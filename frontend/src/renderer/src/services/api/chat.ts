/** Chat conversation endpoints (`/api/chat`). */
import { request, resolveBackendUrl, BASE_URL } from './http'
import type {
  BackupResult,
  BranchConversationRequest,
  BranchConversationResponse,
  ConversationDetail,
  ConversationExport,
  ConversationListResponse,
  ConversationSummary,
  DeleteAllConversationsResponse,
  DeleteConversationResponse,
  FileAttachment,
  RenameConversationResponse,
  SwitchVersionResponse
} from '../../types/chat'

export const chatApi = {
  /** List all conversations (most recent first). */
  getConversations: (): Promise<ConversationListResponse> =>
    request<ConversationListResponse>('/chat/conversations'),

  /** Create a new empty conversation on the backend. */
  createConversation: (id: string, title?: string): Promise<ConversationSummary> =>
    request<ConversationSummary>('/chat/conversations', {
      method: 'POST',
      body: JSON.stringify({ id, title: title ?? null })
    }),

  /** Export a conversation as JSON. */
  exportConversation: (id: string): Promise<ConversationExport> =>
    request<ConversationExport>(`/chat/conversations/${encodeURIComponent(id)}/export`),

  /** Export conversations as JSON files to a directory (explicit backup). */
  backupConversations: (destDir?: string, conversationIds?: string[]): Promise<BackupResult> =>
    request<BackupResult>('/chat/conversations/backup', {
      method: 'POST',
      body: JSON.stringify({
        dest_dir: destDir ?? null,
        conversation_ids: conversationIds ?? null
      })
    }),

  /** Import a conversation from JSON. */
  importConversation: (data: ConversationExport): Promise<ConversationSummary> =>
    request<ConversationSummary>('/chat/conversations/import', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  /** Fetch a single conversation with its full message list. */
  getConversation: (id: string, signal?: AbortSignal): Promise<ConversationDetail> =>
    request<ConversationDetail>(`/chat/conversations/${encodeURIComponent(id)}`, { signal }),

  /** Delete a conversation and all its messages. */
  deleteConversation: (id: string): Promise<DeleteConversationResponse> =>
    request<DeleteConversationResponse>(`/chat/conversations/${encodeURIComponent(id)}`, {
      method: 'DELETE'
    }),

  /** Delete ALL conversations, messages, and files. */
  deleteAllConversations: (): Promise<DeleteAllConversationsResponse> =>
    request<DeleteAllConversationsResponse>('/chat/conversations', { method: 'DELETE' }),

  /** Rename a conversation. */
  renameConversation: (id: string, title: string): Promise<RenameConversationResponse> =>
    request<RenameConversationResponse>(`/chat/conversations/${encodeURIComponent(id)}/title`, {
      method: 'POST',
      body: JSON.stringify({ title })
    }),

  /** Switch the active version for a message version group. */
  switchVersion: (
    conversationId: string,
    versionGroupId: string,
    versionIndex: number
  ): Promise<SwitchVersionResponse> =>
    request<SwitchVersionResponse>(
      `/chat/conversations/${encodeURIComponent(conversationId)}/switch-version`,
      {
        method: 'POST',
        body: JSON.stringify({
          version_group_id: versionGroupId,
          version_index: versionIndex
        })
      }
    ),

  /**
   * Branch a conversation from a specific message.
   *
   * Creates a new conversation containing all messages from the start
   * of {@link conversationId} up through {@link fromMessageId} (inclusive,
   * following the active version branch).
   *
   * @param conversationId - Source conversation UUID.
   * @param fromMessageId - UUID of the last message to copy (inclusive).
   * @param title - Optional title override for the new conversation.
   * @returns Metadata for the newly created conversation.
   */
  branchConversation: (
    conversationId: string,
    fromMessageId: string,
    title?: string
  ): Promise<BranchConversationResponse> => {
    const body: BranchConversationRequest = { from_message_id: fromMessageId }
    if (title) body.title = title
    return request<BranchConversationResponse>(
      `/chat/conversations/${encodeURIComponent(conversationId)}/branch`,
      {
        method: 'POST',
        body: JSON.stringify(body)
      }
    )
  },

  /**
   * Upload a file attachment for a conversation.
   *
   * @param file           - The `File` object to upload.
   * @param conversationId - Target conversation ID.
   * @returns The created {@link FileAttachment} metadata.
   */
  uploadFile: async (file: File, conversationId: string): Promise<FileAttachment> => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('conversation_id', conversationId)
    const response = await fetch(`${BASE_URL}/chat/upload`, {
      method: 'POST',
      body: formData
    })
    if (!response.ok) {
      const body = await response.text().catch(() => '')
      throw new Error(`Upload failed ${response.status}: ${body}`)
    }
    const data: FileAttachment = await response.json()
    // Resolve relative URL to absolute backend URL so images load in Electron.
    data.url = resolveBackendUrl(data.url)
    return data
  }
}
