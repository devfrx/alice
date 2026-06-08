/**
 * plan.ts — Pinia setup-store for per-conversation plans (todo-lists).
 *
 * A plan is the ordered {@link PlanStep} list the model-driven turn engine
 * maintains via the `update_plan` meta-tool. It is kept in sync two ways:
 *
 * - On-demand REST snapshot via {@link ensureForConversation} (fetch-once per
 *   conversation), backed by `GET /api/plans/{conversation_id}`.
 * - Live push: the events WebSocket folds each `plan.updated` frame through
 *   {@link applyPlanUpdated}. The frame carries the FULL step list, so it is
 *   applied directly with no re-fetch.
 *
 * State is keyed by conversation id in a plain record; reactivity is preserved
 * by reassigning the record on every mutation (mirroring `agentRun.ts`).
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '../services/api'
import type { PlanStep } from '../types/plan'

export const usePlanStore = defineStore('plan', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  /** Plan steps known to the client, keyed by conversation id. */
  const byConversation = ref<Record<string, PlanStep[]>>({})

  /** Whether a fetch is currently in flight. */
  const loading = ref(false)

  /** Conversation ids whose plan has been fetched at least once. */
  const fetched = ref<Set<string>>(new Set())

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  /** Lookup helper: the plan steps for a conversation (empty when unknown). */
  function planFor(conversationId: string): PlanStep[] {
    return byConversation.value[conversationId] ?? []
  }

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  /**
   * Fetch the plan snapshot for a conversation, replacing any cached steps.
   * Records the conversation as fetched on success.
   */
  async function fetch(conversationId: string): Promise<void> {
    loading.value = true
    try {
      const res = await api.getPlan(conversationId)
      byConversation.value = { ...byConversation.value, [conversationId]: res.steps }
      fetched.value.add(conversationId)
    } finally {
      loading.value = false
    }
  }

  /** Fetch a conversation's plan only once per session. */
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
   * `plan.updated` → replace the conversation's steps with the pushed list.
   * The frame carries the full plan, so this is a direct fold (no re-fetch).
   */
  function applyPlanUpdated(msg: { conversation_id: string; steps: PlanStep[] }): void {
    byConversation.value = { ...byConversation.value, [msg.conversation_id]: msg.steps }
  }

  /** Clear all cached plans and the fetched-once guard. */
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
    planFor,
    // actions
    fetch,
    ensureForConversation,
    applyPlanUpdated,
    reset,
  }
})
