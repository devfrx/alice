/**
 * Composable that wires the WebSocket connection to the Pinia chat store.
 *
 * Usage (typically in a top-level layout or ChatView):
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

import { computed, onScopeDispose, ref, type Ref } from 'vue'

import { api } from '../services/api'
import { wsManager } from '../services/ws'
import { useChatStore } from '../stores/chat'
import type {
  FileAttachment,
  WsCancelPayload,
  WsDoneMessage,
  WsErrorMessage,
  WsSendPayload,
  WsThinkingMessage,
  WsTokenMessage,
  WsToolCallMessage
} from '../types/chat'

/** Connection status reported by the composable. */
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

export interface UseChatReturn {
  /** Send a user message with optional attachments. */
  sendMessage: (content: string, conversationId?: string, attachments?: File[]) => Promise<void>
  /** Stop the in-progress generation. */
  stopGeneration: () => void
  /** Reactive flag — `true` while the socket is open. */
  isConnected: Ref<boolean>
  /** Reactive connection status string. */
  connectionStatus: Ref<ConnectionStatus>
  /** Reactive flag — `true` while a cancel request is pending. */
  isCancelling: Ref<boolean>
}

/**
 * Wire up WebSocket events to the chat store.
 *
 * @returns Reactive helpers for the chat UI.
 */
export function useChat(): UseChatReturn {
  const store = useChatStore()

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
    store.finalizeStream(msg.conversation_id, msg.message_id)
  }

  const onToolCall = (data: unknown): void => {
    const msg = data as WsToolCallMessage
    console.debug('[useChat] Tool call received:', msg)
    // Tool execution is handled server-side in a future phase.
    // For now, just log it so the event is not silently dropped.
  }

  const onWsError = (data: unknown): void => {
    // Only handle server-side error frames (JSON objects with content),
    // skip native WebSocket error Events.
    if (data instanceof Event) return
    const msg = data as WsErrorMessage
    console.error('[useChat] Server error:', msg.content)
    store.cancelStream()
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

  return {
    sendMessage,
    stopGeneration,
    isConnected,
    connectionStatus,
    isCancelling: computed(() => store.isCancelling)
  }
}
