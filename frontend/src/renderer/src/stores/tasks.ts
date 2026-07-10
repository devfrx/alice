/**
 * tasks.ts — Pinia setup-store for per-conversation task lists (todo-lists).
 *
 * A task list is the ordered {@link TaskStep} list the model-driven turn engine
 * maintains via the `update_plan` meta-tool. It is kept in sync two ways:
 *
 * - On-demand REST snapshot via {@link ensureForConversation} (fetch-once per
 *   conversation), backed by `GET /api/tasks/{conversation_id}`.
 * - Live push: the events WebSocket folds each `tasks.updated` frame through
 *   {@link applyTasksUpdated}. The frame carries the FULL step list, so it is
 *   applied directly with no re-fetch.
 *
 * State is keyed by conversation id in a plain record; reactivity is preserved
 * by reassigning the record on every mutation (mirroring `agentRun.ts`).
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

import { tasksApi } from '../services/api'
import type { TaskStep } from '../types/tasks'

export const useTasksStore = defineStore('tasks', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  /** Task steps known to the client, keyed by conversation id. */
  const byConversation = ref<Record<string, TaskStep[]>>({})

  /** Whether a fetch is currently in flight. */
  const loading = ref(false)

  /** Conversation ids whose task list has been fetched at least once. */
  const fetched = ref<Set<string>>(new Set())

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  /** Lookup helper: the task steps for a conversation (empty when unknown). */
  function tasksFor(conversationId: string): TaskStep[] {
    return byConversation.value[conversationId] ?? []
  }

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  /**
   * Fetch the task snapshot for a conversation, replacing any cached steps.
   * Records the conversation as fetched on success.
   */
  async function fetch(conversationId: string): Promise<void> {
    loading.value = true
    try {
      const res = await tasksApi.getTasks(conversationId)
      byConversation.value = { ...byConversation.value, [conversationId]: res.steps }
      fetched.value.add(conversationId)
    } finally {
      loading.value = false
    }
  }

  /** Fetch a conversation's task list only once per session. */
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
   * `tasks.updated` → replace the conversation's steps with the pushed list.
   * The frame carries the full task list, so this is a direct fold (no re-fetch).
   */
  function applyTasksUpdated(msg: { conversation_id: string; steps: TaskStep[] }): void {
    byConversation.value = { ...byConversation.value, [msg.conversation_id]: msg.steps }
  }

  /** Clear all cached task lists and the fetched-once guard. */
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
    tasksFor,
    // actions
    fetch,
    ensureForConversation,
    applyTasksUpdated,
    reset,
  }
})
