/**
 * Canonical turn-event types aligned with the AL\CE backend.
 *
 * WebSocket frame types (WsTurnStarted, WsTurnFinished, etc.) are re-exported
 * from the generated contract (`./generated`, regenerated via
 * `scripts/gen-contracts.ps1`); the source of truth is
 * `backend/api/ws_schema/` → `backend/services/turn/events.py`.
 * The camelCase view-models below (AgentRun, ToolActivity, etc.) are
 * hand-written client-side projections folded by the `agentRun` Pinia store.
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
  /** Cost of this turn's generations, in OpenRouter credits; `null` for local providers. */
  cost: number | null
}
