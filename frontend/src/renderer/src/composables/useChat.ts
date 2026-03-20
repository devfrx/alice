/**
 * Composable that wires the WebSocket connection to the Pinia chat store.
 *
 * Usage (typically in a top-level layout or HybridView):
 *
 * ```vue
 * <script setup lang="ts">
 * const { sendMessage, isConnected, connectionStatus } = useChat()
 * </script>
 * ```
 *
 * The composable:
 * - Connects on setup AND disconnects when the calling scope is disposed.
 * - Listens for `token`, `done`, and `error` WS events, forwarding them
 *   into the chat store so the UI stays reactive.
 * - Exposes a `sendMessage` helper that optimistically adds the user
 *   message to the store then sends it over the socket.
 */

import type { InjectionKey } from 'vue'
import { computed, onScopeDispose, ref, type ComputedRef, type Ref } from 'vue'

import { api } from '../services/api'
import { wsManager } from '../services/ws'
import { useChatStore } from '../stores/chat'
import { useSettingsStore } from '../stores/settings'
import type {
  FileAttachment,
  WsCancelPayload,
  WsDoneMessage,
  WsErrorMessage,
  WsLlmRequeryMessage,
  WsSendPayload,
  WsThinkingMessage,
  WsTokenMessage,
  WsToolConfirmationRequiredMessage,
  WsToolConfirmationResponsePayload,
  WsToolExecutionDoneMessage,
  WsToolExecutionStartMessage,
  WsWarningMessage
} from '../types/chat'

/** Connection status reported by the composable. */
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

export interface UseChatReturn {
  /** Send a user message with optional attachments. */
  sendMessage: (content: string, conversationId?: string, attachments?: File[]) => Promise<void>
  /** Edit a previously sent user message and regenerate the response. */
  editMessage: (
    messageId: string,
    newContent: string,
    attachments?: File[]
  ) => Promise<void>
  /** Stop the in-progress generation. */
  stopGeneration: () => void
  /** Respond to a tool confirmation request. */
  respondToConfirmation: (executionId: string, approved: boolean) => void
  /** Reactive flag — `true` while the socket is open. */
  isConnected: Ref<boolean>
  /** Reactive connection status string. */
  connectionStatus: Ref<ConnectionStatus>
  /** Reactive flag — `true` while a cancel request is pending (read-only). */
  isCancelling: ComputedRef<boolean>
}

/** Injection key for the global chat API provided by App.vue. */
export const ChatApiKey: InjectionKey<UseChatReturn> = Symbol('chatApi')

/**
 * Wire up WebSocket events to the chat store.
 *
 * @returns Reactive helpers for the chat UI.
 */
