<template>
    <section class="settings-section">
        <h3 class="settings-section__title">Knowledge Graph</h3>
        <p class="kg-subtitle">Gestisci il grafo di conoscenza del server MCP Memory (entità, relazioni, osservazioni).
        </p>

        <!-- Disabled state when memory server is not connected -->
        <div v-if="!memoryConnected" class="kg-disabled">
            <span class="kg-disabled__icon">⚠</span>
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
/* ── Subtitle ──────────────────────────────────────────── */
.kg-subtitle {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--text-secondary, #8a8578);
    margin: 0 0 var(--space-3, 12px);
}

/* ── Disabled state ────────────────────────────────────── */
.kg-disabled {
    display: flex;
    align-items: center;
    gap: var(--space-2, 8px);
    padding: var(--space-3, 12px) var(--space-4, 16px);
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    color: var(--text-muted, #5c584f);
    font-size: var(--text-sm, 0.8125rem);
    line-height: 1.5;
}

.kg-disabled__icon {
    font-size: 1.1rem;
    flex-shrink: 0;
}

/* ── Stats bar ─────────────────────────────────────────── */
.kg-stats {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3, 12px);
    padding: var(--space-2, 8px) var(--space-3, 12px);
    background: var(--bg-secondary, #13161c);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    margin-bottom: var(--space-3, 12px);
}

.kg-stats__item {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-secondary, #8a8578);
}

.kg-stats__item strong {
    color: var(--accent, #c9a84c);
    font-weight: 600;
}

/* ── Toolbar ───────────────────────────────────────────── */
.kg-toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2, 8px);
    margin-bottom: var(--space-3, 12px);
    align-items: center;
}

.kg-search {
    display: flex;
    flex: 1;
    min-width: 180px;
    gap: var(--space-1, 4px);
}

