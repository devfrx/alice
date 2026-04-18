<template>
    <section class="settings-section">
        <h3 class="settings-section__title">Knowledge Graph</h3>
        <p class="kg-subtitle">Gestisci il grafo di conoscenza del server MCP Memory (entità, relazioni, osservazioni).
        </p>

        <!-- Disabled state when memory server is not connected -->
        <div v-if="!memoryConnected" class="kg-disabled" role="alert">
            <AppIcon name="alert-triangle" :size="14" :stroke-width="2" class="kg-disabled__icon" />
            <span>Il server MCP <strong>memory</strong> non è connesso. Abilitalo nella sezione Server MCP per
                gestire il Knowledge Graph.</span>
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
                    <input v-model="searchQuery" type="text" class="kg-search__input" placeholder="Cerca entità…"
                        aria-label="Cerca nel grafo" @keydown.enter="onSearch" />
                    <button class="kg-search__btn" :disabled="!searchQuery.trim() || store.loading"
                        @click="onSearch">Cerca</button>
                </div>
                <div class="kg-actions">
                    <button class="kg-btn kg-btn--accent" @click="showCreateEntity = true">
                        + Entità
                    </button>
                    <button class="kg-btn kg-btn--accent" :disabled="store.entityCount < 2"
                        @click="showCreateRelation = true">
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
                    <span class="kg-section__title">Risultati ricerca ({{ store.searchEntities.length }})</span>
                    <button class="kg-btn kg-btn--text" @click="clearSearch">Annulla ricerca</button>
                </div>
                <div v-if="store.searchEntities.length === 0 && !store.loading" class="kg-empty">
                    Nessun risultato trovato
                </div>
                <div v-else class="kg-list">
                    <EntityCard v-for="entity in store.searchEntities" :key="entity.name" :entity="entity"
                        :relations="relationsFor(entity.name, store.searchRelations)"
                        @delete="confirmDeleteEntity(entity.name)" @add-observation="openAddObservation(entity.name)"
                        @delete-observation="confirmDeleteObservation" />
                </div>
            </div>

            <!-- Full entity list -->
            <div v-if="!showSearchResults" class="kg-section">
                <!-- Type filter -->
                <div v-if="store.entityTypes.length > 1" class="kg-type-filter">
                    <button class="kg-type-tag" :class="{ 'kg-type-tag--active': !typeFilter }"
                        @click="typeFilter = ''">Tutti</button>
                    <button v-for="t in store.entityTypes" :key="t" class="kg-type-tag"
                        :class="{ 'kg-type-tag--active': typeFilter === t }" @click="typeFilter = t">{{ t }}</button>
                </div>

                <div class="kg-section__header">
                    <span class="kg-section__title">Entità ({{ filteredEntities.length }})</span>
                </div>
                <div v-if="filteredEntities.length === 0 && !store.loading" class="kg-empty">
                    Nessuna entità nel grafo
                </div>
                <div v-else class="kg-list">
                    <EntityCard v-for="entity in filteredEntities" :key="entity.name" :entity="entity"
                        :relations="relationsFor(entity.name, store.relations)"
                        @delete="confirmDeleteEntity(entity.name)" @add-observation="openAddObservation(entity.name)"
                        @delete-observation="confirmDeleteObservation" @delete-relation="confirmDeleteRelation" />
                </div>
            </div>

            <!-- Create Entity dialog -->
            <Teleport to="body">
                <div v-if="showCreateEntity" class="kg-overlay" @click.self="showCreateEntity = false">
                    <div class="kg-dialog" role="dialog" aria-modal="true">
                        <h4 class="kg-dialog__title">Nuova entità</h4>
                        <label class="kg-field">
                            <span class="kg-field__label">Nome</span>
                            <input v-model="newEntity.name" type="text" class="kg-input"
                                placeholder="es. Mario Rossi" />
                        </label>
                        <label class="kg-field">
                            <span class="kg-field__label">Tipo</span>
                            <input v-model="newEntity.entityType" type="text" class="kg-input"
                                placeholder="es. persona, luogo, concetto" />
                        </label>
                        <label class="kg-field">
                            <span class="kg-field__label">Osservazioni (una per riga)</span>
                            <textarea v-model="newEntity.observationsText" class="kg-textarea" rows="3"
                                placeholder="es. Lavora come ingegnere&#10;Vive a Milano" />
                        </label>
                        <div class="kg-dialog__actions">
                            <button class="kg-btn kg-btn--secondary" @click="showCreateEntity = false">Annulla</button>
                            <button class="kg-btn kg-btn--accent"
                                :disabled="!newEntity.name.trim() || !newEntity.entityType.trim()"
                                @click="onCreate">Crea</button>
                        </div>
                    </div>
                </div>
            </Teleport>

            <!-- Create Relation dialog -->
            <Teleport to="body">
                <div v-if="showCreateRelation" class="kg-overlay" @click.self="showCreateRelation = false">
                    <div class="kg-dialog" role="dialog" aria-modal="true">
                        <h4 class="kg-dialog__title">Nuova relazione</h4>
                        <label class="kg-field">
                            <span class="kg-field__label">Da (entità)</span>
                            <select v-model="newRelation.from" class="kg-input">
                                <option value="" disabled>Seleziona…</option>
                                <option v-for="e in store.entities" :key="e.name" :value="e.name">
                                    {{ e.name }} ({{ e.entityType }})
                                </option>
                            </select>
                        </label>
                        <label class="kg-field">
                            <span class="kg-field__label">Tipo relazione</span>
                            <input v-model="newRelation.relationType" type="text" class="kg-input"
                                placeholder="es. conosce, lavora_con, si_trova_a" />
                        </label>
                        <label class="kg-field">
                            <span class="kg-field__label">A (entità)</span>
                            <select v-model="newRelation.to" class="kg-input">
                                <option value="" disabled>Seleziona…</option>
                                <option v-for="e in store.entities" :key="e.name" :value="e.name">
                                    {{ e.name }} ({{ e.entityType }})
                                </option>
                            </select>
                        </label>
                        <div class="kg-dialog__actions">
                            <button class="kg-btn kg-btn--secondary"
                                @click="showCreateRelation = false">Annulla</button>
                            <button class="kg-btn kg-btn--accent"
                                :disabled="!newRelation.from || !newRelation.to || !newRelation.relationType.trim()"
                                @click="onCreateRelation">Crea</button>
                        </div>
                    </div>
                </div>
            </Teleport>

            <!-- Add Observation dialog -->
            <Teleport to="body">
                <div v-if="showAddObservation" class="kg-overlay" @click.self="showAddObservation = false">
                    <div class="kg-dialog" role="dialog" aria-modal="true">
                        <h4 class="kg-dialog__title">Aggiungi osservazione a "{{ observationTarget }}"</h4>
                        <label class="kg-field">
                            <span class="kg-field__label">Nuove osservazioni (una per riga)</span>
                            <textarea v-model="newObservationText" class="kg-textarea" rows="3"
                                placeholder="es. Ha un cane di nome Rex" />
                        </label>
                        <div class="kg-dialog__actions">
                            <button class="kg-btn kg-btn--secondary"
                                @click="showAddObservation = false">Annulla</button>
                            <button class="kg-btn kg-btn--accent" :disabled="!newObservationText.trim()"
                                @click="onAddObservation">Aggiungi</button>
                        </div>
                    </div>
                </div>
            </Teleport>

            <!-- Confirm dialog -->
            <Teleport to="body">
                <div v-if="confirmAction" class="kg-overlay" @click.self="cancelConfirm">
                    <div class="kg-dialog" role="dialog" aria-modal="true">
                        <p class="kg-dialog__message">{{ confirmMessage }}</p>
                        <div class="kg-dialog__actions">
                            <button class="kg-btn kg-btn--secondary" @click="cancelConfirm">Annulla</button>
                            <button class="kg-btn kg-btn--danger" @click="executeConfirm">Conferma</button>
                        </div>
                    </div>
                </div>
            </Teleport>

        </template>
    </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useMcpMemoryStore } from '../../stores/mcpMemory'
