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

/** Critic decision about a step's output. */
export interface Verdict {
  action: VerdictAction
  reason: string
  question?: string | null
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
  | AgentAskUserMessage
  | AgentRunFinishedMessage

// ---------------------------------------------------------------------------
// Per-step UI status (derived state)
// ---------------------------------------------------------------------------

/** Visual status of a single step inside the plan card. */
export type StepStatus = 'pending' | 'in_progress' | 'done' | 'retry' | 'failed' | 'skipped'
