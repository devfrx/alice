/** MCP Memory (Knowledge Graph) endpoints (`/api/mcp/memory`). */
import { request } from './http'
import type {
  AddObservationsPayload,
  CreateEntitiesPayload,
  CreateRelationsPayload,
  DeleteEntitiesPayload,
  DeleteObservationsPayload,
  DeleteRelationsPayload,
  KGGraph,
  KGMutationResponse
} from '../../types/mcpMemory'

export const mcpMemoryApi = {
  /** Read the entire knowledge graph. */
  getKnowledgeGraph: (): Promise<KGGraph> => request<KGGraph>('/mcp/memory/graph'),

  /** Search the knowledge graph by query. */
  searchKnowledgeGraph: (query: string): Promise<KGGraph> =>
    request<KGGraph>('/mcp/memory/search', {
      method: 'POST',
      body: JSON.stringify({ query })
    }),

  /** Retrieve specific entities by name. */
  openKnowledgeNodes: (names: string[]): Promise<KGGraph> =>
    request<KGGraph>('/mcp/memory/nodes', {
      method: 'POST',
      body: JSON.stringify({ names })
    }),

  /** Create new entities. */
  createKGEntities: (payload: CreateEntitiesPayload): Promise<KGMutationResponse> =>
    request<KGMutationResponse>('/mcp/memory/entities', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),

  /** Delete entities and their relations. */
  deleteKGEntities: (payload: DeleteEntitiesPayload): Promise<KGMutationResponse> =>
    request<KGMutationResponse>('/mcp/memory/entities', {
      method: 'DELETE',
      body: JSON.stringify(payload)
    }),

  /** Create relations between entities. */
  createKGRelations: (payload: CreateRelationsPayload): Promise<KGMutationResponse> =>
    request<KGMutationResponse>('/mcp/memory/relations', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),

  /** Delete specific relations. */
  deleteKGRelations: (payload: DeleteRelationsPayload): Promise<KGMutationResponse> =>
    request<KGMutationResponse>('/mcp/memory/relations', {
      method: 'DELETE',
      body: JSON.stringify(payload)
    }),

  /** Add observations to existing entities. */
  addKGObservations: (payload: AddObservationsPayload): Promise<KGMutationResponse> =>
    request<KGMutationResponse>('/mcp/memory/observations', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),

  /** Remove specific observations from entities. */
  deleteKGObservations: (payload: DeleteObservationsPayload): Promise<KGMutationResponse> =>
    request<KGMutationResponse>('/mcp/memory/observations', {
      method: 'DELETE',
      body: JSON.stringify(payload)
    })
}
