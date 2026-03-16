/**
 * Chat-related types aligned with the OMNIA backend API.
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
  finish_reason?: string
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
}
