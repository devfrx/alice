/**
 * Memory-related types aligned with the OMNIA backend API.
 *
 * Every interface here mirrors the JSON shapes returned by
 * `backend/api/routes/memory.py` so the frontend can consume
 * responses without transformation.
 */

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

/** Memory entry returned by the API. */
export interface MemoryEntry {
  id: string
  content: string
  scope: 'long_term' | 'session' | 'user_fact'
  category: string | null
  source: 'llm' | 'user' | 'plugin'
  created_at: string
  expires_at: string | null
  conversation_id: string | null
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

/** Search result with similarity score. */
export interface MemorySearchResult {
  entry: MemoryEntry
  score: number
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

/** Memory statistics. */
export interface MemoryStats {
  total: number
  by_scope: Record<string, number>
  by_category: Record<string, number>
  db_size_bytes: number
}

// ---------------------------------------------------------------------------
// REST response helpers
// ---------------------------------------------------------------------------

/** Memory list response. */
export interface MemoryListResponse {
  entries: MemoryEntry[]
  total: number
}

/** Memory search response. */
export interface MemorySearchResponse {
  results: MemorySearchResult[]
}
