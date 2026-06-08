/**
 * Canonical turn-event types aligned with the AL\CE backend.
 *
 * These mirror the additive canonical turn-event stream emitted by the
 * model-driven turn engine — see `backend/services/turn/events.py`. Each
 * server→client frame carries a snake_case shape with a dotted `type`
 * discriminant (e.g. `"turn.started"`); the camelCase view-models below are
 * the client-side projection folded by the `agentRun` Pinia store.
 */

// ---------------------------------------------------------------------------
// WebSocket frames (snake_case — mirror backend/services/turn/events.py)
// ---------------------------------------------------------------------------

/** Server marks the start of a turn. */
export interface WsTurnStartedMessage {
  type: 'turn.started'
  turn_id: string
  conversation_id: string
}

/** Server marks a new LLM iteration (1-based `step`) within a turn. */
export interface WsTurnLlmStepMessage {
  type: 'turn.llm_step'
  turn_id: string
  step: number
}

/** Server signals an outgoing tool invocation. */
export interface WsToolCallMessage {
  type: 'tool.call'
  turn_id: string
  execution_id: string
  tool_name: string
  args: Record<string, unknown>
}

/** Server reports a completed tool invocation. */
export interface WsToolResultMessage {
  type: 'tool.result'
  turn_id: string
  execution_id: string
  tool_name: string
  success: boolean
  result: string
  /** MIME type of an associated artifact (e.g. "image/png"). */
  content_type?: string
  /** UUID of the artifact registered for this tool result, when any. */
  artifact_id?: string
}

/** Kind of mid-turn user interaction surfaced by the engine. */
export type InteractionKind = 'tool_confirmation' | 'client_tool_call' | 'ask_user'

/** Terminal disposition of a resolved interaction. */
export type InteractionOutcome =
  | 'approved'
  | 'rejected'
  | 'answered'
  | 'executed'
  | 'failed'
  | 'cancelled'
  | 'timeout'

/**
 * Server signals a pending user interaction (a confirmation round-trip, a
 * client-side tool call, or an `ask_user` question). Correlates with its
 * later {@link WsInteractionResolvedMessage} — and with the related tool's
 * `tool.call`/`tool.result` — via `execution_id`.
 */
export interface WsInteractionRequestedMessage {
  type: 'interaction.requested'
  turn_id: string
  execution_id: string
  kind: InteractionKind
  /** Name of the tool the interaction relates to, when applicable. */
  tool_name?: string
}

/**
 * Server reports the resolution of a prior interaction. Carries no
 * `tool_name` — correlate back to the request by `execution_id`.
 */
export interface WsInteractionResolvedMessage {
  type: 'interaction.resolved'
  turn_id: string
  execution_id: string
  kind: InteractionKind
  outcome: InteractionOutcome
}

/** Server reports per-step resource usage for a turn. */
export interface WsTurnUsageMessage {
  type: 'turn.usage'
  turn_id: string
  step: number
  input_tokens: number
  output_tokens: number
  tool_calls: number
  max_steps: number
}

/** Server marks the end of a turn. */
export interface WsTurnFinishedMessage {
  type: 'turn.finished'
  turn_id: string
  /** Terminal disposition (e.g. "stop"), or null when not reported. */
  finish_reason: string | null
  input_tokens: number
  output_tokens: number
  steps: number
}

/** Discriminated union of every canonical turn-event server→client frame. */
export type WsTurnEventMessage =
  | WsTurnStartedMessage
  | WsTurnLlmStepMessage
  | WsToolCallMessage
  | WsToolResultMessage
  | WsInteractionRequestedMessage
  | WsInteractionResolvedMessage
  | WsTurnUsageMessage
  | WsTurnFinishedMessage

// ---------------------------------------------------------------------------
// Client view-models (camelCase — folded from the frames above)
// ---------------------------------------------------------------------------

/** Tracks the lifecycle of a single tool execution within an agent run. */
export interface ToolActivity {
  executionId: string
  toolName: string
  args: Record<string, unknown>
  status: 'running' | 'success' | 'error'
  result?: string
  /** MIME type of the result content (e.g. "image/png"). */
  contentType?: string
  /** UUID of the artifact registered for this tool result, when any. */
  artifactId?: string
}

/** Tracks the lifecycle of a single mid-turn user interaction within a run. */
export interface InteractionActivity {
  executionId: string
  kind: InteractionKind
  /** Name of the related tool, when the request carried one. */
  toolName?: string
  status: 'pending' | 'resolved'
  outcome?: InteractionOutcome
}

/** Per-turn "agent run" view-model folded from the canonical event stream. */
export interface AgentRun {
  turnId: string
  conversationId: string
  status: 'running' | 'finished'
  step: number
  maxSteps: number
  tools: ToolActivity[]
  interactions: InteractionActivity[]
  inputTokens: number
  outputTokens: number
  toolCalls: number
  finishReason: string | null
}