import { useMcpStore } from '../../stores/mcp'
import type { KGRelation } from '../../types/mcpMemory'
import EntityCard from './EntityCard.vue'
import AppIcon from '../ui/AppIcon.vue'

const store = useMcpMemoryStore()
const mcpStore = useMcpStore()

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
const showCreateEntity = ref(false)
const newEntity = reactive({ name: '', entityType: '', observationsText: '' })

async function onCreate(): Promise<void> {
    const observations = newEntity.observationsText
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean)
    await store.createEntities([
        { name: newEntity.name.trim(), entityType: newEntity.entityType.trim(), observations },
    ])
    newEntity.name = ''
    newEntity.entityType = ''
    newEntity.observationsText = ''
    showCreateEntity.value = false
}

// ── Create Relation ───────────────────────────────────────────────────────
const showCreateRelation = ref(false)
const newRelation = reactive({ from: '', to: '', relationType: '' })

async function onCreateRelation(): Promise<void> {
    await store.createRelations([
        { from: newRelation.from, to: newRelation.to, relationType: newRelation.relationType.trim() },
    ])
    newRelation.from = ''
    newRelation.to = ''
    newRelation.relationType = ''
    showCreateRelation.value = false
}

// ── Add Observation ───────────────────────────────────────────────────────
const showAddObservation = ref(false)
const observationTarget = ref('')
const newObservationText = ref('')

