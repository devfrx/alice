/**
 * memory.ts — Frontend types for the AL\CE memory domain.
 *
 * Re-exports of the GENERATED OpenAPI schemas (single source of truth:
 * backend/services/knowledge/schemas.py). Fields with backend defaults
 * (category, source, created_at, …) are OPTIONAL here — consumers must
 * use `??` fallbacks.
 */

import type { ApiSchema } from './generated'

/** Memory entry returned by the API. */
export type MemoryEntry = ApiSchema<'MemoryEntryRead'>

/** Search result with similarity score. */
export type MemorySearchResult = ApiSchema<'MemorySearchHit'>

/** Memory statistics. */
export type MemoryStats = ApiSchema<'MemoryStatsResponse'>

/** Memory list response ({items, total}). */
export type MemoryListResponse = ApiSchema<'MemoryListResponse'>

/** Memory search response. */
export type MemorySearchResponse = ApiSchema<'MemorySearchResponse'>

/** Single-delete acknowledgement. */
export type MemoryDeleteResponse = ApiSchema<'MemoryDeleteResponse'>

/** Bulk-delete count. */
export type MemoryDeleteCountResponse = ApiSchema<'MemoryDeleteCountResponse'>
