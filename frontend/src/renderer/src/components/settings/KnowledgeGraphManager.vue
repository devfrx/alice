<template>
  <section class="settings-section">
    <h3 class="settings-section__title">Knowledge Graph</h3>
    <p class="kg-subtitle">
      Gestisci il grafo di conoscenza del server MCP Memory (entità, relazioni, osservazioni).
    </p>

    <!-- Disabled state when memory server is not connected -->
    <div v-if="!memoryConnected" class="kg-disabled" role="alert">
      <AppIcon name="alert-triangle" :size="14" :stroke-width="2" class="kg-disabled__icon" />
      <span
        >Il server MCP <strong>memory</strong> non è connesso. Abilitalo nella sezione Server MCP
        per gestire il Knowledge Graph.</span
      >
    </div>

    <template v-else>
      <!-- Stats bar -->
      <div class="kg-stats">
        <span class="kg-stats__item">
          <strong>{{ store.entityCount }}</strong> entità
        </span>
        <span class="kg-stats__item">
          <strong>{{ store.relationCount }}</strong> relazioni
        </span>
        <span v-for="t in store.entityTypes" :key="t" class="kg-stats__item">
          {{ t }}: <strong>{{ entitiesByType(t) }}</strong>
        </span>
      </div>

      <!-- Search + Actions -->
      <div class="kg-toolbar">
        <div class="kg-search">
          <input
            v-model="searchQuery"
            type="text"
            class="kg-search__input"
            placeholder="Cerca entità…"
            aria-label="Cerca nel grafo"
            @keydown.enter="onSearch"
          />
          <button
            class="kg-search__btn"
            :disabled="!searchQuery.trim() || store.loading"
            @click="onSearch"
          >
            Cerca
          </button>
        </div>
        <div class="kg-actions">
          <button class="kg-btn kg-btn--accent" @click="openCreateEntity">+ Entità</button>
          <button
            class="kg-btn kg-btn--accent"
            :disabled="store.entityCount < 2"
            @click="openCreateRelation"
          >
            + Relazione
          </button>
          <button class="kg-btn kg-btn--secondary" :disabled="store.loading" @click="onRefresh">
            Aggiorna
          </button>
        </div>
      </div>

      <!-- Loading / Error -->
      <div v-if="store.loading" class="kg-loading">Caricamento…</div>
      <div v-if="store.error" class="kg-error">{{ store.error }}</div>

      <!-- Search results -->
      <div v-if="showSearchResults" class="kg-section">
        <div class="kg-section__header">
          <span class="kg-section__title"
            >Risultati ricerca ({{ store.searchEntities.length }})</span
          >
          <button class="kg-btn kg-btn--text" @click="clearSearch">Annulla ricerca</button>
        </div>
        <div v-if="store.searchEntities.length === 0 && !store.loading" class="kg-empty">
          Nessun risultato trovato
        </div>
        <div v-else class="kg-list">
          <EntityCard
            v-for="entity in store.searchEntities"
            :key="entity.name"
            :entity="entity"
            :relations="relationsFor(entity.name, store.searchRelations)"
            @delete="confirmDeleteEntity(entity.name)"
            @add-observation="openAddObservation(entity.name)"
            @delete-observation="confirmDeleteObservation"
          />
        </div>
      </div>

      <!-- Full entity list -->
      <div v-if="!showSearchResults" class="kg-section">
        <!-- Type filter -->
        <div v-if="store.entityTypes.length > 1" class="kg-type-filter">
          <button
            class="kg-type-tag"
            :class="{ 'kg-type-tag--active': !typeFilter }"
            @click="typeFilter = ''"
          >
            Tutti
          </button>
          <button
            v-for="t in store.entityTypes"
            :key="t"
            class="kg-type-tag"
            :class="{ 'kg-type-tag--active': typeFilter === t }"
            @click="typeFilter = t"
          >
            {{ t }}
          </button>
        </div>

        <div class="kg-section__header">
          <span class="kg-section__title">Entità ({{ filteredEntities.length }})</span>
        </div>
        <div v-if="filteredEntities.length === 0 && !store.loading" class="kg-empty">
          Nessuna entità nel grafo
        </div>
        <div v-else class="kg-list">
          <EntityCard
            v-for="entity in filteredEntities"
            :key="entity.name"
            :entity="entity"
            :relations="relationsFor(entity.name, store.relations)"
            @delete="confirmDeleteEntity(entity.name)"
            @add-observation="openAddObservation(entity.name)"
            @delete-observation="confirmDeleteObservation"
            @delete-relation="confirmDeleteRelation"
          />
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useMcpMemoryStore } from '../../stores/mcpMemory'
import { useMcpStore } from '../../stores/mcp'
import type { KGRelation } from '../../types/mcpMemory'
import EntityCard from './EntityCard.vue'
import AppIcon from '../ui/AppIcon.vue'
import { type UiSelectOption } from '../ui/UiSelect.vue'
import { useModal } from '../../composables/useModal'
import KgCreateEntityDialog from './KgCreateEntityDialog.vue'
import KgCreateRelationDialog from './KgCreateRelationDialog.vue'
import KgAddObservationDialog from './KgAddObservationDialog.vue'

