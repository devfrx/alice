/** Artifact (chart/whiteboard/board item) endpoints (`/api/artifacts`). */
import { request } from './http'
import type {
  Artifact,
  ArtifactContentResponse,
  ArtifactContentUpdateResponse,
  ArtifactKind,
  ArtifactListResponse
} from '../../types/artifacts'

export const artifactsApi = {
  /** List artifacts with optional filters and pagination. */
  listArtifacts: (params?: {
    conversation_id?: string
    kind?: ArtifactKind
    pinned?: boolean
    limit?: number
    offset?: number
  }): Promise<ArtifactListResponse> => {
    const qs = new URLSearchParams()
    if (params?.conversation_id) qs.set('conversation_id', params.conversation_id)
    if (params?.kind) qs.set('kind', params.kind)
    if (params?.pinned !== undefined) qs.set('pinned', String(params.pinned))
    if (params?.limit !== undefined) qs.set('limit', String(params.limit))
    if (params?.offset !== undefined) qs.set('offset', String(params.offset))
    const q = qs.toString()
    return request<ArtifactListResponse>(`/artifacts${q ? `?${q}` : ''}`)
  },

  /** Fetch a single artifact by id. */
  getArtifact: (id: string): Promise<Artifact> =>
    request<Artifact>(`/artifacts/${encodeURIComponent(id)}`),

  /** Fetch the JSON content of a chart/whiteboard artifact. */
  getArtifactContent: (id: string): Promise<ArtifactContentResponse> =>
    request<ArtifactContentResponse>(`/artifacts/${encodeURIComponent(id)}/content`),

  /** Merge top-level keys into the JSON content of an artifact. */
  updateArtifactContent: (
    id: string,
    content: Record<string, unknown>
  ): Promise<ArtifactContentUpdateResponse> =>
    request<ArtifactContentUpdateResponse>(`/artifacts/${encodeURIComponent(id)}/content`, {
      method: 'PATCH',
      body: JSON.stringify({ content })
    }),

  /** Pin or unpin an artifact. */
  setArtifactPinned: (id: string, pinned: boolean): Promise<Artifact> =>
    request<Artifact>(`/artifacts/${encodeURIComponent(id)}/pin`, {
      method: 'PATCH',
      body: JSON.stringify({ pinned })
    }),

  /**
   * Delete an artifact row. When *deleteFile* is true the on-disk file is
   * also unlinked.
   */
  deleteArtifact: (id: string, deleteFile = false): Promise<void> => {
    const qs = deleteFile ? '?delete_file=true' : ''
    return request<void>(`/artifacts/${encodeURIComponent(id)}${qs}`, { method: 'DELETE' })
  }
}
