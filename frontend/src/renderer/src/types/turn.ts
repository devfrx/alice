/**
 * Canonical turn-event types aligned with the AL\CE backend.
 *
 * These mirror the additive canonical turn-event stream emitted by the
 * model-driven turn engine — see `backend/services/turn/events.py`. Each
 * server→client frame carries a snake_case shape with a dotted `type`
 * discriminant (e.g. `"turn.started"`); the camelCase view-models below are
 * the client-side projection folded by the `agentRun` Pinia store.
 */

import type { ApiSchema } from './generated'

// ---------------------------------------------------------------------------
// WebSocket frames (server→client — generated from ws_schema)
// ---------------------------------------------------------------------------

/** Generated from the backend WS contract — do not redefine locally. */
export type WsTurnStartedMessage = ApiSchema<'WsTurnStarted'>
export type WsTurnLlmStepMessage = ApiSchema<'WsTurnLlmStep'>
export type WsToolCallMessage = ApiSchema<'WsTurnToolCall'>
export type WsToolResultMessage = ApiSchema<'WsTurnToolResult'>
export type WsInteractionRequestedMessage = ApiSchema<'WsInteractionRequested'>
export type WsInteractionResolvedMessage = ApiSchema<'WsInteractionResolved'>
export type WsTurnUsageMessage = ApiSchema<'WsTurnUsage'>
export type WsTurnFinishedMessage = ApiSchema<'WsTurnFinished'>

/** Derived from the generated contract. */
export type InteractionKind = WsInteractionRequestedMessage['kind']
export type InteractionOutcome = WsInteractionResolvedMessage['outcome']

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
  /** Monotonic insertion order within the run (interleaves tools + interactions). */
  seq: number
}

/** Tracks the lifecycle of a single mid-turn user interaction within a run. */
export interface InteractionActivity {
  executionId: string
  kind: InteractionKind
  /** Name of the related tool, when the request carried one. */
  toolName?: string
  status: 'pending' | 'resolved'
  outcome?: InteractionOutcome
  /** Monotonic insertion order within the run (interleaves tools + interactions). */
  seq: number
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
