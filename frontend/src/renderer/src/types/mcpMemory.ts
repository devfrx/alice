/**
 * Knowledge Graph types for the MCP Memory server.
 *
 * Mirrors the JSON shapes returned by the backend endpoints
 * at `/api/mcp/memory/*`.
 */

import type { ApiSchema } from './generated'

// ── Core entities ─────────────────────────────────────────────────────────

/** An entity node in the knowledge graph. */
export type KGEntity = ApiSchema<'KGEntityRead'>

/** A directed relation between two entities. */
export type KGRelation = ApiSchema<'KGRelationRead'>

/** The full knowledge graph structure (entities + relations). */
export type KGGraph = ApiSchema<'KGGraphResponse'>

/** Mutation acknowledgement for the 6 KG mutation endpoints. */
export type KGMutationResponse = ApiSchema<'KGMutationResponse'>

// ── Request payloads ──────────────────────────────────────────────────────

/** Payload for creating entities. */
export interface CreateEntitiesPayload {
  entities: {
    name: string
    entityType: string
    observations: string[]
  }[]
}

/** Payload for creating relations. */
export interface CreateRelationsPayload {
  relations: {
    from: string
    to: string
    relationType: string
  }[]
}

/** Payload for adding observations to existing entities. */
export interface AddObservationsPayload {
  observations: {
    entityName: string
    contents: string[]
  }[]
}

/** Payload for deleting entities. */
export interface DeleteEntitiesPayload {
  entityNames: string[]
}

/** Payload for deleting relations. */
export interface DeleteRelationsPayload {
  relations: {
    from: string
    to: string
    relationType: string
  }[]
}

/** Payload for deleting observations. */
export interface DeleteObservationsPayload {
  deletions: {
    entityName: string
    observations: string[]
  }[]
}