const store = useMcpMemoryStore()
const mcpStore = useMcpStore()
const { confirm, openCustom } = useModal()

/** Whether the MCP memory server is connected. */
const memoryConnected = computed(() => {
  const srv = mcpStore.servers.find((s) => s.name === 'memory')
  return srv?.status === 'connected'
})

// ── Filters ───────────────────────────────────────────────────────────────
const searchQuery = ref('')
const showSearchResults = ref(false)
const typeFilter = ref('')

const filteredEntities = computed(() => {
  if (!typeFilter.value) return store.entities
  return store.entities.filter((e) => e.entityType === typeFilter.value)
})

function entitiesByType(type: string): number {
  return store.entities.filter((e) => e.entityType === type).length
}

function relationsFor(entityName: string, relations: KGRelation[]): KGRelation[] {
  return relations.filter((r) => r.from === entityName || r.to === entityName)
}

// ── Create Entity ─────────────────────────────────────────────────────────

async function openCreateEntity(): Promise<void> {
  // The store action reloads the graph on success, so no extra refresh here.
  await openCustom({ component: KgCreateEntityDialog, title: 'Nuova entità', width: '480px' })
}

// ── Create Relation ───────────────────────────────────────────────────────

/** Entity options for the relation endpoints, labelled with their type. */
const entityOptions = computed<UiSelectOption[]>(() =>
  store.entities.map((e) => ({ value: e.name, label: `${e.name} (${e.entityType})` }))
)

async function openCreateRelation(): Promise<void> {
  // The store action reloads the graph on success, so no extra refresh here.
  await openCustom({
    component: KgCreateRelationDialog,
    props: { entities: entityOptions.value },
    title: 'Nuova relazione',
    width: '480px'
  })
}

// ── Add Observation ───────────────────────────────────────────────────────

async function openAddObservation(entityName: string): Promise<void> {
  // The store action reloads the graph on success, so no extra refresh here.
  await openCustom({
    component: KgAddObservationDialog,
    props: { entityName },
    title: `Aggiungi osservazione · ${entityName}`,
    width: '480px'
  })
}

// ── Confirmation dialog ───────────────────────────────────────────────────

async function confirmDeleteEntity(name: string): Promise<void> {
  const ok = await confirm({
    title: 'Elimina entità',
    message: `Eliminare l'entità "${name}" e tutte le sue relazioni?`,
    type: 'danger',
    confirmText: 'Elimina'
  })
  if (!ok) return
  await store.deleteEntities([name])
}

async function confirmDeleteObservation(entityName: string, observation: string): Promise<void> {
  const ok = await confirm({
    title: 'Rimuovi osservazione',
    message: `Rimuovere questa osservazione da "${entityName}"?\n\n"${observation.slice(0, 100)}…"`,
    type: 'danger',
    confirmText: 'Elimina'
  })
  if (!ok) return
  await store.deleteObservations(entityName, [observation])
}

async function confirmDeleteRelation(rel: KGRelation): Promise<void> {
  const ok = await confirm({
    title: 'Elimina relazione',
    message: `Eliminare la relazione "${rel.from}" → ${rel.relationType} → "${rel.to}"?`,
    type: 'danger',
    confirmText: 'Elimina'
  })
  if (!ok) return
  await store.deleteRelations([rel])
}

// ── Search / Refresh ──────────────────────────────────────────────────────
async function onSearch(): Promise<void> {
  const q = searchQuery.value.trim()
  if (!q) return
  await store.search(q)
  showSearchResults.value = true
}

function clearSearch(): void {
  searchQuery.value = ''
  showSearchResults.value = false
  store.clearSearch()
}

async function onRefresh(): Promise<void> {
  showSearchResults.value = false
  searchQuery.value = ''
  typeFilter.value = ''
  await store.loadGraph()
}

