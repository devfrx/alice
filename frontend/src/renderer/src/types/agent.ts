/**
 * Agent Loop v2 — TypeScript types mirroring the backend contract.
 *
 * Source of truth:
 *   - Domain models: `backend/services/agent/models.py`
 *   - DB row:        `backend/db/models.py::AgentRun`
 *   - WS events:     `backend/services/turn/agent_executor.py` (and §6 of
 *                    `agent_loop_plan.md`).
 *
 * Field names match the backend snake_case shape so payloads can be
 * consumed without transformation.
 */

// ---------------------------------------------------------------------------
// Domain enums
// ---------------------------------------------------------------------------

/** Complexity classes inferred by the classifier. */
export type TaskComplexity = 'trivial' | 'open_ended' | 'single_tool' | 'multi_step'

/**
 * Execution mode of an agent run.
 *
 * - `agent`  : full plan/execute/critic loop.
 * - `bypass` : direct LLM answer with critic verification only — no
 *              plan, no per-step events.  Used for trivial / single-shot
 *              requests.
 */
export type AgentRunMode = 'agent' | 'bypass'

/**
 * Origin of the complexity classification.
 *
 * - `heuristic`: deterministic regex/length rules.
 * - `llm`      : an LLM call decided.
 * - `default`  : fallback when both above failed.
 */
export type ClassificationSource = 'heuristic' | 'llm' | 'default'

/** Outcome action proposed by the critic for a completed step. */
export type VerdictAction = 'ok' | 'retry' | 'replan' | 'ask_user' | 'abort'

/** Lifecycle state of an `AgentRun`. */
export type AgentRunState =
  | 'planning'
  | 'running'
  | 'done'
  | 'failed'
  | 'cancelled'
  | 'asked_user'

// ---------------------------------------------------------------------------
// Domain models
// ---------------------------------------------------------------------------

/** One actionable unit inside a Plan. */
export interface Step {
  index: number
  description: string
  expected_outcome: string
  tool_hint?: string | null
}

/** An ordered list of steps that together satisfy the user's goal. */
export interface Plan {
  goal: string
  steps: Step[]
}

/**
 * Source of a critic verdict.
 *
 * - `detector`: the verdict was produced by the local pre-LLM
 *   degeneration detector (no LLM round-trip).
 * - `llm`     : the verdict was produced by the critic LLM.
 * - `fallback`: the verdict was synthesised when the critic could not
 *   produce a structured response (parse error, timeout, …).
 */
export type VerdictSource = 'detector' | 'llm' | 'fallback'

/** Critic decision about a step's output. */
export interface Verdict {
  action: VerdictAction
  reason: string
  question?: string | null
  /**
   * Origin of the verdict — populated by `CriticService.evaluate`.
   * Optional for forward compatibility with older backends.
   */
  source?: VerdictSource | null
}

// ---------------------------------------------------------------------------
// AgentRun (mirrors `backend/db/models.py::AgentRun`)
// ---------------------------------------------------------------------------

/**
 * Persistence-shaped representation of a single agent-loop execution.
 * Front-end-side this is built incrementally from the `agent.*`
 * WebSocket events; some fields stay 0/null until the matching event
 * arrives.
 */
export interface AgentRun {
  id: string
  conversation_id: string
  user_message_id: string
  final_assistant_message_id: string | null

  goal: string
  complexity: TaskComplexity | ''
  /**
   * Execution mode: `agent` runs through the full plan/execute/critic
   * loop, `bypass` is a direct LLM answer with critic verification
   * only.  Defaults to `agent` for backwards compatibility.
   */
  mode: AgentRunMode
  /** Live plan (kept in sync with `agent.plan_created` / `agent.replanned`). */
  plan: Plan | null
  state: AgentRunState
  current_step: number
  total_steps: number
  replans: number
  retries_total: number

  total_tokens_in: number
  total_tokens_out: number
  total_tool_calls: number

  /** Per-step verdicts, indexed by `step_index`. */
  verdicts: Record<number, Verdict>
  /**
   * Per-step source of the latest critic verdict, indexed by
   * `step_index`.  Populated by `agent.critic_invoked` events; used
   * by the UI to render an "auto" badge for detector-driven
   * verdicts (no LLM call).
   */
  critic_sources: Record<number, VerdictSource>
  /** Soft warnings emitted by the agent loop during this run. */
  warnings: { code: string; message: string }[]
  /** Question raised by an `agent.ask_user` event, if any. */
  pending_question: string | null

  started_at: string
  finished_at: string | null
  error: string | null
}

// ---------------------------------------------------------------------------
// WebSocket events (discriminated union)
// ---------------------------------------------------------------------------

export interface AgentRunStartedMessage {
  type: 'agent.run_started'
  /** Null when persistence failed and no row could be created. */
  run_id: string | null
  complexity: TaskComplexity
  /**
   * Execution mode chosen by the dispatcher.  Backwards-compatible:
   * older backends omit it and the UI defaults to `agent`.
   */
  mode?: AgentRunMode
  /**
   * Id of the user message that triggered this run.  Used by the
   * activity feed to slice the conversation window owned by the run
   * before the final assistant message id is known.  Optional for
   * backwards compatibility with older backends.
   */
  user_message_id?: string
}

export interface AgentPlanCreatedMessage {
  type: 'agent.plan_created'
  run_id: string | null
  plan: Plan
}

export interface AgentStepStartedMessage {
  type: 'agent.step_started'
  run_id: string | null
  step_index: number
  total_steps: number
  step: Step
}

export interface AgentStepCompletedMessage {
  type: 'agent.step_completed'
  run_id: string | null
  step_index: number
  verdict: Verdict
}

export interface AgentReplannedMessage {
  type: 'agent.replanned'
  run_id: string | null
  new_plan: Plan
  /** Total number of replans performed for this run so far. */
  replan_count: number
}

/**
 * Emitted every time the critic produces a verdict for a step,
 * regardless of whether the verdict came from the local detector or
 * an actual LLM call.  Allows the UI to surface a small "auto" badge
 * for detector-driven verdicts.
 */
export interface AgentCriticInvokedMessage {
  type: 'agent.critic_invoked'
  run_id: string | null
  step_index: number
  source: VerdictSource
}

/**
 * Soft, non-blocking diagnostic from the agent loop (e.g. critic
 * unsatisfied on a bypass path with no recovery, single_tool promoted
 * to mini-plan).  The user-visible result is still returned, but the
 * UI can surface this to explain that something was suboptimal.
 */
export interface AgentWarningMessage {
  type: 'agent.warning'
  run_id: string | null
  /** Short machine-readable identifier (e.g. `degenerated_output`). */
  code: string
  /** Human-readable diagnostic. */
  message: string
}

export interface AgentAskUserMessage {
  type: 'agent.ask_user'
  run_id: string | null
  question: string
}

export interface AgentRunFinishedMessage {
  type: 'agent.run_finished'
  run_id: string | null
  state: AgentRunState
}

/** Discriminated union of every `agent.*` server → client frame. */
export type AgentEvent =
  | AgentRunStartedMessage
  | AgentPlanCreatedMessage
  | AgentStepStartedMessage
  | AgentStepCompletedMessage
  | AgentReplannedMessage
  | AgentCriticInvokedMessage
  | AgentWarningMessage
  | AgentAskUserMessage
  | AgentRunFinishedMessage

// ---------------------------------------------------------------------------
// Per-step UI status (derived state)
// ---------------------------------------------------------------------------

/** Visual status of a single step inside the plan card. */
export type StepStatus = 'pending' | 'in_progress' | 'done' | 'retry' | 'failed' | 'skipped'
