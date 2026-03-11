/**
 * Pinia store for MCP Memory knowledge graph management.
 *
 * Provides CRUD operations over the Knowledge Graph exposed by
 * the MCP Memory server, via the backend REST endpoints at
 * `/api/mcp/memory`.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../services/api'
import type { KGEntity, KGGraph, KGRelation } from '../types/mcpMemory'

export const useMcpMemoryStore = defineStore('mcpMemory', () => {
  // ── State ───────────────────────────────────────────────────────────────

  const entities = ref<KGEntity[]>([])
  const relations = ref<KGRelation[]>([])
  const searchEntities = ref<KGEntity[]>([])
  const searchRelations = ref<KGRelation[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ── Computed ─────────────────────────────────────────────────────────────

  const entityCount = computed(() => entities.value.length)
  const relationCount = computed(() => relations.value.length)

  /** Unique entity types in the graph. */
  const entityTypes = computed(() => {
    const types = new Set(entities.value.map((e) => e.entityType))
    return [...types].sort()
  })

  // ── Internal helpers ────────────────────────────────────────────────────

  function _applyGraph(graph: KGGraph): void {
    entities.value = graph.entities ?? []
    relations.value = graph.relations ?? []
  }

  function _setError(err: unknown): void {
    error.value = err instanceof Error ? err.message : String(err)
  }

  // ── Actions ─────────────────────────────────────────────────────────────

  /** Load the full knowledge graph from the MCP Memory server. */
  async function loadGraph(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const graph = await api.getKnowledgeGraph()
      _applyGraph(graph)
    } catch (err) {
      _setError(err)
    } finally {
      loading.value = false
    }
  }

  /** Search entities by query string. */
  async function search(query: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const graph = await api.searchKnowledgeGraph(query)
      searchEntities.value = graph.entities ?? []
      searchRelations.value = graph.relations ?? []
    } catch (err) {
      _setError(err)
    } finally {
      loading.value = false
    }
  }

  /** Create new entities and reload the graph. */
  async function createEntities(
    items: { name: string; entityType: string; observations: string[] }[],
  ): Promise<void> {
    error.value = null
    try {
      await api.createKGEntities({ entities: items })
      await loadGraph()
    } catch (err) {
      _setError(err)
    }
  }

  /** Delete entities by name and reload the graph. */
  async function deleteEntities(names: string[]): Promise<void> {
    error.value = null
    try {
      await api.deleteKGEntities({ entityNames: names })
      await loadGraph()
    } catch (err) {
      _setError(err)
    }
  }

  /** Create relations between entities and reload. */
  async function createRelations(
    items: { from: string; to: string; relationType: string }[],
  ): Promise<void> {
    error.value = null
    try {
      await api.createKGRelations({ relations: items })
      await loadGraph()
    } catch (err) {
      _setError(err)
    }
  }

  /** Delete specific relations and reload. */
  async function deleteRelations(
    items: { from: string; to: string; relationType: string }[],
  ): Promise<void> {
    error.value = null
    try {
      await api.deleteKGRelations({ relations: items })
      await loadGraph()
    } catch (err) {
      _setError(err)
    }
  }

  /** Add observations to an existing entity and reload. */
  async function addObservations(
    entityName: string,
    contents: string[],
  ): Promise<void> {
    error.value = null
    try {
      await api.addKGObservations({
        observations: [{ entityName, contents }],
      })
      await loadGraph()
    } catch (err) {
      _setError(err)
    }
  }

  /** Remove specific observations from an entity and reload. */
  async function deleteObservations(
    entityName: string,
    observations: string[],
  ): Promise<void> {
    error.value = null
    try {
      await api.deleteKGObservations({
        deletions: [{ entityName, observations }],
      })
      await loadGraph()
    } catch (err) {
      _setError(err)
    }
  }

  /** Clear search results. */
  function clearSearch(): void {
    searchEntities.value = []
    searchRelations.value = []
  }

  return {
    // State
    entities,
    relations,
    searchEntities,
    searchRelations,
    loading,
    error,
    // Computed
    entityCount,
    relationCount,
    entityTypes,
    // Actions
    loadGraph,
    search,
    createEntities,
    deleteEntities,
    createRelations,
    deleteRelations,
    addObservations,
    deleteObservations,
    clearSearch,
  }
})
