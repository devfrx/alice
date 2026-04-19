/**
 * Chat-related types aligned with the AL\CE backend API.
 *
 * Every interface here mirrors the JSON shapes returned by
 * `backend/api/routes/chat.py` so the frontend can consume
 * responses without transformation.
 */

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
 * Conversation summary returned by `GET /api/chat/conversations`.
 * Does NOT include the `messages` array — only a count.
 */
export interface ConversationSummary {
  id: string
  title: string | null
  created_at: string
  updated_at: string
  message_count: number
}

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
}

// ---------------------------------------------------------------------------
// REST response helpers
// ---------------------------------------------------------------------------

/** Response from `DELETE /api/chat/conversations/{id}`. */
export interface DeleteConversationResponse {
  status: 'deleted'
}

/** Response from `DELETE /api/chat/conversations` (delete all). */
export interface DeleteAllConversationsResponse {
  status: 'deleted'
  deleted_files: number
}

/** Response from `POST /api/chat/conversations/{id}/title`. */
export interface RenameConversationResponse {
  id: string
  title: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

/** Payload the client sends over the WebSocket. */
export interface WsSendPayload {
  content: string
  conversation_id?: string
  attachments?: string[]
  /** When set, this message is an edit of the specified user message. */
  edit_message_id?: string
}

/** A streamed token frame from the server. */
export interface WsTokenMessage {
  type: 'token'
  content: string
}

/** A thinking token frame from the server. */
export interface WsThinkingMessage {
  type: 'thinking'
  content: string
}

/** Server signals the response is complete. */
export interface WsDoneMessage {
  type: 'done'
  conversation_id: string
  message_id: string
  /** Server-assigned ID for the user message. */
  user_message_id?: string
  finish_reason?: string
  /** Version group for the completed response (if message was edited). */
  version_group_id?: string | null
  /** Version index within the group. */
  version_index?: number
}

/** Payload the client sends to cancel an in-progress generation. */
export interface WsCancelPayload {
  type: 'cancel'
}

/** Server reports an error. */
export interface WsErrorMessage {
  type: 'error'
  content: string
}

/** Server signals a tool has started executing. */
export interface WsToolExecutionStartMessage {
  type: 'tool_execution_start'
  tool_name: string
  execution_id: string
}

/** Server signals a tool has finished executing. */
export interface WsToolExecutionDoneMessage {
  type: 'tool_execution_done'
  tool_name: string
  result: string
  execution_id: string
  success: boolean
  /** MIME type of the result content (e.g. "image/png"). */
  content_type?: string
  /**
   * UUID of the artifact registered for this tool result, when the tool
   * produced a binary output that the artifacts registry parsed
   * (e.g. ``cad_generate``). Absent for tools without a parser or when
   * registration failed silently.
   */
  artifact_id?: string
}

/** Server requests user confirmation before running a tool. */
export interface WsToolConfirmationRequiredMessage {
  type: 'tool_confirmation_required'
  tool_name: string
  args: Record<string, unknown>
  execution_id: string
  risk_level: 'safe' | 'medium' | 'dangerous' | 'forbidden'
  description: string
  /** LLM reasoning/thinking content explaining why this tool was called. */
  reasoning?: string
}

/** Payload the client sends to approve/reject a tool confirmation. */
export interface WsToolConfirmationResponsePayload {
  type: 'tool_confirmation_response'
  execution_id: string
  approved: boolean
}

/** Server signals it is re-querying the LLM after tool execution. */
export interface WsLlmRequeryMessage {
  type: 'llm_requery'
  iteration: number
}

/** Server sends a warning message. */
export interface WsWarningMessage {
  type: 'warning'
  content: string
}

/** Per-category token usage breakdown sent with context_info events. */
export interface ContextBreakdown {
  system: number
  tools: number
  messages: number
  files: number
  tool_results: number
  other: number
}

/** Server sends context window usage information. */
export interface WsContextInfoMessage {
  type: 'context_info'
  used: number
  available: number
  context_window: number
  percentage: number
  was_compressed: boolean
  messages_summarized: number
  is_estimated: boolean
  breakdown?: ContextBreakdown
}

/** Server signals context compression has started. */
export interface WsContextCompressionStartMessage {
  type: 'context_compression_start'
}

/** Server signals context compression completed. */
export interface WsContextCompressionDoneMessage {
  type: 'context_compression_done'
  messages_summarized: number
  summary_message_id?: string
}

/** Server signals context compression failed. */
export interface WsContextCompressionFailedMessage {
  type: 'context_compression_failed'
}

/** Server signals the LLM wants to invoke a tool (forwarded from LLM stream). */
export interface WsToolCallMessage {
  type: 'tool_call'
  id: string
  function: {
    name: string
    arguments: string
  }
}

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
  /** Relative URL: "/api/charts/{chart_id}" */
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
  /** Relative URL: "/api/whiteboards/{board_id}" */
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

// ---------------------------------------------------------------------------
// Tool execution tracking (client-side)
// ---------------------------------------------------------------------------

/** Tracks the lifecycle of a single tool execution during streaming. */
export interface ToolExecution {
  executionId: string
  toolName: string
  status: 'running' | 'done' | 'error'
  result?: string
  success?: boolean
  /** MIME type of the result content (e.g. "image/png"). */
  contentType?: string
}

/** A pending tool confirmation awaiting user approval. */
export interface ConfirmationRequest {
  executionId: string
  toolName: string
  args: Record<string, unknown>
  riskLevel: 'safe' | 'medium' | 'dangerous' | 'forbidden'
  description: string
  /** LLM reasoning for invoking this tool (from thinking content). */
  reasoning?: string
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

/** Discriminated union of all server→client WebSocket frames. */
export type WsMessage =
  | WsTokenMessage
  | WsThinkingMessage
  | WsDoneMessage
  | WsErrorMessage
  | WsToolCallMessage
  | WsToolExecutionStartMessage
  | WsToolExecutionDoneMessage
  | WsToolConfirmationRequiredMessage
  | WsLlmRequeryMessage
  | WsWarningMessage
  | WsContextInfoMessage
  | WsContextCompressionStartMessage
  | WsContextCompressionDoneMessage
  | WsContextCompressionFailedMessage

// ---------------------------------------------------------------------------
// Export / Import
// ---------------------------------------------------------------------------

/** Full conversation export format (for backup/import). */
export interface ConversationExport {
  id: string
  title: string | null
  created_at: string
  updated_at: string
  messages: ChatMessage[]
  active_versions?: Record<string, number>
}

/** Response from `POST /api/chat/conversations/{id}/switch-version`. */
export interface SwitchVersionResponse {
  id: string
  active_versions: Record<string, number>
  updated_at: string
}

/** Request body for `POST /api/chat/conversations/{id}/branch`. */
export interface BranchConversationRequest {
  from_message_id: string
  title?: string
}

/** Response from `POST /api/chat/conversations/{id}/branch`. */
export interface BranchConversationResponse {
  id: string
  title: string | null
  created_at: string
  updated_at: string
  message_count: number
}