.kg-search__input {
    flex: 1;
    padding: var(--space-1, 4px) var(--space-2, 8px);
    background: var(--bg-input, rgba(255, 255, 255, 0.03));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    color: var(--text-primary, #e8e4de);
    font-size: var(--text-sm, 0.8125rem);
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s;
}

.kg-search__input::placeholder {
    color: var(--text-muted, #5c584f);
    opacity: 0.7;
}

.kg-search__input:focus {
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
}

.kg-search__btn {
    padding: var(--space-1, 4px) var(--space-3, 12px);
    background: var(--accent-dim, rgba(201, 168, 76, 0.12));
    border: 1px solid var(--accent-border, rgba(201, 168, 76, 0.25));
    border-radius: var(--radius-sm, 4px);
    color: var(--accent, #c9a84c);
    font-size: var(--text-sm, 0.8125rem);
    font-weight: 500;
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s;
}

.kg-search__btn:hover:not(:disabled) {
    background: var(--accent-light, rgba(201, 168, 76, 0.10));
    border-color: var(--accent, #c9a84c);
}

.kg-search__btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

.kg-actions {
    display: flex;
    gap: var(--space-2, 8px);
}

/* ── Buttons ───────────────────────────────────────────── */
.kg-btn {
    padding: var(--space-1, 4px) var(--space-3, 12px);
    border-radius: var(--radius-sm, 4px);
    font-size: var(--text-sm, 0.8125rem);
    font-weight: 500;
    cursor: pointer;
    border: 1px solid transparent;
    transition: background 0.2s, border-color 0.2s, color 0.2s;
}

.kg-btn--accent {
    background: var(--accent-dim, rgba(201, 168, 76, 0.12));
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
    color: var(--accent, #c9a84c);
}

.kg-btn--accent:hover:not(:disabled) {
    background: var(--accent-light, rgba(201, 168, 76, 0.10));
    border-color: var(--accent, #c9a84c);
}

.kg-btn--secondary {
    background: var(--bg-tertiary, #1a1e26);
    border-color: var(--border, rgba(255, 255, 255, 0.08));
    color: var(--text-secondary, #8a8578);
}

.kg-btn--secondary:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-primary, #e8e4de);
}

.kg-btn--danger {
    background: rgba(220, 80, 80, 0.1);
    border-color: rgba(220, 80, 80, 0.25);
    color: rgba(220, 80, 80, 0.9);
}

.kg-btn--danger:hover:not(:disabled) {
    background: rgba(220, 80, 80, 0.18);
    border-color: rgba(220, 80, 80, 0.4);
}

.kg-btn--text {
    background: none;
    border: none;
    color: var(--accent, #c9a84c);
    padding: 0;
    font-size: var(--text-xs, 0.75rem);
}

.kg-btn--text:hover {
    text-decoration: underline;
}

.kg-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

/* ── Type filter ───────────────────────────────────────── */
.kg-type-filter {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1, 4px);
    margin-bottom: var(--space-2, 8px);
}

.kg-type-tag {
    padding: 2px 10px;
    border-radius: 9999px;
    font-size: 0.7rem;
    font-weight: 500;
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    background: transparent;
    color: var(--text-secondary, #8a8578);
    cursor: pointer;
    transition: all 0.2s;
}

.kg-type-tag:hover {
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
    color: var(--text-primary, #e8e4de);
}

.kg-type-tag--active {
    background: var(--accent-dim, rgba(201, 168, 76, 0.12));
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
    color: var(--accent, #c9a84c);
}

/* ── Loading / Error / Empty ───────────────────────────── */
.kg-loading {
    color: var(--text-muted, #5c584f);
    padding: var(--space-2, 8px);
    font-size: var(--text-sm, 0.8125rem);
}

.kg-error {
    color: rgba(220, 80, 80, 0.9);
    padding: var(--space-2, 8px);
    font-size: var(--text-sm, 0.8125rem);
    background: rgba(220, 80, 80, 0.06);
    border-radius: var(--radius-sm, 4px);
    margin-bottom: var(--space-2, 8px);
}

.kg-empty {
    color: var(--text-muted, #5c584f);
    padding: var(--space-4, 16px);
    text-align: center;
    font-size: var(--text-sm, 0.8125rem);
}

/* ── Section ───────────────────────────────────────────── */
.kg-section {
    margin-bottom: var(--space-3, 12px);
}

.kg-section__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-2, 8px);
}

.kg-section__title {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--text-secondary, #8a8578);
    font-weight: 600;
}

/* ── Entity list ───────────────────────────────────────── */
.kg-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2, 8px);
    max-height: 500px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--accent-dim, rgba(201, 168, 76, 0.12)) transparent;
}

.kg-list::-webkit-scrollbar {
    width: 4px;
}

.kg-list::-webkit-scrollbar-track {
    background: transparent;
}

.kg-list::-webkit-scrollbar-thumb {
    background: var(--accent-dim, rgba(201, 168, 76, 0.12));
    border-radius: 4px;
}

.kg-list::-webkit-scrollbar-thumb:hover {
    background: rgba(201, 168, 76, 0.25);
}

/* ── Dialog overlay ────────────────────────────────────── */
.kg-overlay {
    position: fixed;
    inset: 0;
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
}

.kg-dialog {
    background: var(--bg-tertiary, #1a1e26);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-md, 8px);
    padding: var(--space-6, 24px);
    max-width: 440px;
    width: 90%;
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}

.kg-dialog__title {
    font-size: var(--text-base, 0.875rem);
    font-weight: 600;
    color: var(--text-primary, #e8e4de);
    margin: 0 0 var(--space-4, 16px);
}

.kg-dialog__message {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--text-primary, #e8e4de);
    line-height: 1.5;
    margin: 0 0 var(--space-4, 16px);
    white-space: pre-line;
}

.kg-dialog__actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2, 8px);
    margin-top: var(--space-4, 16px);
}

/* ── Form fields ───────────────────────────────────────── */
.kg-field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1, 4px);
    margin-bottom: var(--space-3, 12px);
}

.kg-field__label {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-secondary, #8a8578);
    font-weight: 500;
}

.kg-input {
    padding: var(--space-1, 4px) var(--space-2, 8px);
    background: var(--bg-input, rgba(255, 255, 255, 0.03));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    color: var(--text-primary, #e8e4de);
    font-size: var(--text-sm, 0.8125rem);
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s;
}

.kg-input:focus {
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
}

.kg-input option {
    background: var(--bg-tertiary, #1a1e26);
    color: var(--text-primary, #e8e4de);
}

.kg-textarea {
    padding: var(--space-2, 8px);
    background: var(--bg-input, rgba(255, 255, 255, 0.03));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    color: var(--text-primary, #e8e4de);
    font-size: var(--text-sm, 0.8125rem);
    font-family: inherit;
    outline: none;
    resize: vertical;
    transition: border-color 0.2s;
}

.kg-textarea:focus {
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
}
</style>
