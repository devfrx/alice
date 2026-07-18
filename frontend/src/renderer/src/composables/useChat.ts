/**
 * Composable that wires the WebSocket connection to the Pinia chat store.
 *
 * Usage (typically in a top-level layout or a chat view):
 *
 * ```vue
 * <script setup lang="ts">
 * const { sendMessage, isConnected, connectionStatus } = useChat()
 * </script>
 * ```
 *
 * The composable:
 * - Connects on setup AND disconnects when the calling scope is disposed.
 * - Dispatches every chat-WS frame through an exhaustive typed handler map
 *   (`ChatHandlerMap` over `ChatServerMessage['type']`) into the chat and
 *   agent-run stores, so the UI stays reactive and new backend frames fail
 *   compilation until handled.
 * - Exposes a `sendMessage` helper that optimistically adds the user
 *   message to the store then sends it over the socket.
 */

import type { InjectionKey } from 'vue'
import { computed, onScopeDispose, ref, type ComputedRef, type Ref } from 'vue'

import { chatApi } from '../services/api'
import { wsManager } from '../services/ws'
import { useAgentRunStore } from '../stores/agentRun'
import { useChatStore } from '../stores/chat'
import { useSettingsStore } from '../stores/settings'
import type {
  AskUserAnswer,
  FileAttachment,
  WsCancelPayload,
  WsInteractionResponsePayload,
  RememberChoice,
  WsSendPayload
} from '../types/chat'
import type { ChatServerMessage } from '../types/generated'

/**
 * Exhaustive map of chat-WS frame types to handlers. Adding a frame to the
 * backend ws_schema and regenerating the contracts makes this object FAIL TO
 * COMPILE until the new frame is handled (or explicitly no-op'd) — same
 * guarantee the events channel has had since 1b.
 */
type ChatHandlerMap = {
  [K in ChatServerMessage['type']]: (msg: Extract<ChatServerMessage, { type: K }>) => void
}

/** Connection status reported by the composable. */
export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

export interface UseChatReturn {
  /** Send a user message with optional attachments and input-modality source. */
  sendMessage: (
    content: string,
    conversationId?: string,
    attachments?: File[],
    options?: { source?: 'text' | 'voice' }
  ) => Promise<void>
  /** Edit a previously sent user message and regenerate the response. */
  editMessage: (messageId: string, newContent: string, attachments?: File[]) => Promise<void>
  /** Stop the in-progress generation. */
  stopGeneration: () => void
  /** Respond to a tool confirmation request (keyed by `interactionId`). */
  respondToConfirmation: (
    interactionId: string,
    approved: boolean,
    remember?: RememberChoice
  ) => void
  /** Answer an inline `ask_user` prompt with the user's structured answers. */
  answerAskUser: (interactionId: string, answers: AskUserAnswer[]) => void
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
  const agentRunStore = useAgentRunStore()

  const isConnected = ref(false)
  const connectionStatus = ref<ConnectionStatus>('disconnected')

  /** Tracks the generation counter at the time the last message was sent. */
  let activeGeneration = 0

  // -----------------------------------------------------------------------
  // Socket-level lifecycle handlers (named so they can be removed in cleanup)
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

  const onSocketError = (payload?: unknown): void => {
    // Defensive: only genuine socket-level errors (native Events) may flip
    // the connection status. Server-side `error` FRAMES are handled by the
    // typed map and must never be mistaken for a broken socket.
    if (payload instanceof Event) {
      connectionStatus.value = 'error'
    }
  }

  const onReconnectFailed = (): void => {
    connectionStatus.value = 'error'
  }

  // -----------------------------------------------------------------------
  // Chat frame handlers (exhaustive over ChatServerMessage['type'])
  // -----------------------------------------------------------------------

