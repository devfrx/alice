/**
 * agentRun.ts — Pinia setup-store folding the canonical turn-event stream.
 *
 * Each server→client turn-event frame (see `types/turn.ts`, mirroring
 * `backend/services/turn/events.py`) is applied through an idempotent action
 * that folds it into a per-turn {@link AgentRun} view-model keyed by `turnId`.
 *
 * Frames may arrive out of order (e.g. a `tool.result` before its
 * `tool.call`, or any frame before `turn.started`), so every apply path goes
 * through {@link ensureRun}, which lazily materialises a minimal `running`
 * run rather than throwing. Reactivity is preserved by reassigning the
 * `runs` record / `tools` arrays (new objects) and mutating run fields through
 * the reactive proxy returned by {@link ensureRun}.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type {
  AgentRun,
  ToolActivity,
  WsToolCallMessage,
  WsToolResultMessage,
  WsTurnFinishedMessage,
  WsTurnLlmStepMessage,
  WsTurnStartedMessage,
  WsTurnUsageMessage,
} from '../types/turn'

export const useAgentRunStore = defineStore('agentRun', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  /** All agent runs known to the client, keyed by `turnId`. */
  const runs = ref<Record<string, AgentRun>>({})

  /** Turn id of the most recently started run (drives {@link currentRun}). */
  const currentTurnId = ref<string | null>(null)

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  /** The run for {@link currentTurnId}, or null when none is active. */
  const currentRun = computed<AgentRun | null>(() =>
    currentTurnId.value ? runs.value[currentTurnId.value] ?? null : null,
  )

  /** Lookup helper: the run for a given turn id, if known. */
  function runByTurnId(id: string): AgentRun | null {
    return runs.value[id] ?? null
  }

  // -----------------------------------------------------------------------
  // Internal helpers
  // -----------------------------------------------------------------------

  /**
   * Return the existing run for `turnId`, lazily creating a minimal
   * `running` run when absent so out-of-order frames never throw.
   *
   * Always returns the reactive proxy stored in {@link runs}, so callers
   * can mutate run fields in place and have the change tracked.
   */
  function ensureRun(turnId: string, conversationId?: string): AgentRun {
    const existing = runs.value[turnId]
    if (existing) return existing
    const run: AgentRun = {
      turnId,
      conversationId: conversationId ?? '',
      status: 'running',
      step: 0,
      maxSteps: 0,
      tools: [],
      inputTokens: 0,
      outputTokens: 0,
      toolCalls: 0,
      finishReason: null,
    }
    runs.value = { ...runs.value, [turnId]: run }
    return runs.value[turnId]
  }

  // -----------------------------------------------------------------------
  // Apply actions (idempotent — one per canonical frame)
  // -----------------------------------------------------------------------

  /** `turn.started` → create/replace the run and mark it current. */
  function applyTurnStarted(msg: WsTurnStartedMessage): void {
    const run: AgentRun = {
      turnId: msg.turn_id,
      conversationId: msg.conversation_id,
      status: 'running',
      step: 0,
      maxSteps: 0,
      tools: [],
      inputTokens: 0,
      outputTokens: 0,
      toolCalls: 0,
      finishReason: null,
    }
    runs.value = { ...runs.value, [msg.turn_id]: run }
    currentTurnId.value = msg.turn_id
  }

  /** `turn.llm_step` → advance the run's step counter. */
  function applyLlmStep(msg: WsTurnLlmStepMessage): void {
    const run = ensureRun(msg.turn_id)
    run.step = msg.step
  }

  /** `tool.call` → append a `running` tool activity (dedup by executionId). */
  function applyToolCall(msg: WsToolCallMessage): void {
    const run = ensureRun(msg.turn_id)
    if (run.tools.some((t) => t.executionId === msg.execution_id)) return
    const activity: ToolActivity = {
      executionId: msg.execution_id,
      toolName: msg.tool_name,
      args: msg.args,
      status: 'running',
    }
    run.tools = [...run.tools, activity]
  }

  /** `tool.result` → resolve the matching tool activity (create if absent). */
  function applyToolResult(msg: WsToolResultMessage): void {
    const run = ensureRun(msg.turn_id)
    const status: ToolActivity['status'] = msg.success ? 'success' : 'error'
    const idx = run.tools.findIndex((t) => t.executionId === msg.execution_id)
    if (idx === -1) {
      const activity: ToolActivity = {
        executionId: msg.execution_id,
        toolName: msg.tool_name,
        args: {},
        status,
        result: msg.result,
        contentType: msg.content_type,
        artifactId: msg.artifact_id,
      }
      run.tools = [...run.tools, activity]
      return
    }
    const updated: ToolActivity = {
      ...run.tools[idx],
      status,
      result: msg.result,
      contentType: msg.content_type,
      artifactId: msg.artifact_id,
    }
    run.tools = [...run.tools.slice(0, idx), updated, ...run.tools.slice(idx + 1)]
  }

  /** `turn.usage` → record per-step token/tool counters. */
  function applyTurnUsage(msg: WsTurnUsageMessage): void {
    const run = ensureRun(msg.turn_id)
    run.step = msg.step
    run.inputTokens = msg.input_tokens
    run.outputTokens = msg.output_tokens
    run.toolCalls = msg.tool_calls
    run.maxSteps = msg.max_steps
  }

  /** `turn.finished` → mark the run finished with its terminal disposition. */
  function applyTurnFinished(msg: WsTurnFinishedMessage): void {
    const run = ensureRun(msg.turn_id)
    run.status = 'finished'
    run.finishReason = msg.finish_reason
    run.inputTokens = msg.input_tokens
    run.outputTokens = msg.output_tokens
    run.step = msg.steps
  }

  /** Clear all runs and the current-turn pointer. */
  function reset(): void {
    runs.value = {}
    currentTurnId.value = null
  }

  return {
    // state
    runs,
    currentTurnId,
    // getters
    currentRun,
    runByTurnId,
    // actions
    applyTurnStarted,
    applyLlmStep,
    applyToolCall,
    applyToolResult,
    applyTurnUsage,
    applyTurnFinished,
    reset,
  }
})
