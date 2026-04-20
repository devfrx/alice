/**
 * useAgentRun — Stateful tracker for in-flight agent loop runs.
 *
 * Owns a module-level reactive map keyed by `run_id` plus a secondary
 * index keyed by the `final_assistant_message_id` so the UI can look up
 * the run that produced a specific assistant message.
 *
 * The composable is a singleton: every caller observes the same
 * reactive state.  This mirrors the singleton pattern used by
 * `services/ws.ts` (single WebSocket per renderer).
 *
 * Events are applied via {@link applyAgentEvent}; consumers read the
 * state via {@link agentRuns} or the helper getters.  Linking a run to
 * its final assistant message is done by {@link linkRunToMessage} once
 * the WS `done` event arrives with the persisted message id.
 */

import { computed, reactive, ref, type ComputedRef, type Ref } from 'vue'

import type {
  AgentEvent,
  AgentRun,
  AgentRunMode,
  AgentRunState,
  Plan,
  Step,
} from '../types/agent'

// ---------------------------------------------------------------------------
// Module-level reactive state (singleton)
// ---------------------------------------------------------------------------

/** All known runs, keyed by `run_id`. */
const runs = reactive<Map<string, AgentRun>>(new Map())

/** Secondary index: `assistant_message_id → run_id`. */
const messageIndex = reactive<Map<string, string>>(new Map())

/**
 * Most recently started run that has not yet been linked to an
 * assistant message.  Set on `agent.run_started`, consumed by
 * {@link linkRunToMessage} when the WS `done` event arrives.
 */
const pendingRunId = ref<string | null>(null)

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function _newEmptyRun(
  runId: string,
  complexity: AgentRun['complexity'],
  mode: AgentRunMode = 'agent',
): AgentRun {
  return {
    id: runId,
    conversation_id: '',
    user_message_id: '',
    final_assistant_message_id: null,
    goal: '',
    complexity,
    mode,
    plan: null,
    state: 'planning',
    current_step: 0,
    total_steps: 0,
    replans: 0,
    retries_total: 0,
    total_tokens_in: 0,
    total_tokens_out: 0,
    total_tool_calls: 0,
    verdicts: {},
    critic_sources: {},
    warnings: [],
    pending_question: null,
    started_at: new Date().toISOString(),
    finished_at: null,
    error: null,
  }
}

function _withRun(runId: string | null, mutator: (run: AgentRun) => void): void {
  if (!runId) return
  const run = runs.get(runId)
  if (!run) return
  mutator(run)
  // Re-set so reactive `Map` change tracking fires for any subscriber
  // iterating over `.values()`.
  runs.set(runId, run)
}

