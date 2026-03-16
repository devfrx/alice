<template>
    <section class="settings-section">
        <h3 class="settings-section__title">Gestione Memoria</h3>

        <!-- Stats bar -->
        <div v-if="store.stats" class="mem-stats">
            <span class="mem-stats__item">
                <strong>{{ store.stats.total }}</strong> memorie
            </span>
            <span class="mem-stats__item">
                DB: <strong>{{ formatBytes(store.stats.db_size_bytes) }}</strong>
            </span>
            <span v-for="(count, scope) in store.stats.by_scope" :key="scope" class="mem-stats__item">
                {{ scope }}: <strong>{{ count }}</strong>
            </span>
        </div>

        <!-- Filters row -->
        <div class="mem-filters">
            <select v-model="scopeFilter" class="mem-select" aria-label="Filtra per ambito">
                <option value="">Tutti gli ambiti</option>
                <option value="long_term">Lungo termine</option>
                <option value="session">Sessione</option>
            </select>

            <select v-model="categoryFilter" class="mem-select" aria-label="Filtra per categoria">
                <option value="">Tutte le categorie</option>
                <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
            </select>

            <div class="mem-search">
                <input v-model="searchQuery" type="text" class="mem-search__input" placeholder="Ricerca semantica…"
                    aria-label="Ricerca semantica" @keydown.enter="onSearch" />
                <button class="mem-search__btn" :disabled="!searchQuery.trim() || store.loading" @click="onSearch">
                    Cerca
                </button>
            </div>
        </div>

        <!-- Actions row -->
        <div class="mem-actions">
            <button class="mem-btn mem-btn--danger" :disabled="store.loading" @click="confirmClearSession">
                Cancella memoria di sessione
            </button>
            <button class="mem-btn mem-btn--danger" :disabled="store.loading" @click="confirmClearAll">
                Cancella tutta la memoria
            </button>
            <button class="mem-btn mem-btn--secondary" :disabled="store.loading" @click="onRefresh">
                Aggiorna
            </button>
        </div>

        <!-- Loading -->
        <div v-if="store.loading" class="mem-loading">Caricamento…</div>

        <!-- Error -->
        <div v-if="store.error" class="mem-error">{{ store.error }}</div>

        <!-- Search results -->
        <div v-if="showSearchResults" class="mem-section">
            <div class="mem-section__header">
                <span class="mem-section__title">Risultati ricerca ({{ store.searchResults.length }})</span>
                <button class="mem-btn mem-btn--text" @click="clearSearch">Cancella</button>
            </div>
            <div class="mem-list">
                <div v-for="result in store.searchResults" :key="result.entry.id" class="mem-entry">
                    <div class="mem-entry__content">{{ result.entry.content }}</div>
                    <div class="mem-entry__meta">
                        <span class="mem-badge mem-badge--scope">{{ result.entry.scope }}</span>
                        <span v-if="result.entry.category" class="mem-badge mem-badge--category">
                            {{ result.entry.category }}
                        </span>
                        <span class="mem-badge mem-badge--source">{{ result.entry.source }}</span>
                        <span class="mem-entry__score">Punteggio: {{ result.score.toFixed(3) }}</span>
                        <span class="mem-entry__date">{{ formatDate(result.entry.created_at) }}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Memory entries -->
        <div v-if="!showSearchResults" class="mem-section">
            <div class="mem-section__header">
                <span class="mem-section__title">Voci ({{ store.total }})</span>
            </div>
            <div v-if="store.entries.length === 0 && !store.loading" class="mem-empty">
                Nessuna memoria trovata
            </div>
            <div v-else class="mem-list">
                <div v-for="entry in store.entries" :key="entry.id" class="mem-entry">
                    <div class="mem-entry__content">{{ entry.content }}</div>
                    <div class="mem-entry__meta">
                        <span class="mem-badge mem-badge--scope">{{ entry.scope }}</span>
                        <span v-if="entry.category" class="mem-badge mem-badge--category">
                            {{ entry.category }}
                        </span>
                        <span class="mem-badge mem-badge--source">{{ entry.source }}</span>
                        <span class="mem-entry__date">{{ formatDate(entry.created_at) }}</span>
                        <button class="mem-entry__delete" title="Elimina memoria" aria-label="Elimina memoria"
                            @click="confirmDelete(entry)">
                            ✕
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Confirm dialog -->
        <Teleport to="body">
            <div v-if="confirmAction" class="mem-confirm-overlay" @click.self="cancelConfirm">
                <div class="mem-confirm" role="dialog" aria-modal="true">
                    <p class="mem-confirm__message">{{ confirmMessage }}</p>
                    <div class="mem-confirm__actions">
                        <button class="mem-btn mem-btn--secondary" @click="cancelConfirm">Annulla</button>
                        <button class="mem-btn mem-btn--danger" @click="executeConfirm">Conferma</button>
                    </div>
                </div>
            </div>
        </Teleport>
    </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useMemoryStore } from '../../stores/memory'