// ── Lifecycle ─────────────────────────────────────────────────────────────
onMounted(async () => {
  if (!mcpStore.servers.length) await mcpStore.loadServers()
  if (memoryConnected.value) store.loadGraph()
})

watch(memoryConnected, (connected) => {
  if (connected) store.loadGraph()
})
</script>

<style scoped>
/* ── Shared settings section typography ── */
.settings-section__title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

/* ── Subtitle ──────────────────────────────────────────── */
.kg-subtitle {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin: 0 0 var(--space-3);
}

/* ── Disabled state ────────────────────────────────────── */
.kg-disabled {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-muted);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
}

.kg-disabled__icon {
  font-size: var(--text-lg);
  flex-shrink: 0;
}

/* ── Stats bar ─────────────────────────────────────────── */
.kg-stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-3);
}

.kg-stats__item {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.kg-stats__item strong {
  color: var(--accent);
  font-weight: var(--weight-semibold);
}

/* ── Toolbar ───────────────────────────────────────────── */
.kg-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  align-items: center;
}

.kg-search {
  display: flex;
  flex: 1;
  min-width: 180px;
  gap: var(--space-1);
}

.kg-search__input {
  flex: 1;
  padding: var(--space-1) var(--space-2);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: inherit;
  outline: none;
  transition: border-color var(--transition-fast);
}

.kg-search__input::placeholder {
  color: var(--text-muted);
}

.kg-search__input:focus {
  border-color: var(--accent-border);
}

.kg-search__btn {
  padding: var(--space-1) var(--space-3);
  background: var(--accent-dim);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-sm);
  color: var(--accent);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.kg-search__btn:hover:not(:disabled) {
  background: var(--accent-light);
  border-color: var(--accent);
}

.kg-search__btn:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

.kg-actions {
  display: flex;
  gap: var(--space-2);
}

/* ── Buttons ───────────────────────────────────────────── */
.kg-btn {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  border: 1px solid transparent;
  transition: all var(--transition-fast);
}

.kg-btn--accent {
  background: var(--accent-dim);
  border-color: var(--accent-border);
  color: var(--accent);
}

.kg-btn--accent:hover:not(:disabled) {
  background: var(--accent-light);
  border-color: var(--accent);
}

.kg-btn--secondary {
  background: var(--surface-3);
  border-color: var(--border);
  color: var(--text-secondary);
}

.kg-btn--secondary:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.kg-btn--danger {
  background: var(--danger-light);
  border-color: var(--danger-border);
  color: var(--danger);
}

.kg-btn--danger:hover:not(:disabled) {
  background: var(--danger-hover);
  border-color: var(--danger);
}

.kg-btn--text {
  background: none;
  border: none;
  color: var(--accent);
  padding: 0;
  font-size: var(--text-xs);
}

.kg-btn--text:hover {
  text-decoration: underline;
}

.kg-btn:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

/* ── Type filter ───────────────────────────────────────── */
.kg-type-filter {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-bottom: var(--space-2);
}

.kg-type-tag {
  padding: 2px 10px;
  border-radius: var(--radius-pill);
  font-size: var(--text-2xs);
  font-weight: var(--weight-medium);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.kg-type-tag:hover {
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.kg-type-tag--active {
  background: var(--accent-dim);
  border-color: var(--accent-border);
  color: var(--accent);
}

/* ── Loading / Error / Empty ───────────────────────────── */
.kg-loading {
  color: var(--text-muted);
  padding: var(--space-2);
  font-size: var(--text-sm);
}

.kg-error {
  color: var(--danger);
  padding: var(--space-2);
  font-size: var(--text-sm);
  background: var(--danger-light);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-2);
}

.kg-empty {
  color: var(--text-muted);
  padding: var(--space-4);
  text-align: center;
  font-size: var(--text-sm);
}

/* ── Section ───────────────────────────────────────────── */
.kg-section {
  margin-bottom: var(--space-3);
}

.kg-section__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.kg-section__title {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: var(--weight-semibold);
}

/* ── Entity list ───────────────────────────────────────── */
.kg-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 500px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--surface-4) transparent;
}

.kg-list::-webkit-scrollbar {
  width: 4px;
}

.kg-list::-webkit-scrollbar-track {
  background: transparent;
}

.kg-list::-webkit-scrollbar-thumb {
  background: var(--surface-4);
  border-radius: 4px;
}

.kg-list::-webkit-scrollbar-thumb:hover {
  background: var(--border-hover);
}
</style>
