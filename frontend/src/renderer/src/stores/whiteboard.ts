/**
 * Pinia store for AL\CE whiteboard (tldraw) system.
 *
 * Manages whiteboard list, active board loading, and
 * debounced snapshot persistence via the REST API.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../services/api'
import type { WhiteboardListItem, WhiteboardSpec } from '../types/whiteboard'

export const useWhiteboardStore = defineStore('whiteboard', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  const boards = ref<WhiteboardListItem[]>([])
  const total = ref(0)
  const currentBoard = ref<WhiteboardSpec | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const error = ref<string | null>(null)

  // -----------------------------------------------------------------------
  // Computed
  // -----------------------------------------------------------------------

  const hasBoards = computed(() => boards.value.length > 0)

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  /** Load the whiteboard list, with optional conversation filter. */
  async function loadBoards(conversationId?: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await api.getWhiteboards({
        conversation_id: conversationId,
        limit: 100
      })
      boards.value = data.items
      total.value = data.total
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** Load a single whiteboard by ID (includes snapshot). */
  async function loadBoard(boardId: string): Promise<WhiteboardSpec | null> {
    loading.value = true
    error.value = null
    try {
      const spec = await api.getWhiteboard(boardId)
      currentBoard.value = spec
      return spec
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      return null
    } finally {
      loading.value = false
    }
  }

  /** Save a tldraw snapshot (debounced at call-site). */
  async function saveSnapshot(
    boardId: string,
    snapshot: Record<string, unknown>
  ): Promise<boolean> {
    saving.value = true
    try {
      await api.saveWhiteboardSnapshot(boardId, snapshot)
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      return false
    } finally {
      saving.value = false
    }
  }

  /** Delete a whiteboard and refresh the list. */
  async function deleteBoard(boardId: string): Promise<boolean> {
    try {
      await api.deleteWhiteboard(boardId)
      boards.value = boards.value.filter((b) => b.board_id !== boardId)
      if (currentBoard.value?.board_id === boardId) {
        currentBoard.value = null
      }
      total.value = Math.max(0, total.value - 1)
      return true
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      return false
    }
  }

  /** Clear current board selection. */
  function clearCurrent(): void {
    currentBoard.value = null
  }

  return {
    boards,
    total,
    currentBoard,
    loading,
    saving,
    error,
    hasBoards,
    loadBoards,
    loadBoard,
    saveSnapshot,
    deleteBoard,
    clearCurrent
  }
})
