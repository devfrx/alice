/**
 * Knowledge Graph types for the MCP Memory server.
 *
 * Mirrors the JSON shapes returned by the backend endpoints
 * at `/api/mcp/memory/*`.
 */

// ── Core entities ─────────────────────────────────────────────────────────

/** A single entity in the knowledge graph. */
export interface KGEntity {
  name: string
  entityType: string
  observations: string[]
}

/** A directed relation between two entities. */
export interface KGRelation {
  from: string
  to: string
  relationType: string
}

/** The full knowledge graph structure. */
export interface KGGraph {
  entities: KGEntity[]
  relations: KGRelation[]
}

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
