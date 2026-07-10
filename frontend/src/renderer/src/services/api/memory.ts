/** Episodic memory + Qdrant vector store endpoints (`/api/memory`, `/api/vector-store`). */
import { request } from './http'
import type {
  MemoryListResponse,
  MemorySearchResponse,
  MemoryStats,
  MemoryDeleteResponse,
  MemoryDeleteCountResponse
} from '../../types/memory'
import type { VectorStoreStats } from '../../types/settings'

export const memoryApi = {
  /** Fetch memory entries with optional filters. */
  getMemories: (params?: {
    scope?: string
    category?: string
    limit?: number
    offset?: number
  }): Promise<MemoryListResponse> => {
    const qs = new URLSearchParams()
    if (params?.scope) qs.set('scope', params.scope)
    if (params?.category) qs.set('category', params.category)
    if (params?.limit !== undefined) qs.set('limit', String(params.limit))
    if (params?.offset !== undefined) qs.set('offset', String(params.offset))
    const q = qs.toString()
    return request<MemoryListResponse>(`/memory${q ? `?${q}` : ''}`)
  },

  /** Semantic search over memories. */
  searchMemories: (query: string, limit = 10, category?: string): Promise<MemorySearchResponse> =>
    request<MemorySearchResponse>('/memory/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit, ...(category ? { category } : {}) })
    }),

  /** Delete a single memory entry by ID. */
  deleteMemory: (id: string): Promise<MemoryDeleteResponse> =>
    request<MemoryDeleteResponse>(`/memory/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  /** Clear all session-scoped memories. */
  clearSessionMemory: (): Promise<MemoryDeleteCountResponse> =>
    request<MemoryDeleteCountResponse>('/memory/session', { method: 'DELETE' }),

  /** Clear ALL memories (every scope). */
  clearAllMemory: (): Promise<MemoryDeleteCountResponse> =>
    request<MemoryDeleteCountResponse>('/memory/all', { method: 'DELETE' }),

  /** Load memory statistics. */
  getMemoryStats: (): Promise<MemoryStats> =>
    request<MemoryStats>('/memory/stats'),
}

export const vectorStoreApi = {
  /** Fetch Qdrant vector store statistics. */
  getVectorStoreStats: (): Promise<VectorStoreStats> =>
    request<VectorStoreStats>('/vector-store/stats'),

  /** Trigger re-embedding of all registered tools. */
  reembedTools: (): Promise<{ status: string }> =>
    request<{ status: string }>('/vector-store/reembed-tools', { method: 'POST' }),

  /**
   * Reset the embedded vector store and re-wire the RAG stack (manual repair).
   * Destructive: clears persisted embedded vectors. Returns refreshed stats.
   */
  repairVectorStore: (): Promise<VectorStoreStats> =>
    request<VectorStoreStats>('/vector-store/repair', { method: 'POST' }),
}
