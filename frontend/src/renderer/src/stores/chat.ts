/**
 * Pinia store managing chat state for the OMNIA assistant.
 *
 * Responsibilities:
 * - Maintain the sidebar conversation list (`conversations`)
 * - Track the active conversation (`currentConversation`)
 * - Accumulate streaming tokens from the WebSocket
 * - Dispatch REST calls via `services/api.ts`
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, resolveBackendUrl } from '../services/api'
import type {
  ChatMessage,
  ConversationDetail,
  ConversationExport,
  ConversationSummary,
  FileAttachment
} from '../types/chat'

export const useChatStore = defineStore('chat', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  /** All conversations for the sidebar (summary only, no messages). */
  const conversations = ref<ConversationSummary[]>([])

  /** The currently open conversation (includes messages). */
  const currentConversation = ref<ConversationDetail | null>(null)

  /** Whether the LLM is currently streaming a response. */
  const isStreaming = ref(false)

  /** The conversation ID for which streaming is currently active. */
  const streamingConversationId = ref<string | null>(null)

  /** Tokens accumulated so far for the in-progress assistant response. */
  const currentStreamContent = ref('')

  /** Thinking tokens accumulated for the in-progress assistant response. */
  const currentThinkingContent = ref('')

  /** Monotonically increasing counter to detect stale stream events. */
  const streamGeneration = ref(0)

  /** True between sending a user message and receiving the first token/thinking. */
  const isWaitingForResponse = ref(false)

  /** True while a cancel has been sent but the server hasn't confirmed yet. */
  const isCancelling = ref(false)

  /** Files selected by the user but not yet uploaded. */
  const pendingAttachments = ref<File[]>([])

  // -----------------------------------------------------------------------
  // Computed
  // -----------------------------------------------------------------------

  /** Messages of the active conversation (empty array when none). */
  const messages = computed<ChatMessage[]>(
    () => currentConversation.value?.messages ?? []
  )

  // -----------------------------------------------------------------------
  // REST actions
  // -----------------------------------------------------------------------

  /** Fetch the conversation list from the backend. */
  async function loadConversations(): Promise<void> {
    const remote = await api.getConversations()

    // Merge: keep any locally-created conversations that the backend
    // does not know about yet (created while backend was down).
    const remoteIds = new Set(remote.map((c) => c.id))
    const localOnly = conversations.value.filter(
      (c) => !remoteIds.has(c.id) && c.message_count === 0
    )

    // Try to persist orphan local-only conversations to the backend.
    for (const orphan of localOnly) {
      api
        .createConversation(orphan.id, orphan.title ?? undefined)
        .then((persisted) => {
          // Write back authoritative server timestamps.
          orphan.created_at = persisted.created_at
          orphan.updated_at = persisted.updated_at
        })
        .catch(() => {
          // Backend still unreachable — keep local, retry next load.
        })
    }

    conversations.value = [...localOnly, ...remote]
  }

  /** Load a full conversation (with messages) and set it as active. */
  async function loadConversation(id: string): Promise<void> {
    // NOTE: Do NOT cancel any in-progress stream for a different conversation.
    // The stream continues accumulating in the background; when it completes,
    // finalizeStream() will handle cleanup without touching the UI.

    // If the conversation only exists locally (created but no message sent yet),
    // skip the API call — the backend doesn't know about it and would return 404.
    const summary = conversations.value.find((c) => c.id === id)
    if (summary && summary.message_count === 0) {
      currentConversation.value = {
        id: summary.id,
        title: summary.title,
        created_at: summary.created_at,
        updated_at: summary.updated_at,
        messages: []
      }
      return
    }

    try {
      const detail = await api.getConversation(id)
      // Resolve relative attachment URLs to absolute backend URLs.
      for (const msg of detail.messages) {
        if (msg.attachments) {
          for (const att of msg.attachments) {
            att.url = resolveBackendUrl(att.url)
          }
        }
      }
      currentConversation.value = detail
    } catch (err) {
      // Fallback: if the backend returns 404 (conversation not persisted yet),
      // build a local ConversationDetail so the UI doesn't break.
      if (summary) {
        currentConversation.value = {
          id: summary.id,
          title: summary.title,
          created_at: summary.created_at,
          updated_at: summary.updated_at,
          messages: []
        }
      } else {
        // No local record either — propagate the error.
        throw err
      }
    }
  }

  /**
   * Start a fresh conversation and persist it to the backend immediately.
   * Falls back to local-only if the backend is unreachable.
   */
  async function createConversation(): Promise<void> {
    const now = new Date().toISOString()
    let newId = crypto.randomUUID()

    // Optimistically set local state so the UI updates instantly.
    const localSummary: ConversationSummary = {
      id: newId,
      title: null,
      created_at: now,
      updated_at: now,
      message_count: 0
    }

    currentConversation.value = {
      id: newId,
      title: null,
      created_at: now,
      updated_at: now,
      messages: []
    }
    conversations.value.unshift(localSummary)

    // Persist on backend — on conflict (duplicate UUID) retry with a new ID.
    try {
      const persisted = await api.createConversation(newId)
      // Sync any server-provided timestamps back into local state.
      localSummary.created_at = persisted.created_at
      localSummary.updated_at = persisted.updated_at
      if (currentConversation.value?.id === newId) {
        currentConversation.value.created_at = persisted.created_at
        currentConversation.value.updated_at = persisted.updated_at
      }
    } catch (err) {
      // 409 Conflict — duplicate UUID, regenerate and retry once.
      const isConflict = err instanceof Error && err.message.includes('409')
      if (isConflict) {
        const retryId = crypto.randomUUID()
        try {
          const persisted = await api.createConversation(retryId)
          // Update local references to the new ID.
          localSummary.id = retryId
          localSummary.created_at = persisted.created_at
          localSummary.updated_at = persisted.updated_at
          if (currentConversation.value?.id === newId) {
            currentConversation.value.id = retryId
            currentConversation.value.created_at = persisted.created_at
            currentConversation.value.updated_at = persisted.updated_at
          }
          newId = retryId
        } catch {
          // Both attempts failed — stay local-only.
          console.warn('[chat store] createConversation: backend unreachable, keeping local-only')
        }
      } else {
        // Backend down or other error — local-only is fine.
        console.warn('[chat store] createConversation: backend unreachable, keeping local-only')
      }
    }
  }

  /** Delete a conversation on the backend and remove it from local state. */
  async function deleteConversation(id: string): Promise<void> {
    // Cancel any active stream before deleting.
    if (isStreaming.value && currentConversation.value?.id === id) {
      cancelStream()
    }

    // Always attempt backend deletion — empty conversations are now persisted too.
    try {
      await api.deleteConversation(id)
    } catch (err) {
      // Silently ignore 404 (conversation may not exist on backend if created while offline).
      const is404 = err instanceof Error && err.message.includes('404')
      if (!is404) throw err
    }

    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentConversation.value?.id === id) {
      currentConversation.value = null
    }
  }

  /** Rename a conversation on the backend and update local state. */
  async function renameConversation(id: string, title: string): Promise<void> {
    try {
      const result = await api.renameConversation(id, title)

      // Update sidebar entry
      const entry = conversations.value.find((c) => c.id === id)
      if (entry) {
        entry.title = result.title
        entry.updated_at = result.updated_at
      }

      // Update active conversation if it matches
      if (currentConversation.value?.id === id) {
        currentConversation.value.title = result.title
        currentConversation.value.updated_at = result.updated_at
      }
    } catch {
      // Backend unreachable or 404 — update state locally.
      const summary = conversations.value.find((c) => c.id === id)
      if (summary) {
        summary.title = title
      }
      if (currentConversation.value?.id === id) {
        currentConversation.value.title = title
      }
    }
  }

  // -----------------------------------------------------------------------
  // Message / streaming actions
  // -----------------------------------------------------------------------

  /** Append a user message to the active conversation and start streaming. */
  function addUserMessage(content: string, attachments?: FileAttachment[]): void {
    if (!currentConversation.value) return

    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      tool_calls: null,
      tool_call_id: null,
      created_at: new Date().toISOString(),
      attachments: attachments?.length ? attachments : undefined
    }

    currentConversation.value.messages.push(msg)
    streamGeneration.value++
    isStreaming.value = true
    isWaitingForResponse.value = true
    isCancelling.value = false
    streamingConversationId.value = currentConversation.value.id
    currentStreamContent.value = ''
    currentThinkingContent.value = ''

    // Bump the sidebar message count so it reflects the new user message.
    const sidebar = conversations.value.find((c) => c.id === currentConversation.value!.id)
    if (sidebar) sidebar.message_count += 1
  }

  /** Append a streamed token to the in-progress assistant response. */
  function appendToStream(token: string): void {
    if (!isStreaming.value) return
    isWaitingForResponse.value = false
    currentStreamContent.value += token
  }

  /** Append a thinking token to the in-progress thinking content. */
  function appendToThinking(token: string): void {
    if (!isStreaming.value) return
    isWaitingForResponse.value = false
    currentThinkingContent.value += token
  }

  /**
   * Finalise the streamed response: create the assistant message,
   * reset streaming state, and refresh the sidebar.
   *
   * If the user navigated away from the streaming conversation, the
   * assistant message is already persisted server-side. We just reset
   * streaming state and refresh the sidebar; `loadConversation()` will
   * fetch the complete message list when the user navigates back.
   */
  function finalizeStream(conversationId: string, messageId: string): void {
    // Prevent double-finalization.
    if (!isStreaming.value) return

    // User navigated away — message is saved server-side.
    // Reset streaming state and refresh sidebar only.
    if (!currentConversation.value || currentConversation.value.id !== conversationId) {
      currentStreamContent.value = ''
      currentThinkingContent.value = ''
      isStreaming.value = false
      isWaitingForResponse.value = false
      isCancelling.value = false
      streamingConversationId.value = null
      loadConversations().catch(console.error)
      return
    }

    const assistantMsg: ChatMessage = {
      id: messageId,
      role: 'assistant',
      content: currentStreamContent.value,
      tool_calls: null,
      tool_call_id: null,
      created_at: new Date().toISOString(),
      thinking_content: currentThinkingContent.value || null
    }

    currentConversation.value.messages.push(assistantMsg)
    currentStreamContent.value = ''
    currentThinkingContent.value = ''
    isStreaming.value = false
    isWaitingForResponse.value = false
    isCancelling.value = false
    streamingConversationId.value = null

    // Refresh sidebar list asynchronously (fire-and-forget)
    loadConversations().catch(console.error)
  }

  /** Export a conversation as JSON from the backend. */
  async function exportConversation(id: string): Promise<ConversationExport> {
    return api.exportConversation(id)
  }

  /** Import a conversation from JSON and add it to the sidebar. */
  async function importConversation(data: ConversationExport): Promise<void> {
    const summary = await api.importConversation(data)
    conversations.value.unshift(summary)
  }

  /** Clear streaming state (e.g. on error or cancel). Preserves partial content as a message. */
  function cancelStream(): void {
    // If there's accumulated content, save as partial assistant message
    if (currentStreamContent.value && currentConversation.value) {
      const partialMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: currentStreamContent.value,
        tool_calls: null,
        tool_call_id: null,
        created_at: new Date().toISOString(),
        thinking_content: currentThinkingContent.value || null,
      }
      currentConversation.value.messages.push(partialMsg)
    }

    streamGeneration.value++
    currentStreamContent.value = ''
    currentThinkingContent.value = ''
    isStreaming.value = false
    isWaitingForResponse.value = false
    isCancelling.value = false
    streamingConversationId.value = null
  }

  // -----------------------------------------------------------------------
  // Public surface
  // -----------------------------------------------------------------------

  return {
    // state
    conversations,
    currentConversation,
    isStreaming,
    streamingConversationId,
    currentStreamContent,
    currentThinkingContent,
    streamGeneration,
    isWaitingForResponse,
    isCancelling,
    pendingAttachments,

    // computed
    messages,

    // REST actions
    loadConversations,
    loadConversation,
    createConversation,
    deleteConversation,
    renameConversation,
    exportConversation,
    importConversation,

    // message / streaming actions
    addUserMessage,
    appendToStream,
    appendToThinking,
    finalizeStream,
    cancelStream
  }
})