function _ensureRun(
  runId: string | null,
  complexity: AgentRun['complexity'] = '',
  mode: AgentRunMode = 'agent',
): AgentRun | null {
  if (!runId) return null
  let run = runs.get(runId)
  if (!run) {
    run = _newEmptyRun(runId, complexity, mode)
    runs.set(runId, run)
  }
  return run
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface UseAgentRunReturn {
  /** All runs known to the renderer (`Map<run_id, AgentRun>`). */
  agentRuns: Map<string, AgentRun>
  /** True when at least one run is in `planning` or `running` state. */
  hasActiveRun: ComputedRef<boolean>
  /** Read-only handle to the most recently started run id (pre-link). */
  pendingRunId: Ref<string | null>

  /** Look up a run by its UUID. */
  getRunById: (runId: string | null | undefined) => AgentRun | null
  /** Look up a run by its associated assistant message id. */
  getRunByMessageId: (messageId: string | null | undefined) => AgentRun | null

  /** Apply an `agent.*` WebSocket event to the local state. */
  applyAgentEvent: (event: AgentEvent) => void
  /** Associate the most recently started run with an assistant message id. */
  linkRunToMessage: (messageId: string) => void
  /** Drop a run from local state (e.g. after the conversation is deleted). */
  removeRun: (runId: string) => void
  /** Reset the entire tracker (used by tests / on logout). */
  reset: () => void
}

/**
 * Singleton composable.  Returns the shared reactive state plus typed
 * helpers for mutation and lookup.
 */
export function useAgentRun(): UseAgentRunReturn {
  const hasActiveRun = computed<boolean>(() => {
    for (const run of runs.values()) {
      if (run.state === 'planning' || run.state === 'running') return true
    }
    return false
  })

  function getRunById(runId: string | null | undefined): AgentRun | null {
    if (!runId) return null
    return runs.get(runId) ?? null
  }

  function getRunByMessageId(messageId: string | null | undefined): AgentRun | null {
    if (!messageId) return null
    const runId = messageIndex.get(messageId)
    if (!runId) return null
    return runs.get(runId) ?? null
  }

  function applyAgentEvent(event: AgentEvent): void {
    switch (event.type) {
      case 'agent.run_started': {
        const mode: AgentRunMode = event.mode ?? 'agent'
        const run = _ensureRun(event.run_id, event.complexity, mode)
        if (run) {
          run.complexity = event.complexity
          run.mode = mode
          run.state = 'planning'
          // Capture the originating user message id when supplied so
          // the activity feed can slice the run's conversation window
          // before the final assistant message arrives.
          if (event.user_message_id) {
            run.user_message_id = event.user_message_id
          }
          pendingRunId.value = event.run_id
        }
        break
      }
      case 'agent.plan_created': {
        _withRun(event.run_id, (run) => {
          run.plan = _normalizePlan(event.plan)
          run.total_steps = event.plan.steps.length
          run.state = 'running'
          run.goal = event.plan.goal || run.goal
        })
        break
      }
      case 'agent.step_started': {
        _withRun(event.run_id, (run) => {
          run.current_step = event.step_index
          run.total_steps = event.total_steps
          run.state = 'running'
          // Patch the step in case the planner changed its description.
          if (run.plan && run.plan.steps[event.step_index]) {
            run.plan.steps[event.step_index] = _normalizeStep(event.step)
          }
        })
        break
      }
      case 'agent.step_completed': {
        _withRun(event.run_id, (run) => {
          run.verdicts[event.step_index] = event.verdict
          if (event.verdict.action === 'retry') {
            run.retries_total += 1
          }
        })
        break
      }
      case 'agent.replanned': {
        _withRun(event.run_id, (run) => {
          run.plan = _normalizePlan(event.new_plan)
          run.total_steps = event.new_plan.steps.length
          // Trust the backend counter when present, fall back to local
          // increment for backwards compatibility.
          run.replans =
            typeof event.replan_count === 'number'
              ? event.replan_count
              : run.replans + 1
        })
        break
      }
      case 'agent.critic_invoked': {
        _withRun(event.run_id, (run) => {
          run.critic_sources[event.step_index] = event.source
        })
        break
      }
      case 'agent.warning': {
        _withRun(event.run_id, (run) => {
          run.warnings.push({ code: event.code, message: event.message })
        })
        break
      }
      case 'agent.ask_user': {
        _withRun(event.run_id, (run) => {
          run.pending_question = event.question
          run.state = 'asked_user'
        })
        break
      }
      case 'agent.run_finished': {
        _withRun(event.run_id, (run) => {
          run.state = event.state as AgentRunState
          run.finished_at = new Date().toISOString()
          if (run.state !== 'done' && !run.error) {
            run.error = run.state
          }
        })
        break
      }
    }
  }

  function linkRunToMessage(messageId: string): void {
    const runId = pendingRunId.value
    if (!runId) return
    const run = runs.get(runId)
    if (!run) {
      pendingRunId.value = null
      return
    }
    run.final_assistant_message_id = messageId
    messageIndex.set(messageId, runId)
    pendingRunId.value = null
  }

  function removeRun(runId: string): void {
    const run = runs.get(runId)
    if (run?.final_assistant_message_id) {
      messageIndex.delete(run.final_assistant_message_id)
    }
    runs.delete(runId)
    if (pendingRunId.value === runId) {
      pendingRunId.value = null
    }
  }

  function reset(): void {
    runs.clear()
    messageIndex.clear()
    pendingRunId.value = null
  }

  return {
    agentRuns: runs,
    hasActiveRun,
    pendingRunId,
    getRunById,
    getRunByMessageId,
    applyAgentEvent,
    linkRunToMessage,
    removeRun,
    reset,
  }
}

// ---------------------------------------------------------------------------
// Normalisers — defensive copies so backend payloads can be mutated freely
// without touching the original event object.
// ---------------------------------------------------------------------------

function _normalizeStep(step: Step): Step {
  return {
    index: step.index,
    description: step.description,
    expected_outcome: step.expected_outcome,
    tool_hint: step.tool_hint ?? null,
  }
}

function _normalizePlan(plan: Plan): Plan {
  return {
    goal: plan.goal,
    steps: plan.steps.map(_normalizeStep),
  }
}
