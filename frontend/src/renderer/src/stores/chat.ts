/**
 * Pinia store managing chat state for the AL\CE assistant.
 *
 * Responsibilities:
 * - Maintain the sidebar conversation list (`conversations`)
 * - Track the active conversation (`currentConversation`)
 * - Accumulate streaming tokens from the WebSocket
 * - Dispatch REST calls via `services/api.ts`
 */

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import { api, resolveBackendUrl } from '../services/api'
import { useAgentRun } from '../composables/useAgentRun'
import type { AgentEvent, AgentRun } from '../types/agent'
import type {
  ChatMessage,
  ConfirmationRequest,
  ContextInfo,
  ConversationDetail,
  ConversationExport,
  ConversationSummary,
  FileAttachment,
  ToolExecution,
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

  /**
   * Epoch (ms) at which the last stream ended.  Used by background
   * pollers (LM Studio status, weather, calendar, …) to honour a short
   * grace period after a chat finishes so the backend can drain its
   * tool / embedding work without competing with renderer traffic.
   */
  const lastStreamEndedAt = ref(0)

  /** Grace window (ms) during which background pollers stay quiet. */
  const POST_STREAM_QUIET_MS = 10_000

  /**
   * Returns true when background polling should be skipped — either a
   * stream is currently active or it ended less than
   * ``POST_STREAM_QUIET_MS`` milliseconds ago.
   */
  function isPollingPaused(): boolean {
    if (isStreaming.value) return true
    if (lastStreamEndedAt.value === 0) return false
    return Date.now() - lastStreamEndedAt.value < POST_STREAM_QUIET_MS
  }

  // Stamp lastStreamEndedAt whenever streaming transitions true → false.
  // Centralised here so every code path that ends a stream (normal
  // finalize, cancel, error, conversation switch) is covered without
  // having to remember the bookkeeping at each call site.
  watch(isStreaming, (streaming, wasStreaming) => {
    if (wasStreaming && !streaming) {
      lastStreamEndedAt.value = Date.now()
    }
  })

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

  /** Tool executions running during the current stream. */
  const activeToolExecutions = ref<ToolExecution[]>([])

  /** Tool confirmations awaiting user approval. */
  const pendingConfirmations = ref<Record<string, ConfirmationRequest>>({})

  /** Latest context window usage information from the server. */
  const contextInfo = ref<ContextInfo | null>(null)

  /** Whether context compression is currently in progress. */
  const isCompressingContext = ref(false)

  // -----------------------------------------------------------------------
  // Agent loop tracker (Agent Loop v2)
  // -----------------------------------------------------------------------

  const agentTracker = useAgentRun()

  /** Reactive map of in-flight / completed agent runs, keyed by `run_id`. */
  const agentRuns = agentTracker.agentRuns

  /** Apply an `agent.*` WebSocket event to the local tracker. */
  function applyAgentEvent(event: AgentEvent): void {
    agentTracker.applyAgentEvent(event)
  }

  /**
   * Associate the most recently started agent run with an assistant
   * message id.  Called from `finalizeStream` so the UI can look the
   * run up by `final_assistant_message_id`.
   */
  function linkAgentRunToMessage(messageId: string): void {
    agentTracker.linkRunToMessage(messageId)
  }

  /** Look up the agent run that produced a given assistant message. */
  function getAgentRunByMessageId(messageId: string | null | undefined): AgentRun | null {
    return agentTracker.getRunByMessageId(messageId)
  }

  // -----------------------------------------------------------------------
  // Computed
  // -----------------------------------------------------------------------

  /**
   * Active-version filtered messages of the current conversation.
   * Messages without a version_group_id pass through unchanged.
   * Versioned messages are shown only if their version_index matches
   * the active index for their group.
   */
  const messages = computed<ChatMessage[]>(() => {
    const conv = currentConversation.value
    if (!conv) return []
    const av = conv.active_versions ?? {}
    return conv.messages.filter((m) => {
      if (!m.version_group_id) return true
      const activeIdx = av[m.version_group_id] ?? 0
      return (m.version_index ?? 0) === activeIdx
    })
  })

  /**
   * Get the total number of versions for a version group.
   * Counts distinct version indices among user messages only.
   */
  function getVersionCount(versionGroupId: string): number {
    if (!currentConversation.value) return 1
    const indices = new Set<number>()
    for (const m of currentConversation.value.messages) {
      if (m.version_group_id === versionGroupId && m.role === 'user') {
        indices.add(m.version_index ?? 0)
      }
    }
    return Math.max(indices.size, 1)
  }

  /**
   * Get the active version index for a version group.
   */
  function getActiveVersionIndex(versionGroupId: string): number {
    return currentConversation.value?.active_versions?.[versionGroupId] ?? 0
  }

  /** True only when the currently viewed conversation is the one being streamed. */
  const isStreamingCurrentConversation = computed<boolean>(
    () => isStreaming.value && streamingConversationId.value === currentConversation.value?.id
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
      (c) => !remoteIds.has(c.id) && (
        c.message_count === 0 || c.id === streamingConversationId.value
      )
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
    // Reset context info only when switching to a DIFFERENT conversation.
    // When reloading the same conversation (e.g. after finalizeStream),
    // keep the existing contextInfo to avoid flicker and data loss.
    const isSameConversation = currentConversation.value?.id === id
    if (!isSameConversation && (!isStreaming.value || streamingConversationId.value !== id)) {
      contextInfo.value = null
      isCompressingContext.value = false
    }

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

      // Populate context info from the API response if available.
      // Skip if we already hold real (non-estimated) data from streaming —
      // the GET endpoint only returns estimates.
      const hasRealData = contextInfo.value && !contextInfo.value.isEstimated
      const isStreamingThisConversation =
        isStreaming.value && streamingConversationId.value === id
      if (detail.context_info && !isStreamingThisConversation && !hasRealData) {
        contextInfo.value = {
          used: detail.context_info.used,
          available: detail.context_info.available,
          contextWindow: detail.context_info.context_window,
          percentage: detail.context_info.percentage,
          wasCompressed: detail.context_info.was_compressed,
          messagesSummarized: detail.context_info.messages_summarized ?? 0,
          isEstimated: detail.context_info.is_estimated ?? true,
          breakdown: detail.context_info.breakdown,
        }
      }
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

  /** Delete ALL conversations on the backend and clear local state. */
  async function deleteAllConversations(): Promise<void> {
    // Cancel any active stream.
    if (isStreaming.value) {
      cancelStream()
    }

    await api.deleteAllConversations()

    conversations.value = []
    currentConversation.value = null
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

  /** Append a user message to the active conversation and start streaming.
   *  When `editInfo` is provided, the message is tagged with version metadata.
   *  Otherwise, if the conversation has active version groups, the message
   *  automatically inherits the version context of the currently active branch.
   */
  function addUserMessage(
    content: string,
    attachments?: FileAttachment[],
    editInfo?: { versionGroupId: string; versionIndex: number },
  ): void {
    if (!currentConversation.value) return

    // Determine version metadata: explicit edit > auto-inherit > none.
    let versionGroupId: string | undefined
    let versionIndex: number | undefined

    if (editInfo) {
      versionGroupId = editInfo.versionGroupId
      versionIndex = editInfo.versionIndex
    } else {
      const av = currentConversation.value.active_versions
      if (av && Object.keys(av).length > 0) {
        // Inherit from the most recent versioned message in the active view.
        const filtered = messages.value
        for (let i = filtered.length - 1; i >= 0; i--) {
          const gid = filtered[i].version_group_id
          if (gid) {
            versionGroupId = gid
            versionIndex = av[gid] ?? 0
            break
          }
        }
      }
    }

    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      tool_calls: null,
      tool_call_id: null,
      created_at: new Date().toISOString(),
      attachments: attachments?.length ? attachments : undefined,
      version_group_id: versionGroupId,
      version_index: versionIndex,
    }

    currentConversation.value.messages.push(msg)

    // Update active_versions map when editing.
    if (editInfo) {
      if (!currentConversation.value.active_versions) {
        currentConversation.value.active_versions = {}
      }
      currentConversation.value.active_versions[editInfo.versionGroupId] =
        editInfo.versionIndex
    }

    streamGeneration.value++
    isStreaming.value = true
    isWaitingForResponse.value = true
    isCancelling.value = false
    streamingConversationId.value = currentConversation.value.id
    currentStreamContent.value = ''
    currentThinkingContent.value = ''
    contextInfo.value = null
    isCompressingContext.value = false

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
  function finalizeStream(
    conversationId: string,
    messageId: string,
    versionGroupId?: string | null,
    versionIndex?: number,
    _userMessageId?: string,
  ): void {
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
      isCompressingContext.value = false
      streamingConversationId.value = null
      activeToolExecutions.value = []
      pendingConfirmations.value = {}
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
      thinking_content: currentThinkingContent.value || null,
      version_group_id: versionGroupId ?? undefined,
      version_index: versionIndex ?? undefined,
    }

    currentConversation.value.messages.push(assistantMsg)
    // Link any pending agent run to the freshly persisted assistant message
    // so MessageBubble can look it up by `final_assistant_message_id`.
    linkAgentRunToMessage(messageId)
    currentStreamContent.value = ''
    currentThinkingContent.value = ''
    isStreaming.value = false
    isWaitingForResponse.value = false
    isCancelling.value = false
    isCompressingContext.value = false
    streamingConversationId.value = null
    activeToolExecutions.value = []
    pendingConfirmations.value = {}

    // Refresh sidebar list asynchronously (fire-and-forget)
    loadConversations().catch(console.error)

    // Always reload the conversation from server to sync message IDs,
    // version metadata, and any intermediate tool-loop messages.
    loadConversation(conversationId).catch(console.error)
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

  // -----------------------------------------------------------------------
  // Tool execution actions
  // -----------------------------------------------------------------------

  /** Register a new tool execution as running. */
  function addToolExecution(executionId: string, toolName: string): void {
    activeToolExecutions.value.push({ executionId, toolName, status: 'running' })
  }

  /** Mark a tool execution as completed. */
  function completeToolExecution(
    executionId: string,
    result: string,
    success: boolean,
    contentType?: string
  ): void {
    const exec = activeToolExecutions.value.find((e) => e.executionId === executionId)
    if (exec) {
      exec.status = success ? 'done' : 'error'
      exec.result = result
      exec.success = success
      if (contentType) exec.contentType = contentType
    }
    // Clean up any orphaned confirmation (e.g. backend timeout before user responded).
    delete pendingConfirmations.value[executionId]
  }

  /** Add a pending confirmation request. */
  function addPendingConfirmation(req: ConfirmationRequest): void {
    pendingConfirmations.value[req.executionId] = req
  }

  /** Remove a pending confirmation (after user responds). */
  function removePendingConfirmation(executionId: string): void {
    delete pendingConfirmations.value[executionId]
  }

  /** Update the context window usage info from a server event. */
  function updateContextInfo(info: ContextInfo): void {
    contextInfo.value = info
  }

  /** Set whether context compression is in progress. */
  function setCompressingContext(value: boolean): void {
    isCompressingContext.value = value
  }

  /** Handle context compression completion. */
  function setCompressionDone(messagesSummarized: number): void {
    isCompressingContext.value = false
    if (contextInfo.value) {
      contextInfo.value.wasCompressed = true
      contextInfo.value.messagesSummarized = messagesSummarized
      // Mark as estimated so loadConversation's GET response can refresh
      // with accurate post-compression token counts.
      contextInfo.value.isEstimated = true
    }
  }

  /** Clear streaming state (e.g. on error or cancel). Preserves partial content as a message. */
  function cancelStream(): void {
    // If there's accumulated content, save as partial assistant message
    if ((currentStreamContent.value || currentThinkingContent.value) && currentConversation.value) {
      // Tag the partial message with the same version context as the last user message.
      const rawMsgs = currentConversation.value.messages
      const lastUserMsg = [...rawMsgs].reverse().find((m) => m.role === 'user')
      const partialMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: currentStreamContent.value,
        tool_calls: null,
        tool_call_id: null,
        created_at: new Date().toISOString(),
        thinking_content: currentThinkingContent.value || null,
        version_group_id: lastUserMsg?.version_group_id,
        version_index: lastUserMsg?.version_index,
      }
      currentConversation.value.messages.push(partialMsg)
    }

    currentStreamContent.value = ''
    currentThinkingContent.value = ''
    isStreaming.value = false
    isWaitingForResponse.value = false
    isCancelling.value = false
    isCompressingContext.value = false
    streamingConversationId.value = null
    activeToolExecutions.value = []
    pendingConfirmations.value = {}
  }

  /**
   * Switch the active version for a message version group.
   * Updates local state immediately and persists to backend.
   *
   * No-op during streaming: switching versions while a response is being
   * generated would corrupt the context seen by the LLM.
   */
  async function switchVersion(
    versionGroupId: string,
    versionIndex: number,
  ): Promise<void> {
    if (!currentConversation.value) return
    if (isStreamingCurrentConversation.value) return

    // Optimistic: update local state first.
    const previousIndex = currentConversation.value.active_versions?.[versionGroupId] ?? 0
    if (!currentConversation.value.active_versions) {
      currentConversation.value.active_versions = {}
    }
    currentConversation.value.active_versions[versionGroupId] = versionIndex

    // Persist to backend.
    try {
      const result = await api.switchVersion(
        currentConversation.value.id,
        versionGroupId,
        versionIndex,
      )
      if (currentConversation.value) {
        currentConversation.value.active_versions = result.active_versions
        currentConversation.value.updated_at = result.updated_at
      }
    } catch (err) {
      console.error('[chat store] switchVersion failed:', err)
      if (currentConversation.value.active_versions) {
        currentConversation.value.active_versions[versionGroupId] = previousIndex
      }
    }
  }

  /**
   * Branch the current conversation from a specific message.
   *
   * Creates a new independent conversation with all messages from the
   * start through {@link fromMessageId} (following the active version
   * branch), then navigates to the new conversation.
   *
   * No-op during streaming — branching while a response is being
   * generated would produce an incomplete context in the new branch.
   *
   * @param fromMessageId - UUID of the last message to include in the branch.
   * @param title - Optional title override. Defaults to server-generated.
   * @returns UUID of the newly created conversation, or empty string on guard.
   */
  async function branchConversation(
    fromMessageId: string,
    title?: string,
  ): Promise<string> {
    if (!currentConversation.value) return ''
    if (isStreamingCurrentConversation.value) return ''

    try {
      const result = await api.branchConversation(
        currentConversation.value.id,
        fromMessageId,
        title,
      )
      // Refresh sidebar list so the new conversation appears.
      await loadConversations()
      // Navigate to the new conversation.
      await loadConversation(result.id)
      return result.id
    } catch (err) {
      console.error('[chat store] branchConversation failed:', err)
      throw err
    }
  }

  // -----------------------------------------------------------------------
  // Public surface
  // -----------------------------------------------------------------------

  return {
    // state
    conversations,
    currentConversation,
    isStreaming,
    lastStreamEndedAt,
    streamingConversationId,
    currentStreamContent,
    currentThinkingContent,
    streamGeneration,
    isWaitingForResponse,
    isCancelling,
    activeToolExecutions,
    pendingConfirmations,
    contextInfo,
    isCompressingContext,
    agentRuns,

    // computed
    messages,
    isStreamingCurrentConversation,

    // helpers
    isPollingPaused,

    // REST actions
    loadConversations,
    loadConversation,
    createConversation,
    deleteConversation,
    deleteAllConversations,
    renameConversation,
    exportConversation,
    importConversation,

    // message / streaming actions
    addUserMessage,
    appendToStream,
    appendToThinking,
    finalizeStream,
    cancelStream,

    // version actions
    switchVersion,
    branchConversation,
    getVersionCount,
    getActiveVersionIndex,

    // tool execution actions
    addToolExecution,
    completeToolExecution,
    addPendingConfirmation,
    removePendingConfirmation,
    updateContextInfo,
    setCompressingContext,
    setCompressionDone,

    // agent loop
    applyAgentEvent,
    linkAgentRunToMessage,
    getAgentRunByMessageId
  }
})
