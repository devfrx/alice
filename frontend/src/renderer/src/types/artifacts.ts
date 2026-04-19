/**
 * artifacts.ts — Frontend types for the AL\CE artifacts registry.
 *
 * Mirrors the Pydantic schemas in ``backend/services/artifacts/schemas.py``.
 * The registry persists generated tool outputs (3D models, …) and exposes
 * them via REST + a WebSocket ``artifact.created`` event.
 */

/**
 * Kinds of persisted artifacts. Currently limited to the two CAD pipelines
 * exposed by the backend; future kinds (image / audio / chart / whiteboard)
 * can extend this union without breaking consumers.
 */
export type ArtifactKind = 'cad_3d_text' | 'cad_3d_image'

/** Single persisted artifact row, as returned by the REST API. */
export interface Artifact {
  id: string
  conversation_id: string
  message_id: string | null
  tool_call_id: string | null
  kind: ArtifactKind
  title: string
  /** Path relative to ``PROJECT_ROOT`` — DO NOT use directly for URLs. */
  file_path: string
  /** MIME type (e.g. ``model/gltf-binary``). */
  mime: string
  size_bytes: number
  /** Free-form metadata produced by the parser (e.g. ``export_url``). */
  artifact_metadata: Record<string, unknown>
  pinned: boolean
  /** ISO 8601 datetime. */
  created_at: string
  /** ISO 8601 datetime. */
  updated_at: string
  /**
   * Backend-relative download URL (``/api/artifacts/<id>/download``).
   * Pass through ``resolveBackendUrl`` before assigning to ``<img>`` /
   * ``<a href>``.
   */
  download_url: string
}

/** Paginated artifact list response. */
export interface ArtifactListResponse {
  items: Artifact[]
  total: number
}

/** Query parameters accepted by ``GET /api/artifacts``. */
export interface ArtifactListQuery {
  conversation_id?: string
  kind?: ArtifactKind
  pinned?: boolean
  limit?: number
  offset?: number
}

/** Payload of the global ``artifact.created`` WebSocket event. */
export interface ArtifactCreatedEvent {
  type: 'artifact.created'
  artifact_id: string
  kind: ArtifactKind
  conversation_id: string
  title: string
}