function openAddObservation(entityName: string): void {
    observationTarget.value = entityName
    newObservationText.value = ''
    showAddObservation.value = true
}

async function onAddObservation(): Promise<void> {
    const contents = newObservationText.value
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean)
    if (contents.length > 0) {
        await store.addObservations(observationTarget.value, contents)
    }
    showAddObservation.value = false
}

// ── Confirmation dialog ───────────────────────────────────────────────────
const confirmAction = ref<(() => Promise<void>) | null>(null)
const confirmMessage = ref('')

function confirmDeleteEntity(name: string): void {
    confirmMessage.value = `Eliminare l'entità "${name}" e tutte le sue relazioni?`
    confirmAction.value = () => store.deleteEntities([name])
}

function confirmDeleteObservation(entityName: string, observation: string): void {
    confirmMessage.value = `Rimuovere questa osservazione da "${entityName}"?\n\n"${observation.slice(0, 100)}…"`
    confirmAction.value = () => store.deleteObservations(entityName, [observation])
}

function confirmDeleteRelation(rel: KGRelation): void {
    confirmMessage.value = `Eliminare la relazione "${rel.from}" → ${rel.relationType} → "${rel.to}"?`
    confirmAction.value = () => store.deleteRelations([rel])
}

async function executeConfirm(): Promise<void> {
    if (confirmAction.value) await confirmAction.value()
    confirmAction.value = null
    confirmMessage.value = ''
}

function cancelConfirm(): void {
    confirmAction.value = null
    confirmMessage.value = ''
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

/* ── Dialog overlay ────────────────────────────────────── */
.kg-overlay {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--black-heavy);
    backdrop-filter: blur(var(--blur-sm));
    -webkit-backdrop-filter: blur(var(--blur-sm));
}

.kg-dialog {
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: var(--space-6);
    max-width: 440px;
    width: 90%;
    box-shadow: var(--shadow-floating);
}

.kg-dialog__title {
    font-size: var(--text-base);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
    margin: 0 0 var(--space-4);
}

.kg-dialog__message {
    font-size: var(--text-sm);
    color: var(--text-primary);
    line-height: var(--leading-normal);
    margin: 0 0 var(--space-4);
    white-space: pre-line;
}

.kg-dialog__actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2);
    margin-top: var(--space-4);
}

/* ── Form fields ───────────────────────────────────────── */
.kg-field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin-bottom: var(--space-3);
}

.kg-field__label {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    font-weight: var(--weight-medium);
}

.kg-input {
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

.kg-input:focus {
    border-color: var(--accent-border);
}

.kg-input option {
    background: var(--surface-3);
    color: var(--text-primary);
}

.kg-textarea {
    padding: var(--space-2);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-primary);
    font-size: var(--text-sm);
    font-family: inherit;
    outline: none;
    resize: vertical;
    transition: border-color var(--transition-fast);
}

.kg-textarea:focus {
    border-color: var(--accent-border);
}
</style>
