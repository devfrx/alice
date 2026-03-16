/**
 * Pinia store for OMNIA memory management.
 *
 * Provides CRUD operations and semantic search over the
 * backend memory service at `/api/memory`.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../services/api'
import type {
  MemoryEntry,
  MemorySearchResult,
  MemoryStats
} from '../types/memory'

export const useMemoryStore = defineStore('memory', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  const entries = ref<MemoryEntry[]>([])
  const total = ref<number>(0)
  const searchResults = ref<MemorySearchResult[]>([])
  const stats = ref<MemoryStats | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  /** Fetch memory entries with optional filters. */
  async function loadMemories(
    scope?: string,
    category?: string,
    limit = 50,
    offset = 0
  ): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await api.getMemories({ scope, category, limit, offset })
      entries.value = data.entries
      total.value = data.total
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** Semantic search over memories. */
  async function searchMemories(
    query: string,
    limit = 10,
    category?: string
  ): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await api.searchMemories(query, limit, category)
      searchResults.value = data.results
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** Delete a single memory entry by ID. */
  async function deleteMemory(id: string): Promise<void> {
    error.value = null
    try {
      await api.deleteMemory(id)
      entries.value = entries.value.filter((e) => e.id !== id)
      total.value = Math.max(0, total.value - 1)
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  /** Clear all session-scoped memories. */
  async function clearSessionMemory(): Promise<void> {
    error.value = null
    try {
      const { deleted_count } = await api.clearSessionMemory()
      entries.value = entries.value.filter((e) => e.scope !== 'session')
      total.value = Math.max(0, total.value - deleted_count)
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  /** Clear ALL memories (every scope). */
  async function clearAllMemory(): Promise<void> {
    error.value = null
    try {
      await api.clearAllMemory()
      entries.value = []
      total.value = 0
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  /** Load memory statistics. */
  async function loadStats(): Promise<void> {
    error.value = null
    try {
      stats.value = await api.getMemoryStats()
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  /** Clear search results. */
  function clearSearchResults(): void {
    searchResults.value = []
  }

  return {
    entries,
    total,
    searchResults,
    stats,
    loading,
    error,
    loadMemories,
    searchMemories,
    deleteMemory,
    clearSessionMemory,
    clearAllMemory,
    loadStats,
    clearSearchResults
  }
})
