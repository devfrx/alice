/**
 * planDocument.ts — Pinia setup-store for per-conversation plan documents.
 *
 * A plan *document* is the free-form Markdown write-up the turn engine maintains
 * for a conversation (distinct from the ordered `tasks` todo-list). It is kept
 * in sync two ways:
 *
 * - On-demand REST snapshot via {@link ensureForConversation} (fetch-once per
 *   conversation), backed by `GET /api/plan-document/{conversation_id}`.
 * - Live push: the events WebSocket folds each `plan_document.updated` frame
 *   through {@link applyPlanDocumentUpdated}. The frame carries the FULL
 *   document, so it is applied directly with no re-fetch.
 *
 * State is keyed by conversation id in a plain record; reactivity is preserved
 * by reassigning the record on every mutation (mirroring `tasks.ts`). An empty
 * body is treated as "no document": the conversation entry is cleared and
 * {@link documentFor} returns `null`.
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '../services/api'
import type { PlanDocument, WsPlanDocumentUpdatedMessage } from '../types/planDocument'

export const usePlanDocumentStore = defineStore('planDocument', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  /** Plan documents known to the client, keyed by conversation id. */
  const byConversation = ref<Record<string, PlanDocument>>({})

  /** Whether a fetch is currently in flight. */
  const loading = ref(false)

  /** Conversation ids whose plan document has been fetched at least once. */
  const fetched = ref<Set<string>>(new Set())

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  /**
   * Lookup helper: the plan document for a conversation, or `null` when none is
   * known or its body is empty.
   */
  function documentFor(conversationId: string): PlanDocument | null {
    const doc = byConversation.value[conversationId]
    if (!doc || !doc.body) return null
    return doc
  }

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  /** Drop a conversation's cached document (used when the body is empty). */
  function clearDocument(conversationId: string): void {
    if (!(conversationId in byConversation.value)) return
    const next = { ...byConversation.value }
    delete next[conversationId]
    byConversation.value = next
  }

  /**
   * Fetch the plan-document snapshot for a conversation, replacing any cached
   * entry. A non-empty body is stored; an empty body clears the entry. Records
   * the conversation as fetched on success.
   */
  async function fetch(conversationId: string): Promise<void> {
    loading.value = true
    try {
      const res = await api.getPlanDocument(conversationId)
      if (res.body) {
        byConversation.value = {
          ...byConversation.value,
          [conversationId]: { title: res.title, body: res.body, updatedAt: res.updated_at },
        }
      } else {
        clearDocument(conversationId)
      }
      fetched.value.add(conversationId)
    } finally {
      loading.value = false
    }
  }

  /** Fetch a conversation's plan document only once per session. */
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
   * `plan_document.updated` → fold the pushed document into the conversation's
   * entry. The frame carries the full document, so this is a direct fold; an
   * empty body deletes the entry (no document).
   */
  function applyPlanDocumentUpdated(msg: WsPlanDocumentUpdatedMessage): void {
    if (msg.body) {
      byConversation.value = {
        ...byConversation.value,
        [msg.conversation_id]: { title: msg.title, body: msg.body, updatedAt: msg.updated_at ?? null },
      }
    } else {
      clearDocument(msg.conversation_id)
    }
  }

  /** Clear all cached plan documents and the fetched-once guard. */
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
    documentFor,
    // actions
    fetch,
    ensureForConversation,
    applyPlanDocumentUpdated,
    reset,
  }
})
