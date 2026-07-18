/**
 * Chat-related types aligned with the AL\CE backend API.
 *
 * WebSocket frame types (WsToken, WsDone, WsError, etc.) are re-exported from
 * the generated contract (`./generated`, regenerated via `scripts/gen-contracts.ps1`).
 * REST conversation response types are also re-exported from generated contracts.
 * Only view-models (ChatMessage, ConversationDetail, etc.) are hand-written here.
 */

import type { ApiSchema, ChatServerMessage } from './generated'

// ---------------------------------------------------------------------------
// Message
// ---------------------------------------------------------------------------

/** A single tool-call attachment on a message (OpenAI-compatible shape). */
export interface ToolCall {
  id: string
  type: 'function'
  function: {
    name: string
    arguments: string
  }
}

/** A file attachment on a message (image, document, etc.). */
export interface FileAttachment {
  file_id: string
  url: string
  filename: string
  content_type: string
  file_path?: string
}

/** Role a message can have. */
export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

/**
 * A chat message as returned by
 * `GET /api/chat/conversations/{id}`.
 */
export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  tool_calls: ToolCall[] | null
  tool_call_id: string | null
  created_at: string
  thinking_content?: string | null
  attachments?: FileAttachment[] | null
  /** Groups message versions at the same edit point. */
  version_group_id?: string | null
  /** Version index within a version group (0 = original). */
  version_index?: number
  /** True if this message is an LLM-generated context summary. */
  is_context_summary?: boolean
  /** True if this message has been archived from LLM context. */
  context_excluded?: boolean
}

// ---------------------------------------------------------------------------
// Conversation
// ---------------------------------------------------------------------------

/**
 * Full conversation returned by `GET /api/chat/conversations/{id}`.
 * Includes the ordered list of messages.
 */
export interface ConversationDetail {
  id: string
  title: string | null
  created_at: string
  updated_at: string
  messages: ChatMessage[]
  /** Map of version_group_id → active version_index. */
  active_versions?: Record<string, number>
  /** Estimated context window usage (snake_case from backend). */
  context_info?: {
    used: number
    available: number
    context_window: number
    percentage: number
    was_compressed: boolean
    messages_summarized: number
    is_estimated: boolean
    breakdown?: ContextBreakdown
  } | null
  /**
   * Persisted total cost of the conversation, in OpenRouter credits.
   * `null` when nothing billable has been reported (e.g. a local provider).
   * Covers main-turn generations only — subagent/summarization calls are
   * not tracked.
   */
  total_cost?: number | null
}

// ---------------------------------------------------------------------------
// REST response helpers (generated re-exports)
// ---------------------------------------------------------------------------

/**
 * Conversation summary returned by `GET /api/chat/conversations`.
 * Does NOT include the `messages` array — only a count.
 */
export type ConversationSummary = ApiSchema<'ConversationSummaryResponse'>

/** Paginated list of conversation summaries (items + total). */
export type ConversationListResponse = ApiSchema<'ConversationListResponse'>

/** Full conversation export format (for backup/import). */
export type ConversationExport = ApiSchema<'ConversationExport'>

/** Response from `POST /api/chat/conversations/{id}/switch-version`. */
export type SwitchVersionResponse = ApiSchema<'SwitchVersionResponse'>

/** Response from `POST /api/chat/conversations/{id}/branch`. */
export type BranchConversationResponse = ApiSchema<'ConversationSummaryResponse'>

/** Response from `DELETE /api/chat/conversations/{id}`. */
export type DeleteConversationResponse = ApiSchema<'DeleteConversationResponse'>

/** Response from `DELETE /api/chat/conversations` (delete all). */
export type DeleteAllConversationsResponse = ApiSchema<'DeleteAllConversationsResponse'>

/** Result from `POST /api/chat/conversations/backup` (explicit JSON backup). */
export type BackupResult = ApiSchema<'BackupResult'>

/** Response from `POST /api/chat/conversations/{id}/title`. */
export type RenameConversationResponse = ApiSchema<'TitleUpdateResponse'>

/** Request body for `POST /api/chat/conversations/{id}/branch`. */
export type BranchConversationRequest = ApiSchema<'BranchConversationRequest'>

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

/**
 * Generated from the backend WS contract — do not redefine locally.
 *
 * Only the aliases with live consumers are kept: the exhaustive
 * `ChatHandlerMap` dispatcher narrows handler parameters via
 * `Extract<ChatServerMessage, …>`, so the per-frame server aliases live in
 * `types/turn.ts`. The client channel (v2) is the untagged user message,
 * `cancel`, and the unified `interaction.response`.
 */
