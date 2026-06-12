/**
 * artifacts.ts — Frontend types for the AL\CE artifacts registry.
 *
 * Re-exports of the GENERATED OpenAPI schemas (single source of truth:
 * backend/services/artifacts/schemas.py). Fields with backend defaults
 * (artifact_metadata, pinned, conversation_id, …) are OPTIONAL here —
 * consumers must use `??` fallbacks.
 */

import type { ApiSchema } from './generated'

/** Kinds of persisted artifacts (generated enum). */
export type ArtifactKind = ApiSchema<'ArtifactKind'>

/** Single persisted artifact row, as returned by the REST API. */
export type Artifact = ApiSchema<'ArtifactRead'>

/** Paginated artifact list response. */
export type ArtifactListResponse = ApiSchema<'ArtifactListResponse'>

/** JSON content envelope for chart/whiteboard artifacts. */
export type ArtifactContentResponse = ApiSchema<'ArtifactContentResponse'>

/** Outcome of a PATCH content merge. */
export type ArtifactContentUpdateResponse = ApiSchema<'ArtifactContentUpdateResponse'>

/** Query parameters accepted by ``GET /api/artifacts``. */
export interface ArtifactListQuery {
  conversation_id?: string
  kind?: ArtifactKind
  pinned?: boolean
  limit?: number
  offset?: number
}

/** Generated from the backend WS contract — do not redefine locally. */
export type ArtifactCreatedEvent = ApiSchema<'WsArtifactCreated'>