  const handlers: ChatHandlerMap = {
    // -- Turn lifecycle ----------------------------------------------------
    // Run-scoped frames (keyed by turn_id) fold into the agentRun store and
    // are NOT gated on the stale-generation guard, so late frames after
    // navigation still land on the correct run. Streaming text/context frames
    // touch the chat store and ARE gated (by generation and/or conversation).

    'turn.started': (msg) => agentRunStore.applyTurnStarted(msg),

    'turn.delta': (msg) => {
      if (store.streamGeneration !== activeGeneration) return // stale event
      if (msg.kind === 'text') store.appendToStream(msg.text)
      else store.appendToThinking(msg.text)
    },

    'turn.llm_step': (msg) => {
      agentRunStore.applyLlmStep(msg)
      if (store.streamGeneration !== activeGeneration) return
      if (msg.step > 1) {
        // New LLM step: reset the text buffer (the previous step is already
        // persisted server-side); thinking accumulates across steps, with a
        // horizontal rule separating each (spec §4).
        store.currentStreamContent = ''
        if (store.currentThinkingContent) {
          store.currentThinkingContent += '\n\n---\n\n'
        }
      }
    },

    'tool.call': (msg) => agentRunStore.applyToolCall(msg),
    'tool.started': (msg) => agentRunStore.applyToolStarted(msg),
    'tool.progress': (msg) => agentRunStore.applyToolProgress(msg),
    'tool.result': (msg) => agentRunStore.applyToolResult(msg),

    'interaction.requested': (msg) => {
      agentRunStore.applyInteractionRequested(msg)
      if (msg.kind === 'tool_confirmation') {
        // Auto-approve safe tools or ALL tools when confirmations are disabled
        // (parity with the legacy behaviour). The dialog gates its own render
        // with the same predicate so the auto-approved entry never flashes.
        if (msg.risk_level === 'safe' || !settingsStore.toolConfirmations) {
          respondToConfirmation(msg.interaction_id, true)
        }
      }
      // kind 'client_tool_call': no renderer executor is wired (dormant).
    },
    'interaction.resolved': (msg) => agentRunStore.applyInteractionResolved(msg),

    'context.usage': (msg) => {
      // Gated ONLY on the conversation (not the generation): the post-turn
      // usage frame arrives after finalizeStream has advanced the generation.
      if (store.streamingConversationId !== store.currentConversation?.id) return
      store.updateContextInfo({
        used: msg.used,
        available: msg.available,
        contextWindow: msg.context_window,
        percentage: msg.percentage,
        wasCompressed: msg.was_compressed ?? false,
        messagesSummarized: msg.messages_summarized ?? 0,
        isEstimated: msg.is_estimated ?? true,
        breakdown: msg.breakdown ?? undefined
      })
    },

    'context.compaction': (msg) => {
      if (store.streamingConversationId !== store.currentConversation?.id) return
      if (msg.phase === 'started') store.setCompressingContext(true)
      else if (msg.phase === 'done') store.setCompressionDone(msg.messages_summarized ?? 0)
      else store.setCompressingContext(false)
    },

    'turn.usage': (msg) => agentRunStore.applyTurnUsage(msg),

    'turn.warning': (msg) => console.warn('[useChat] Turn warning:', msg.code, msg.message),
    'turn.error': (msg) => console.error('[useChat] Turn error:', msg.code, msg.message),

    'turn.finished': (msg) => {
      agentRunStore.applyTurnFinished(msg)
      if (store.streamGeneration !== activeGeneration) return
      store.finalizeStream(
        msg.conversation_id,
        msg.message_id,
        msg.version_group_id,
        msg.version_index
      )
      store.addTurnCost(msg.cost ?? null)
    }
  }

  const dispatchFrame = (frame: ChatServerMessage): void => {
    // Own-property lookup: a frame type like 'constructor' must hit the
    // safety net below, not the Object prototype chain.
    const handler = Object.prototype.hasOwnProperty.call(handlers, frame.type)
      ? (handlers[frame.type] as (msg: ChatServerMessage) => void)
      : undefined
    if (handler) {
      handler(frame)
    } else {
      // Runtime safety net for frames newer than the bundled contract.
      console.warn('[useChat] Unhandled chat frame type:', (frame as { type?: string }).type)
    }
  }

  // -----------------------------------------------------------------------
  // Register handlers & connect
  // -----------------------------------------------------------------------

  wsManager.onFrame(dispatchFrame)
  wsManager.on('connected', onConnected)
  wsManager.on('disconnected', onDisconnected)
  wsManager.on('error', onSocketError)
  wsManager.on('reconnect_failed', onReconnectFailed)

