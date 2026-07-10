/**
 * scope.ts — Pinia setup-store for per-conversation workspace scope.
 *
 * A conversation's *scope* is the set of filesystem folders the scoped Terminal
 * plugin is confined to. It is kept in sync three ways:
 *
 * - On-demand REST snapshot via {@link ensureForConversation} (fetch-once per
 *   conversation), backed by `GET /api/scope/{conversation_id}`.
 * - User mutation via {@link setFolders} / {@link clear}, backed by
 *   `PUT` / `DELETE /api/scope/{conversation_id}`. Both are idle-guarded
 *   server-side: while a turn is running the request fails with HTTP 409
 *   (`ApiError.status === 409`, detail `"scope_locked"`), which is left to
 *   propagate so the UI can surface a "scope locked" message.
 * - Live push: the events WebSocket folds each `scope.updated` frame through
 *   {@link applyScopeUpdated}. The frame carries the FULL folder list (but no
 *   `is_idle`), so it is applied directly with no re-fetch.
 *
 * State is keyed by conversation id in a plain record; reactivity is preserved
 * by reassigning the record on every mutation (mirroring `plan.ts`).
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

import { scopeApi } from '../services/api'

/** Per-conversation scope view-model. */
interface ScopeEntry {
  /** Folders the conversation's terminal is confined to. */
  folders: string[]
  /** Whether the conversation is idle (no turn running) — gates mutations. */
  isIdle: boolean
}

export const useScopeStore = defineStore('scope', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  /** Scope entries known to the client, keyed by conversation id. */
  const byConversation = ref<Record<string, ScopeEntry>>({})

  /** Whether a fetch is currently in flight. */
  const loading = ref(false)

  /** Conversation ids whose scope has been fetched at least once. */
  const fetched = ref<Set<string>>(new Set())

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  /** Lookup helper: the scope folders for a conversation (empty when unknown). */
  function foldersFor(conversationId: string): string[] {
    return byConversation.value[conversationId]?.folders ?? []
  }

  /** Lookup helper: whether the conversation is idle (defaults to `true`). */
  function isIdleFor(conversationId: string): boolean {
    return byConversation.value[conversationId]?.isIdle ?? true
  }

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  /**
   * Fetch the scope snapshot for a conversation, replacing any cached entry.
   * Records the conversation as fetched on success.
   */
  async function fetch(conversationId: string): Promise<void> {
    loading.value = true
    try {
      const res = await scopeApi.getScope(conversationId)
      byConversation.value = {
        ...byConversation.value,
        [conversationId]: { folders: res.folders, isIdle: res.is_idle },
      }
      fetched.value.add(conversationId)
    } finally {
      loading.value = false
    }
  }

  /** Fetch a conversation's scope only once per session. */
  async function ensureForConversation(conversationId: string): Promise<void> {
    if (fetched.value.has(conversationId)) return
    fetched.value.add(conversationId) // mark optimistically to dedupe
    try {
      await fetch(conversationId)
    } catch (err) {
      fetched.value.delete(conversationId)
      throw err
    }
  }

  /**
   * `scope.updated` → replace the conversation's folders with the pushed list.
   * The frame carries the full folder set (but no `is_idle`), so the prior
   * `isIdle` is preserved when known and defaults to `true` otherwise.
   */
  function applyScopeUpdated(msg: { conversation_id: string; folders: string[] }): void {
    const existing = byConversation.value[msg.conversation_id]
    byConversation.value = {
      ...byConversation.value,
      [msg.conversation_id]: {
        folders: msg.folders,
        isIdle: existing?.isIdle ?? true,
      },
    }
  }

  /**
   * Replace the conversation's scope folders, persisting server-side.
   *
   * Lets an {@link ApiError} (e.g. HTTP 409 `scope_locked` while a turn is
   * running) propagate so the caller can surface a "scope locked" message.
   */
  async function setFolders(conversationId: string, folders: string[]): Promise<void> {
    const res = await scopeApi.setScope(conversationId, folders)
    byConversation.value = {
      ...byConversation.value,
      [conversationId]: { folders: res.folders, isIdle: res.is_idle },
    }
  }

  /**
   * Clear the conversation's scope (empties the folder list), persisting
   * server-side. Lets an {@link ApiError} (409 `scope_locked`) propagate.
   */
  async function clear(conversationId: string): Promise<void> {
    await scopeApi.clearScope(conversationId)
    byConversation.value = {
      ...byConversation.value,
      [conversationId]: { folders: [], isIdle: true },
    }
  }

  /** Clear all cached scopes and the fetched-once guard. */
  function reset(): void {
    byConversation.value = {}
    fetched.value = new Set()
  }

  return {
    // state
    byConversation,
    loading,
    fetched,
    // getters
    foldersFor,
    isIdleFor,
    // actions
    fetch,
    ensureForConversation,
    applyScopeUpdated,
    setFolders,
    clear,
    reset,
  }
})