import type { MemoryEntry } from '../../types/memory'

const store = useMemoryStore()

// ── Filter state ──────────────────────────────────────────────────────────
const scopeFilter = ref<string>('')
const categoryFilter = ref<string>('')
const searchQuery = ref<string>('')
const showSearchResults = ref(false)

/** Unique categories extracted from stats. */
const categories = computed<string[]>(() => {
    if (!store.stats) return []
    return Object.keys(store.stats.by_category).sort()
})

// ── Confirmation dialog ───────────────────────────────────────────────────
const confirmAction = ref<(() => Promise<void>) | null>(null)
const confirmMessage = ref('')

function confirmDelete(entry: MemoryEntry): void {
    confirmMessage.value = `Eliminare questa memoria?\n\n"${entry.content.slice(0, 80)}…"`
    confirmAction.value = async () => {
        await store.deleteMemory(entry.id)
        await store.loadStats()
    }
}

function confirmClearSession(): void {
    confirmMessage.value = 'Cancellare tutte le memorie di sessione? Questa azione è irreversibile.'
    confirmAction.value = async () => {
        await store.clearSessionMemory()
        await store.loadStats()
    }
}

function confirmClearAll(): void {
    confirmMessage.value = 'Cancellare TUTTA la memoria (sessione e lungo termine)? Questa azione è irreversibile.'
    confirmAction.value = async () => {
        await store.clearAllMemory()
        await store.loadStats()
    }
}

async function executeConfirm(): Promise<void> {
    if (confirmAction.value) {
        await confirmAction.value()
    }
    confirmAction.value = null
    confirmMessage.value = ''
}

function cancelConfirm(): void {
    confirmAction.value = null
    confirmMessage.value = ''
}

// ── Handlers ──────────────────────────────────────────────────────────────
async function onSearch(): Promise<void> {
    const q = searchQuery.value.trim()
    if (!q) return
    await store.searchMemories(q, 20, categoryFilter.value || undefined)
    showSearchResults.value = true
}

function clearSearch(): void {
    searchQuery.value = ''
    showSearchResults.value = false
    store.clearSearchResults()
}

async function onRefresh(): Promise<void> {
    showSearchResults.value = false
    searchQuery.value = ''
    await Promise.all([
        store.loadMemories(
            scopeFilter.value || undefined,
            categoryFilter.value || undefined
        ),
        store.loadStats()
    ])
}

// ── Watchers — reload on filter change ────────────────────────────────────
watch([scopeFilter, categoryFilter], () => {
    showSearchResults.value = false
    store.loadMemories(
        scopeFilter.value || undefined,
        categoryFilter.value || undefined
    )
})

// ── Formatters ────────────────────────────────────────────────────────────
function formatDate(iso: string): string {
    return new Date(iso).toLocaleString()
}