  // WebSocket connection is deferred — App.vue calls wsManager.connect()
  // after the backend health check passes.
  connectionStatus.value = 'connecting'

  // Sync initial state (connect may have already opened)
  if (wsManager.isConnected) {
    isConnected.value = true
    connectionStatus.value = 'connected'
  }

  // -----------------------------------------------------------------------
  // Cleanup on scope dispose
  // -----------------------------------------------------------------------

  onScopeDispose(() => {
    wsManager.offFrame(dispatchFrame)
    wsManager.off('connected', onConnected)
    wsManager.off('disconnected', onDisconnected)
    wsManager.off('error', onSocketError)
    wsManager.off('reconnect_failed', onReconnectFailed)
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
    attachments?: File[],
    options?: { source?: 'text' | 'voice' }
  ): Promise<void> {
    const trimmed = content.trim()
    if (!trimmed && (!attachments || attachments.length === 0)) return

    // Cancel any in-progress stream before sending a new message.
    if (store.isStreaming) {
      const cancel: WsCancelPayload = { type: 'cancel' }
      wsManager.send(cancel)
      store.cancelStream()
    }

    // Reopen an existing conversation before creating a new one. This prevents
    // reloads from producing a trail of empty chats.
    if (!conversationId && !store.currentConversation) {
      await store.restoreConversation()
    }

    // Auto-create only when the user actually sends and no existing target exists.
    if (!conversationId && !store.currentConversation) {
      await store.createConversation()
    }

    const convId = conversationId ?? store.currentConversation?.id

    // Upload attachments first (if any)
    let uploaded: FileAttachment[] | undefined
    if (attachments?.length && convId) {
      try {
        uploaded = await Promise.all(attachments.map((file) => chatApi.uploadFile(file, convId)))
      } catch (err) {
        console.error('[useChat] Attachment upload failed:', err)
      }
    }

    // Optimistic UI update
    store.addUserMessage(trimmed, uploaded)

    // Reset the live agent thread so it shows a fresh "starting" state instead
    // of the previous (finished) run during the send→turn.started gap.
    agentRunStore.beginPendingTurn()

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
      attachments: uploaded?.map((a) => a.file_id),
      ...(options?.source ? { source: options.source } : {})
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
    const original = store.currentConversation.messages.find((m) => m.id === messageId)
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
        uploaded = await Promise.all(attachments.map((file) => chatApi.uploadFile(file, convId)))
      } catch (err) {
        console.error('[useChat] Attachment upload failed:', err)
      }
    }

    // Optimistic UI update.
    store.addUserMessage(trimmed, uploaded, {
      versionGroupId,
      versionIndex: newVersionIndex
    })

    // Reset the live agent thread so it shows a fresh "starting" state instead
    // of the previous (finished) run during the send→turn.started gap.
    agentRunStore.beginPendingTurn()

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
      edit_message_id: messageId
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
   *
   * Correlated by `interactionId`. `remember` carries an optional "don't ask
   * again" persistence choice, only meaningful on an approval — the server
   * ignores it on rejection. It is sent only when not `'none'` to keep the
   * wire frame minimal. The pending state resolves when the server's
   * `interaction.resolved` frame folds into the agentRun store.
   */
  function respondToConfirmation(
    interactionId: string,
    approved: boolean,
    remember: RememberChoice = 'none'
  ): void {
    const payload: WsInteractionResponsePayload = {
      type: 'interaction.response',
      interaction_id: interactionId,
      kind: 'tool_confirmation',
      approved
    }
    if (remember !== 'none') payload.remember = remember
    wsManager.send(payload)
  }

  /**
   * Answer an inline `ask_user` prompt with the user's structured answers.
   *
   * One `interactionId` per interaction; each answer is correlated back to its
   * question by `question_id`.
   */
  function answerAskUser(interactionId: string, answers: AskUserAnswer[]): void {
    const payload: WsInteractionResponsePayload = {
      type: 'interaction.response',
      interaction_id: interactionId,
      kind: 'ask_user',
      answers
    }
    wsManager.send(payload)
  }

  return {
    sendMessage,
    editMessage,
    stopGeneration,
    respondToConfirmation,
    answerAskUser,
    isConnected,
    connectionStatus,
    isCancelling: computed(() => store.isCancelling)
  }
}