export function useChat(): UseChatReturn {
  const store = useChatStore()
  const settingsStore = useSettingsStore()

  const isConnected = ref(false)
  const connectionStatus = ref<ConnectionStatus>('disconnected')

  /** Tracks the generation counter at the time the last message was sent. */
  let activeGeneration = 0

  // -----------------------------------------------------------------------
  // WS event handlers (named so they can be removed in cleanup)
  // -----------------------------------------------------------------------

  const onConnected = (): void => {
    isConnected.value = true
    connectionStatus.value = 'connected'
    // Re-sync model config with LM Studio on (re)connect.
    settingsStore.syncModel().catch(console.error)
    // Sync sidebar list (picks up local-only conversations persisted while offline).
    store.loadConversations().catch(console.error)
    // Reload the active conversation to sync any messages missed during disconnect.
    if (store.currentConversation?.id) {
      store.loadConversation(store.currentConversation.id).catch(console.error)
    }
  }

  const onDisconnected = (): void => {
    isConnected.value = false
    connectionStatus.value = 'disconnected'
    // Cancel any in-progress stream — we lost the connection.
    if (store.isStreaming) {
      store.cancelStream()
    }
  }

  const onError = (data: unknown): void => {
    // Only set connection-level error for native WS errors (Event objects),
    // not for server-side error frames (which are JSON with type:'error').
    if (data instanceof Event) {
      connectionStatus.value = 'error'
    }
  }

  const onReconnectFailed = (): void => {
    connectionStatus.value = 'error'
  }

  const onToken = (data: unknown): void => {
    if (store.streamGeneration !== activeGeneration) return // stale event
    const msg = data as WsTokenMessage
    store.appendToStream(msg.content)
  }

  const onThinking = (data: unknown): void => {
    if (store.streamGeneration !== activeGeneration) return // stale event
    const msg = data as WsThinkingMessage
    store.appendToThinking(msg.content)
  }

  const onDone = (data: unknown): void => {
    if (store.streamGeneration !== activeGeneration) return // stale event
    const msg = data as WsDoneMessage
    if (msg.finish_reason && msg.finish_reason !== 'stop') {
      console.debug('[useChat] Stream finished with reason:', msg.finish_reason)
    }
    store.finalizeStream(
      msg.conversation_id,
      msg.message_id,
      msg.version_group_id,
      msg.version_index,
      msg.user_message_id,
    )
  }

  const onToolCall = (data: unknown): void => {
    // Legacy handler kept for backward compatibility with older backends.
    console.debug('[useChat] Legacy tool_call event received:', data)
  }

  const onToolExecutionStart = (data: unknown): void => {
    if (store.streamGeneration !== activeGeneration) return
    const msg = data as WsToolExecutionStartMessage
    store.addToolExecution(msg.execution_id, msg.tool_name)
  }

  const onToolExecutionDone = (data: unknown): void => {
    if (store.streamGeneration !== activeGeneration) return
    const msg = data as WsToolExecutionDoneMessage
    store.completeToolExecution(msg.execution_id, msg.result, msg.success, msg.content_type)
  }

  const onToolConfirmationRequired = (data: unknown): void => {
    if (store.streamGeneration !== activeGeneration) return
    const msg = data as WsToolConfirmationRequiredMessage

    // Auto-approve safe tools or ALL tools when confirmations are disabled.
    if (msg.risk_level === 'safe' || !settingsStore.toolConfirmations) {
      respondToConfirmation(msg.execution_id, true)
      return
    }

    store.addPendingConfirmation({
      executionId: msg.execution_id,
      toolName: msg.tool_name,
      args: msg.args,
      riskLevel: msg.risk_level,
      description: msg.description,
      reasoning: msg.reasoning
    })
  }

  const onLlmRequery = (data: unknown): void => {
    if (store.streamGeneration !== activeGeneration) return
    const msg = data as WsLlmRequeryMessage
    console.debug('[useChat] LLM re-query iteration:', msg.iteration)
    // Reset streaming content for the new LLM iteration.
    // The previous iteration's content is already persisted server-side.
    store.currentStreamContent = ''
    // Accumulate thinking across iterations so all reasoning stays visible.
    // Previous iterations are separated by a horizontal rule.
    if (store.currentThinkingContent) {
      store.currentThinkingContent += '\n\n---\n\n'
    }
  }

  const onWarning = (data: unknown): void => {
    const msg = data as WsWarningMessage
    console.warn('[useChat] Server warning:', msg.content)
  }

  const onWsError = (data: unknown): void => {
    // Only handle server-side error frames (JSON objects with content),
    // skip native WebSocket error Events.
    if (data instanceof Event) return
    const msg = data as WsErrorMessage
    console.error('[useChat] Server error:', msg.content)
    // Don't cancel stream here — transient LLM errors during tool loop
    // re-queries would kill the entire stream.  The backend sends a
    // proper "done" event when the response is truly finished.
  }

  // -----------------------------------------------------------------------
  // Register handlers & connect
  // -----------------------------------------------------------------------

  wsManager.on('connected', onConnected)
  wsManager.on('disconnected', onDisconnected)
  wsManager.on('error', onError)
  wsManager.on('reconnect_failed', onReconnectFailed)
  wsManager.on('token', onToken)
  wsManager.on('thinking', onThinking)
  wsManager.on('done', onDone)
  wsManager.on('tool_call', onToolCall)
  wsManager.on('tool_execution_start', onToolExecutionStart)
  wsManager.on('tool_execution_done', onToolExecutionDone)
  wsManager.on('tool_confirmation_required', onToolConfirmationRequired)
  wsManager.on('llm_requery', onLlmRequery)
  wsManager.on('warning', onWarning)
  wsManager.on('error', onWsError) // also catches server-side error frames

  connectionStatus.value = 'connecting'
  wsManager.connect()

  // Sync initial state (connect may have already opened)
  if (wsManager.isConnected) {
    isConnected.value = true
    connectionStatus.value = 'connected'
  }

  // -----------------------------------------------------------------------
  // Cleanup on scope dispose
  // -----------------------------------------------------------------------

  onScopeDispose(() => {
    wsManager.off('connected', onConnected)
    wsManager.off('disconnected', onDisconnected)
    wsManager.off('error', onError)
    wsManager.off('reconnect_failed', onReconnectFailed)
    wsManager.off('token', onToken)
    wsManager.off('thinking', onThinking)
    wsManager.off('done', onDone)
    wsManager.off('tool_call', onToolCall)
    wsManager.off('tool_execution_start', onToolExecutionStart)
    wsManager.off('tool_execution_done', onToolExecutionDone)
    wsManager.off('tool_confirmation_required', onToolConfirmationRequired)
    wsManager.off('llm_requery', onLlmRequery)
    wsManager.off('warning', onWarning)
    wsManager.off('error', onWsError)
    wsManager.disconnect()
  })

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  /**
   * Send a user message via WebSocket, optionally with file attachments.
   *
   * Files are uploaded first via the REST API, then their IDs are
   * included in the WebSocket payload.
   *
   * If a stream is already in progress, it is cancelled first.
   */
  async function sendMessage(
    content: string,
    conversationId?: string,
    attachments?: File[]
  ): Promise<void> {
    const trimmed = content.trim()
    if (!trimmed && (!attachments || attachments.length === 0)) return

    // Cancel any in-progress stream before sending a new message.
    if (store.isStreaming) {
      const cancel: WsCancelPayload = { type: 'cancel' }
      wsManager.send(cancel)
      store.cancelStream()
    }

    // Auto-create a conversation if none exists yet.
    if (!conversationId && !store.currentConversation) {
      await store.createConversation()
    }

    const convId = conversationId ?? store.currentConversation?.id

    // Upload attachments first (if any)
    let uploaded: FileAttachment[] | undefined
    if (attachments?.length && convId) {
      try {
        uploaded = await Promise.all(
          attachments.map((file) => api.uploadFile(file, convId))
        )
      } catch (err) {
        console.error('[useChat] Attachment upload failed:', err)
      }
    }

    // Optimistic UI update
    store.addUserMessage(trimmed, uploaded)

    // Capture the generation counter so stale events from previous streams are ignored.
    activeGeneration = store.streamGeneration

    // Guard: if the WebSocket is not open, cancel immediately so the
    // streaming indicator does not stay stuck.
    if (!wsManager.isConnected) {
      console.error('[useChat] Cannot send — WebSocket is not connected')
      store.cancelStream()
      return
    }

    const payload: WsSendPayload = {
      content: trimmed,
      conversation_id: convId,
      attachments: uploaded?.map((a) => a.file_id)
    }

    wsManager.send(payload)
  }

  /**
   * Edit a previously sent user message and regenerate the LLM response.
   *
   * 1. Cancels any in-progress stream.
   * 2. Uploads new attachments (if any).
   * 3. Determines the version_group_id (existing or new).
   * 4. Computes the next version_index.
   * 5. Optimistically adds the edited user message with version metadata.
   * 6. Sends the edit payload over WebSocket.
   */
  async function editMessage(
    messageId: string,
    newContent: string,
    attachments?: File[]
  ): Promise<void> {
    const trimmed = newContent.trim()
    if (!trimmed && (!attachments || attachments.length === 0)) return

    if (!store.currentConversation) return
    const convId = store.currentConversation.id

    // Cancel any in-progress stream.
    if (store.isStreaming) {
      const cancel: WsCancelPayload = { type: 'cancel' }
      wsManager.send(cancel)
      store.cancelStream()
    }

    // Find the original message to determine version group.
    const original = store.currentConversation.messages.find(
      (m) => m.id === messageId
    )
    if (!original || original.role !== 'user') {
      console.error('[useChat] editMessage: target message not found or not a user message')
      return
    }

    // Determine version_group_id and next version_index.
    const versionGroupId = original.version_group_id ?? crypto.randomUUID()
    let maxIndex = 0
    for (const m of store.currentConversation.messages) {
      if (m.version_group_id === versionGroupId && m.role === 'user') {
        maxIndex = Math.max(maxIndex, m.version_index ?? 0)
      }
    }
    // If the original didn't have a version_group_id, tag it now.
    if (!original.version_group_id) {
      original.version_group_id = versionGroupId
      original.version_index = 0
      // Tag subsequent messages from the original onward with version 0.
      const originalIdx = store.currentConversation.messages.indexOf(original)
      for (let i = originalIdx + 1; i < store.currentConversation.messages.length; i++) {
        const m = store.currentConversation.messages[i]
        if (!m.version_group_id) {
          m.version_group_id = versionGroupId
          m.version_index = 0
        }
      }
    }
    const newVersionIndex = maxIndex + 1

    // Upload attachments.
    let uploaded: FileAttachment[] | undefined
    if (attachments?.length) {
      try {
        uploaded = await Promise.all(
          attachments.map((file) => api.uploadFile(file, convId))
        )
      } catch (err) {
        console.error('[useChat] Attachment upload failed:', err)
      }
    }

    // Optimistic UI update.
    store.addUserMessage(trimmed, uploaded, {
      versionGroupId,
      versionIndex: newVersionIndex,
    })

    activeGeneration = store.streamGeneration

    if (!wsManager.isConnected) {
      console.error('[useChat] Cannot send — WebSocket is not connected')
      store.cancelStream()
      return
    }

    const payload: WsSendPayload = {
      content: trimmed,
      conversation_id: convId,
      attachments: uploaded?.map((a) => a.file_id),
      edit_message_id: messageId,
    }

    wsManager.send(payload)
  }

  /**
   * Request the server to stop the current generation.
   * Does not immediately clear streaming state — waits for the server
   * to send a "done" event with `finish_reason: "cancelled"`.
   */
  function stopGeneration(): void {
    if (!store.isStreaming || store.isCancelling) return
    store.isCancelling = true
    const cancel: WsCancelPayload = { type: 'cancel' }
    wsManager.send(cancel)
    // Safety timeout: if server doesn't confirm cancel within 5s, force it.
    // Scoped to current generation to avoid cancelling a newer stream.
    const gen = store.streamGeneration
    setTimeout(() => {
      if (store.isCancelling && store.streamGeneration === gen) {
        store.cancelStream()
      }
    }, 5000)
  }

  /**
   * Respond to a tool confirmation request (approve or reject).
   */
  function respondToConfirmation(executionId: string, approved: boolean): void {
    const payload: WsToolConfirmationResponsePayload = {
      type: 'tool_confirmation_response',
      execution_id: executionId,
      approved
    }
    wsManager.send(payload)
    store.removePendingConfirmation(executionId)
  }

  return {
    sendMessage,
    editMessage,
    stopGeneration,
    respondToConfirmation,
    isConnected,
    connectionStatus,
    isCancelling: computed(() => store.isCancelling)
  }
}
