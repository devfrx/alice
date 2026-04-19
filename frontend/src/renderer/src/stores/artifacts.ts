/**
 * artifacts.ts — Pinia setup-store for the persisted artifacts registry.
 *
 * Tracks artifacts (3D models, …) produced by tool calls. The list is
 * fetched on demand via {@link useArtifactsStore.fetch} and kept in sync
 * with the backend via the global ``artifact.created`` WebSocket event
 * (see {@link useEventsWebSocket}).
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '../services/api'
import type {
  Artifact,
  ArtifactKind,
  ArtifactListQuery,
} from '../types/artifacts'

export const useArtifactsStore = defineStore('artifacts', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  /** All artifacts known to the client (newest first). */
  const items = ref<Artifact[]>([])

  /** Whether a fetch is currently in flight. */
  const loading = ref(false)

  /** Total artifact count for the most recent filter combination. */
  const total = ref(0)

  /** Conversation ids whose artifacts have been fetched at least once. */
  const fetchedConversations = ref<Set<string>>(new Set())

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  /** Map of ``kind → artifacts[]``. */
  const byKind = computed<Record<ArtifactKind, Artifact[]>>(() => {
    const map: Record<ArtifactKind, Artifact[]> = {
      cad_3d_text: [],
      cad_3d_image: [],
    }
    for (const a of items.value) {
      const bucket = map[a.kind]
      if (bucket) bucket.push(a)
    }
    return map
  })

  /** Pinned artifacts only (preserves global ordering). */
  const pinnedItems = computed(() => items.value.filter((a) => a.pinned))

  /** Lookup helper: artifacts for a given conversation id. */
  function byConversation(id: string): Artifact[] {
    return items.value.filter((a) => a.conversation_id === id)
  }

  /** Lookup helper: artifact created by a given tool_call_id, if any. */
  function byToolCallId(toolCallId: string | null | undefined): Artifact | null {
    if (!toolCallId) return null
    return items.value.find((a) => a.tool_call_id === toolCallId) ?? null
  }

  /** Lookup helper: artifact by id (without fetching). */
  function findById(id: string): Artifact | null {
    return items.value.find((a) => a.id === id) ?? null
  }

  // -----------------------------------------------------------------------
  // Mutations
  // -----------------------------------------------------------------------

  /** Insert or merge an artifact in-place (newest at the front). */
  function addArtifact(artifact: Artifact): void {
    const idx = items.value.findIndex((a) => a.id === artifact.id)
    if (idx === -1) {
      items.value.unshift(artifact)
    } else {
      items.value[idx] = { ...items.value[idx], ...artifact }
    }
  }

  /** Merge a partial update onto an existing artifact. */
  function upsertById(id: string, partial: Partial<Artifact>): void {
    const idx = items.value.findIndex((a) => a.id === id)
    if (idx === -1) return
    items.value[idx] = { ...items.value[idx], ...partial }
  }

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  /**
   * Fetch artifacts from the backend with optional filters.
   * Replaces the in-memory list with the response items.
   */
  async function fetch(params?: ArtifactListQuery): Promise<void> {
    loading.value = true
    try {
      const res = await api.listArtifacts(params)
      // Merge with existing items: replace those returned, keep others.
      const returnedIds = new Set(res.items.map((a) => a.id))
      const kept = items.value.filter((a) => !returnedIds.has(a.id))
      items.value = [...res.items, ...kept].sort((a, b) =>
        b.created_at.localeCompare(a.created_at),
      )
      total.value = res.total
      if (params?.conversation_id) {
        fetchedConversations.value.add(params.conversation_id)
      }
    } finally {
      loading.value = false
    }
  }

  /** Fetch artifacts for a conversation only once per session. */
  async function ensureForConversation(id: string): Promise<void> {
    if (fetchedConversations.value.has(id)) return
    fetchedConversations.value.add(id) // mark optimistically to dedupe
    try {
      await fetch({ conversation_id: id })
    } catch (err) {
      fetchedConversations.value.delete(id)
      throw err
    }
  }

  /**
   * Fetch a single artifact by id and add/merge it into the store.
   * No-op if the artifact is already loaded.
   */
  async function fetchById(id: string): Promise<Artifact | null> {
    const existing = findById(id)
    if (existing) return existing
    try {
      const artifact = await api.getArtifact(id)
      addArtifact(artifact)
      return artifact
    } catch (err) {
      console.warn('[artifacts] fetchById failed:', err)
      return null
    }
  }

  /** Toggle the pin flag for an artifact and persist server-side. */
  async function togglePin(id: string): Promise<void> {
    const current = findById(id)
    const next = !(current?.pinned ?? false)
    // Optimistic update
    if (current) upsertById(id, { pinned: next })
    try {
      const updated = await api.setArtifactPinned(id, next)
      addArtifact(updated)
    } catch (err) {
      // Roll back optimistic update
      if (current) upsertById(id, { pinned: current.pinned })
      throw err
    }
  }

  /** Delete an artifact server-side and remove it from the list. */
  async function remove(id: string, deleteFile = false): Promise<void> {
    await api.deleteArtifact(id, deleteFile)
    const idx = items.value.findIndex((a) => a.id === id)
    if (idx !== -1) items.value.splice(idx, 1)
  }

  return {
    // state
    items,
    loading,
    total,
    // getters
    byKind,
    pinnedItems,
    byConversation,
    byToolCallId,
    findById,
    // actions
    fetch,
    ensureForConversation,
    fetchById,
    togglePin,
    remove,
    addArtifact,
    upsertById,
  }
})
