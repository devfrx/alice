/**
 * terminalSessions.ts — Pinia setup-store for interactive PTY terminals
 * (Fase 7 E1/E2).
 *
 * Mirrors {@link useScopeStore}: per-conversation session metadata kept in sync
 * by an on-demand REST snapshot ({@link ensureForConversation}), user mutations
 * (create / kill / rename / assign), and live events folded from the events
 * WebSocket (`terminal.session_opened` / `output` / `closed` / `renamed` /
 * `assigned`).
 *
 * Output plumbing is deliberately **non-reactive** for throughput: each
 * session's scrollback is kept in a plain `Map` (capped) so a reattaching xterm
 * can replay it once, and live chunks are pushed to per-session subscriber
 * callbacks (the mounted xterm's `write`). Only the session *list* is reactive.
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

import { terminalApi } from '../services/api'
import { sendEventsMessage } from '../composables/useEventsWebSocket'
import type {
  TerminalCreateRequest,
  TerminalSession,
  WsTerminalAssignedMessage,
  WsTerminalClosedMessage,
  WsTerminalOutputMessage,
  WsTerminalRenamedMessage,
  WsTerminalSessionOpenedMessage,
} from '../types/terminal'

/** Max scrollback bytes retained per session for reattach replay. */
const MAX_BUFFER = 256_000