export type WsSendPayload = ApiSchema<'WsUserMessage'>
export type WsCancelPayload = ApiSchema<'WsCancel'>
/** Unified client→server interaction reply (tool_confirmation / ask_user / client_tool_call). */
export type WsInteractionResponsePayload = ApiSchema<'WsInteractionResponse'>
export type RememberChoice = NonNullable<WsInteractionResponsePayload['remember']>
export type AskUserQuestion = ApiSchema<'WsAskUserQuestion'>
export type AskUserAnswer = ApiSchema<'WsAskUserAnswer'>
export type ContextBreakdown = ApiSchema<'WsContextBreakdown'>

// ---------------------------------------------------------------------------
// CAD / 3D Model
// ---------------------------------------------------------------------------

/** Payload from cad_generate tool (content_type='application/vnd.alice.cad-model+json'). */
export interface CadModelPayload {
  model_name: string
  /** Relative URL of the proxy route: /api/cad/models/{name} */
  export_url: string
  /** Format: always "glb" for TRELLIS */
  format: string
  size_bytes?: number
  description?: string
}

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------

/** Payload from chart_generate tool (content_type='application/vnd.alice.chart+json'). */
export interface ChartPayload {
  chart_id: string
  title: string
  chart_type: string
  /** Relative URL: "/api/artifacts/{chart_id}/content" */
  chart_url: string
  created_at: string
}

// ---------------------------------------------------------------------------
// Whiteboards
// ---------------------------------------------------------------------------

/** Payload from whiteboard tools (content_type='application/vnd.alice.whiteboard+json'). */
export interface WhiteboardPayload {
  board_id: string
  title: string
  /** Relative URL: "/api/artifacts/{board_id}/content" */
  board_url: string
  conversation_id: string | null
  created_at: string
}

/** Type guard: checks if a parsed tool result is a WhiteboardPayload. */
export function isWhiteboardPayload(obj: unknown): obj is WhiteboardPayload {
  return (
    typeof obj === 'object' &&
    obj !== null &&
    'board_id' in obj &&
    'board_url' in obj &&
    'title' in obj
  )
}

/** Type guard: checks if a parsed tool result is a ChartPayload. */
export function isChartPayload(p: unknown): p is ChartPayload {
  if (typeof p !== 'object' || p === null || Array.isArray(p)) return false
  const o = p as Record<string, unknown>
  return (
    typeof o.chart_id === 'string' &&
    typeof o.chart_url === 'string' &&
    typeof o.chart_type === 'string'
  )
}

/**
 * Extract every chart payload from a message list, in chronological order
 * (oldest → newest). Non-tool / non-JSON / non-chart messages are skipped.
 */
export function extractCharts(messages: ChatMessage[]): ChartPayload[] {
  const out: ChartPayload[] = []
  for (const msg of messages) {
    if (msg.role !== 'tool') continue
    try {
      const p = JSON.parse(msg.content) as unknown
      if (isChartPayload(p)) out.push(p)
    } catch {
      // not JSON — skip
    }
  }
  return out
}

// ---------------------------------------------------------------------------
// Tool progress (client-side view-model)
// ---------------------------------------------------------------------------

/** Latest progress frame received from a long-running tool. */
export interface ToolProgressSnapshot {
  /** Implementation-specific high-level phase (e.g. "sampling"). */
  phase?: string
  /** Optional human-readable stage label (e.g. "Shape latent"). */
  label?: string | null
  /** Current step within ``total`` (monotonic). */
  step?: number
  /** Total steps. */
  total?: number
  /** Pre-computed integer percentage (0-100). */
  percent?: number
  /** Wall-clock elapsed since the tool started, in seconds. */
  elapsedS?: number
}

/** A pending tool confirmation awaiting user approval (projected from the fold). */
export interface ConfirmationRequest {
  /** Wire correlation key — sent back in the `interaction.response`. */
  interactionId: string
  /** Tool execution id, kept for tool-chip correlation in the timeline. */
  executionId: string
  toolName: string
  args: Record<string, unknown>
  riskLevel: 'safe' | 'medium' | 'dangerous' | 'forbidden'
  description: string
  /** LLM reasoning for invoking this tool (from thinking content). */
  reasoning?: string
  /**
   * When `true` the server accepts a `remember` choice, so the dialog may
   * offer "don't ask again" (session / persistent) options.
   */
  allowRemember?: boolean
}

/** A pending `ask_user` request awaiting the user's answers (client-side). */
export interface AskUserRequest {
  /** Wire correlation key — sent back in the `interaction.response`. */
  interactionId: string
  /** Tool execution id, kept for tool-chip correlation in the timeline. */
  executionId: string
  questions: AskUserQuestion[]
}

/** Snapshot of context window utilization (camelCase, from WS snake_case). */
export interface ContextInfo {
  used: number
  available: number
  contextWindow: number
  /**
   * Fraction of the context window in use.
   * Always in the range [0, 1] — multiply by 100 for a percentage value.
   */
  percentage: number
  wasCompressed: boolean
  messagesSummarized: number
  isEstimated: boolean
  breakdown?: ContextBreakdown
}

/** Discriminated union of all server→client chat frames (generated). */
export type WsMessage = ChatServerMessage