function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ── Lifecycle ─────────────────────────────────────────────────────────────
onMounted(() => {
    store.loadMemories()
    store.loadStats()
})
</script>

<style scoped>
/* ── Stats bar ─────────────────────────────────────────────── */
.mem-stats {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3, 12px);
    padding: var(--space-2, 8px) var(--space-3, 12px);
    background: var(--bg-secondary, #13161c);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    margin-bottom: var(--space-3, 12px);
}

.mem-stats__item {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-secondary, #8a8578);
}

.mem-stats__item strong {
    color: var(--accent, #c9a84c);
    font-weight: 600;
}

/* ── Filters ───────────────────────────────────────────────── */
.mem-filters {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2, 8px);
    margin-bottom: var(--space-3, 12px);
    align-items: center;
}

.mem-select {
    padding: var(--space-1, 4px) var(--space-2, 8px);
    background: var(--bg-input, rgba(255, 255, 255, 0.03));
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    color: var(--text-primary, #e8e4de);
    font-size: var(--text-sm, 0.8125rem);
    font-family: inherit;
    outline: none;
    cursor: pointer;
    transition: border-color 0.2s;
}

.mem-select:focus {
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
}

.mem-select option {
    background: var(--bg-tertiary, #1a1e26);
    color: var(--text-primary, #e8e4de);
}

.mem-search {
    display: flex;
    flex: 1;
    min-width: 180px;
    gap: var(--space-1, 4px);
}

.mem-search__input {
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

.mem-search__input::placeholder {
    color: var(--text-muted, #5c584f);
    opacity: 0.7;
}

.mem-search__input:focus {
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
}

.mem-search__btn {
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

.mem-search__btn:hover:not(:disabled) {
    background: var(--accent-light, rgba(201, 168, 76, 0.10));
    border-color: var(--accent, #c9a84c);
}

.mem-search__btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

/* ── Action buttons ────────────────────────────────────────── */
.mem-actions {
    display: flex;
    gap: var(--space-2, 8px);
    margin-bottom: var(--space-3, 12px);
}

.mem-btn {
    padding: var(--space-1, 4px) var(--space-3, 12px);
    border-radius: var(--radius-sm, 4px);
    font-size: var(--text-sm, 0.8125rem);
    font-weight: 500;
    cursor: pointer;
    border: 1px solid transparent;
    transition: background 0.2s, border-color 0.2s, color 0.2s;
}

.mem-btn--secondary {
    background: var(--bg-tertiary, #1a1e26);
    border-color: var(--border, rgba(255, 255, 255, 0.08));
    color: var(--text-secondary, #8a8578);
}

.mem-btn--secondary:hover:not(:disabled) {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-primary, #e8e4de);
}

.mem-btn--danger {
    background: rgba(220, 80, 80, 0.1);
    border-color: rgba(220, 80, 80, 0.25);
    color: rgba(220, 80, 80, 0.9);
}

.mem-btn--danger:hover:not(:disabled) {
    background: rgba(220, 80, 80, 0.18);
    border-color: rgba(220, 80, 80, 0.4);
}

.mem-btn--text {
    background: none;
    border: none;
    color: var(--accent, #c9a84c);
    padding: 0;
    font-size: var(--text-xs, 0.75rem);
}

.mem-btn--text:hover {
    text-decoration: underline;
}

.mem-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

/* ── Loading / Error / Empty ───────────────────────────────── */
.mem-loading {
    color: var(--text-muted, #5c584f);
    padding: var(--space-2, 8px);
    font-size: var(--text-sm, 0.8125rem);
}

.mem-error {
    color: rgba(220, 80, 80, 0.9);
    padding: var(--space-2, 8px);
    font-size: var(--text-sm, 0.8125rem);
    background: rgba(220, 80, 80, 0.06);
    border-radius: var(--radius-sm, 4px);
    margin-bottom: var(--space-2, 8px);
}

.mem-empty {
    color: var(--text-muted, #5c584f);
    padding: var(--space-4, 16px);
    text-align: center;
    font-size: var(--text-sm, 0.8125rem);
}

/* ── Section header ────────────────────────────────────────── */
.mem-section {
    margin-bottom: var(--space-3, 12px);
}

.mem-section__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-2, 8px);
}

.mem-section__title {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--text-secondary, #8a8578);
    font-weight: 600;
}

/* ── Memory list ───────────────────────────────────────────── */
.mem-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2, 8px);
    max-height: 400px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--accent-dim, rgba(201, 168, 76, 0.12)) transparent;
}

.mem-list::-webkit-scrollbar {
    width: 4px;
}

.mem-list::-webkit-scrollbar-track {
    background: transparent;
}

.mem-list::-webkit-scrollbar-thumb {
    background: var(--accent-dim, rgba(201, 168, 76, 0.12));
    border-radius: 4px;
}

.mem-list::-webkit-scrollbar-thumb:hover {
    background: rgba(201, 168, 76, 0.25);
}

/* ── Memory entry card ─────────────────────────────────────── */
.mem-entry {
    padding: var(--space-3, 12px);
    background: var(--bg-secondary, #13161c);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-sm, 4px);
    transition: border-color 0.2s;
}

.mem-entry:hover {
    border-color: var(--accent-border, rgba(201, 168, 76, 0.25));
}

.mem-entry__content {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--text-primary, #e8e4de);
    line-height: 1.5;
    margin-bottom: var(--space-2, 8px);
    white-space: pre-wrap;
    word-break: break-word;
}

.mem-entry__meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1, 4px);
}

/* ── Badges ────────────────────────────────────────────────── */
.mem-badge {
    font-size: 0.65rem;
    padding: 1px 6px;
    border-radius: 9999px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.03em;
}

.mem-badge--scope {
    background: rgba(201, 168, 76, 0.12);
    color: var(--accent, #c9a84c);
}

.mem-badge--category {
    background: rgba(100, 160, 220, 0.12);
    color: rgba(100, 160, 220, 0.9);
}

.mem-badge--source {
    background: rgba(149, 165, 166, 0.12);
    color: var(--text-muted, #5c584f);
}

.mem-entry__score {
    font-size: var(--text-xs, 0.75rem);
    color: var(--accent, #c9a84c);
    opacity: 0.8;
    margin-left: auto;
}

.mem-entry__date {
    font-size: var(--text-xs, 0.75rem);
    color: var(--text-muted, #5c584f);
    margin-left: auto;
}

.mem-entry__delete {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: var(--radius-sm, 4px);
    border: none;
    background: transparent;
    color: var(--text-muted, #5c584f);
    font-size: 0.75rem;
    cursor: pointer;
    transition: background 0.2s, color 0.2s;
    flex-shrink: 0;
    margin-left: var(--space-1, 4px);
}

.mem-entry__delete:hover {
    background: rgba(220, 80, 80, 0.12);
    color: rgba(220, 80, 80, 0.9);
}

/* ── Confirm dialog overlay ────────────────────────────────── */
.mem-confirm-overlay {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
}

.mem-confirm {
    background: var(--bg-tertiary, #1a1e26);
    border: 1px solid var(--border, rgba(255, 255, 255, 0.08));
    border-radius: var(--radius-md, 8px);
    padding: var(--space-6, 24px);
    max-width: 400px;
    width: 90%;
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}

.mem-confirm__message {
    font-size: var(--text-sm, 0.8125rem);
    color: var(--text-primary, #e8e4de);
    line-height: 1.5;
    margin: 0 0 var(--space-4, 16px);
    white-space: pre-line;
}

.mem-confirm__actions {
    display: flex;
    justify-content: flex-end;
    gap: var(--space-2, 8px);
}
</style>