export const useTerminalSessionsStore = defineStore('terminalSessions', () => {
  // -----------------------------------------------------------------------
  // State (reactive: session metadata only)
  // -----------------------------------------------------------------------

  /** Sessions per conversation id (oldest first, as the server returns them). */
  const byConversation = ref<Record<string, TerminalSession[]>>({})

  /** Whether the terminal capability is enabled (from the last list call). */
  const enabled = ref(true)

  /** Conversation ids fetched at least once (dedupe guard). */
  const fetched = ref<Set<string>>(new Set())

  const loading = ref(false)

  // Non-reactive output plumbing (perf): scrollback + live subscribers.
  const buffers = new Map<string, string>()
  const subscribers = new Map<string, Set<(data: string) => void>>()

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  function sessionsFor(conversationId: string | null): TerminalSession[] {
    if (!conversationId) return []
    return byConversation.value[conversationId] ?? []
  }

  function assignedFor(conversationId: string | null): TerminalSession | null {
    return sessionsFor(conversationId).find((s) => s.agent_assigned) ?? null
  }

  function activeCountFor(conversationId: string | null): number {
    return sessionsFor(conversationId).length
  }

  /** Current scrollback buffer for a session (for reattach replay). */
  function bufferFor(sessionId: string): string {
    return buffers.get(sessionId) ?? ''
  }

  // -----------------------------------------------------------------------
  // Output subscription (non-reactive)
  // -----------------------------------------------------------------------

  /**
   * Subscribe to live output chunks for a session. Returns an unsubscribe.
   * The caller (a mounted xterm) typically replays {@link bufferFor} first,
   * then writes each subsequent chunk delivered here.
   */
  function subscribe(sessionId: string, cb: (data: string) => void): () => void {
    let set = subscribers.get(sessionId)
    if (!set) {
      set = new Set()
      subscribers.set(sessionId, set)
    }
    set.add(cb)
    return () => {
      subscribers.get(sessionId)?.delete(cb)
    }
  }

  // -----------------------------------------------------------------------
  // Internal mutators (reassign for reactivity, mirroring scope.ts)
  // -----------------------------------------------------------------------

  function _upsert(conversationId: string, session: TerminalSession): void {
    const list = byConversation.value[conversationId] ?? []
    const idx = list.findIndex((s) => s.id === session.id)
    const next = idx >= 0 ? list.map((s) => (s.id === session.id ? session : s)) : [...list, session]
    byConversation.value = { ...byConversation.value, [conversationId]: next }
  }

  function _patch(
    conversationId: string, sessionId: string, patch: Partial<TerminalSession>,
  ): void {
    const list = byConversation.value[conversationId]
    if (!list) return
    byConversation.value = {
      ...byConversation.value,
      [conversationId]: list.map((s) => (s.id === sessionId ? { ...s, ...patch } : s)),
    }
  }

  function _remove(conversationId: string, sessionId: string): void {
    const list = byConversation.value[conversationId]
    if (!list) return
    byConversation.value = {
      ...byConversation.value,
      [conversationId]: list.filter((s) => s.id !== sessionId),
    }
  }

  function _setAssigned(conversationId: string, sessionId: string): void {
    const list = byConversation.value[conversationId]
    if (!list) return
    byConversation.value = {
      ...byConversation.value,
      [conversationId]: list.map((s) => ({ ...s, agent_assigned: s.id === sessionId })),
    }
  }

  function _appendBuffer(sessionId: string, data: string): void {
    const prev = buffers.get(sessionId) ?? ''
    let next = prev + data
    if (next.length > MAX_BUFFER) next = next.slice(next.length - MAX_BUFFER)
    buffers.set(sessionId, next)
  }

  // -----------------------------------------------------------------------
  // REST actions
  // -----------------------------------------------------------------------

  async function fetch(conversationId: string): Promise<void> {
    loading.value = true
    try {
      const res = await terminalApi.listTerminals(conversationId)
      enabled.value = res.enabled
      byConversation.value = { ...byConversation.value, [conversationId]: res.sessions }
      fetched.value.add(conversationId)
    } finally {
      loading.value = false
    }
  }

  async function ensureForConversation(conversationId: string): Promise<void> {
    if (fetched.value.has(conversationId)) return
    fetched.value.add(conversationId)
    try {
      await fetch(conversationId)
    } catch (err) {
      fetched.value.delete(conversationId)
      throw err
    }
  }

  /** Open a new session. Lets {@link ApiError} (e.g. 400 no-scope, 403) propagate. */
  async function create(
    conversationId: string, body: TerminalCreateRequest = {},
  ): Promise<TerminalSession> {
    const session = await terminalApi.createTerminal(conversationId, body)
    _upsert(conversationId, session)
    return session
  }

  /** Kill a session (its process tree). */
  async function kill(conversationId: string, sessionId: string): Promise<void> {
    await terminalApi.deleteTerminal(conversationId, sessionId)
    _remove(conversationId, sessionId)
    buffers.delete(sessionId)
  }

  /** Rename a session. */
  async function rename(
    conversationId: string, sessionId: string, title: string,
  ): Promise<void> {
    const updated = await terminalApi.updateTerminal(conversationId, sessionId, { title })
    _upsert(conversationId, updated)
  }

  /** Assign a session to the agent (exactly one per conversation). */
  async function assign(conversationId: string, sessionId: string): Promise<void> {
    await terminalApi.updateTerminal(conversationId, sessionId, { assign_to_agent: true })
    _setAssigned(conversationId, sessionId)
  }

  // -----------------------------------------------------------------------
  // Live I/O (over the events WS)
  // -----------------------------------------------------------------------

  function sendInput(conversationId: string, sessionId: string, data: string): void {
    sendEventsMessage({
      type: 'terminal.input',
      conversation_id: conversationId,
      session_id: sessionId,
      data,
    })
  }

  function sendResize(
    conversationId: string, sessionId: string, rows: number, cols: number,
  ): void {
    sendEventsMessage({
      type: 'terminal.resize',
      conversation_id: conversationId,
      session_id: sessionId,
      rows,
      cols,
    })
  }

  // -----------------------------------------------------------------------
  // WS event folders
  // -----------------------------------------------------------------------

  function applySessionOpened(msg: WsTerminalSessionOpenedMessage): void {
    _upsert(msg.conversation_id, msg.session)
  }

  function applyOutput(msg: WsTerminalOutputMessage): void {
    _appendBuffer(msg.session_id, msg.data)
    const subs = subscribers.get(msg.session_id)
    if (subs) for (const cb of subs) cb(msg.data)
  }

  function applyClosed(msg: WsTerminalClosedMessage): void {
    _remove(msg.conversation_id, msg.session_id)
    buffers.delete(msg.session_id)
  }

  function applyRenamed(msg: WsTerminalRenamedMessage): void {
    _patch(msg.conversation_id, msg.session_id, { title: msg.title })
  }

  function applyAssigned(msg: WsTerminalAssignedMessage): void {
    _setAssigned(msg.conversation_id, msg.session_id)
  }

  function reset(): void {
    byConversation.value = {}
    fetched.value = new Set()
    buffers.clear()
    subscribers.clear()
  }

  return {
    // state
    byConversation,
    enabled,
    fetched,
    loading,
    // getters
    sessionsFor,
    assignedFor,
    activeCountFor,
    bufferFor,
    // output
    subscribe,
    // rest
    fetch,
    ensureForConversation,
    create,
    kill,
    rename,
    assign,
    // live io
    sendInput,
    sendResize,
    // ws folders
    applySessionOpened,
    applyOutput,
    applyClosed,
    applyRenamed,
    applyAssigned,
    reset,
  }
})
