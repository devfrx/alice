/**
 * Canonical turn-event types aligned with the AL\CE backend.
 *
 * WebSocket frame types (WsTurnStarted, WsTurnFinished, etc.) are re-exported
 * from the generated contract (`./generated`, regenerated via
 * `scripts/gen-contracts.ps1`); the source of truth is
 * `backend/api/ws_schema/chat.py` → `backend/services/agent/adapters/wire.py`
 * (the v2 vocabulary, spec §4). The camelCase view-models below (AgentRun,
 * ToolActivity, etc.) are hand-written client-side projections folded by the
 * `agentRun` Pinia store.
 */

import type { ApiSchema } from './generated'
import type { AskUserQuestion } from './chat'

// ---------------------------------------------------------------------------
// WebSocket frames (server→client — generated from ws_schema, v2 vocabulary)
// ---------------------------------------------------------------------------

/** Generated from the backend WS contract — do not redefine locally. */
export type WsTurnStartedMessage = ApiSchema<'WsTurnStarted'>
export type WsTurnDeltaMessage = ApiSchema<'WsTurnDelta'>
export type WsTurnLlmStepMessage = ApiSchema<'WsTurnLlmStep'>
export type WsToolCallMessage = ApiSchema<'WsTurnToolCall'>
export type WsToolStartedMessage = ApiSchema<'WsToolStarted'>
export type WsToolProgressMessage = ApiSchema<'WsToolProgress'>
export type WsToolResultMessage = ApiSchema<'WsTurnToolResult'>
export type WsInteractionRequestedMessage = ApiSchema<'WsInteractionRequested'>
export type WsInteractionResolvedMessage = ApiSchema<'WsInteractionResolved'>
export type WsContextUsageMessage = ApiSchema<'WsContextUsage'>
export type WsContextCompactionMessage = ApiSchema<'WsContextCompaction'>
export type WsTurnWarningMessage = ApiSchema<'WsTurnWarning'>
export type WsTurnErrorMessage = ApiSchema<'WsTurnError'>
export type WsTurnUsageMessage = ApiSchema<'WsTurnUsage'>
export type WsTurnFinishedMessage = ApiSchema<'WsTurnFinished'>

/** Derived from the generated contract. */
export type InteractionKind = WsInteractionRequestedMessage['kind']
export type InteractionOutcome = WsInteractionResolvedMessage['outcome']

/** Discriminated union of every canonical turn-event server→client frame. */
export type WsTurnEventMessage =
  | WsTurnStartedMessage
  | WsTurnDeltaMessage
  | WsTurnLlmStepMessage
  | WsToolCallMessage
  | WsToolStartedMessage
  | WsToolProgressMessage
  | WsToolResultMessage
  | WsInteractionRequestedMessage
  | WsInteractionResolvedMessage
  | WsContextUsageMessage
  | WsContextCompactionMessage
  | WsTurnWarningMessage
  | WsTurnErrorMessage
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
  /**
   * Raw engine outcome status (ok/error/denied/timeout/…), preserved verbatim
   * for richer chips. `status` above is the coarse UI bucket derived from it.
   */
  rawStatus?: string
  /** Latest `tool.progress` snapshot (the tool's own nested payload, verbatim). */
  progress?: Record<string, unknown>
  /** Monotonic insertion order within the run (interleaves tools + interactions). */
  seq: number
}

/** Tracks the lifecycle of a single mid-turn user interaction within a run. */
export interface InteractionActivity {
  /** Wire correlation key of the interaction (matches `interaction.response`). */
  interactionId: string
  executionId: string
  kind: InteractionKind
  /** Name of the related tool, when the request carried one. */
  toolName?: string
  status: 'pending' | 'resolved'
  outcome?: InteractionOutcome
  /** Tool arguments (tool_confirmation / client_tool_call). */
  args?: Record<string, unknown>
  /** Risk tier of the gated tool (tool_confirmation). */
  riskLevel?: string
  /** Human-readable description of the gated action (tool_confirmation). */
  description?: string
  /** LLM reasoning behind the request (tool_confirmation). */
  reasoning?: string
  /** Whether the server accepts a `remember` choice (tool_confirmation). */
  allowRemember?: boolean
  /** Questions carried by an `ask_user` request. */
  questions?: AskUserQuestion[]
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
