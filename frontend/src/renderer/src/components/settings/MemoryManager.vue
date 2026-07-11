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
      <UiSelect
        :model-value="scopeFilter"
        :options="scopeOptions"
        size="sm"
        aria-label="Filtra per ambito"
        @update:model-value="(v) => (scopeFilter = String(v))"
      />

      <UiSelect
        :model-value="categoryFilter"
        :options="categoryOptions"
        size="sm"
        aria-label="Filtra per categoria"
        @update:model-value="(v) => (categoryFilter = String(v))"
      />

      <div class="mem-search">
        <input
          v-model="searchQuery"
          type="text"
          class="mem-search__input"
          placeholder="Ricerca semantica…"
          aria-label="Ricerca semantica"
          @keydown.enter="onSearch"
        />
        <button
          class="mem-search__btn"
          :disabled="!searchQuery.trim() || store.loading"
          @click="onSearch"
        >
          Cerca
        </button>
      </div>
    </div>

    <!-- Actions row -->
    <div class="mem-actions">
      <button
        class="mem-btn mem-btn--danger"
        :disabled="store.loading"
        @click="confirmClearSession"
      >
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
            <button
              class="mem-entry__delete"
              title="Elimina memoria"
              aria-label="Elimina memoria"
              @click="confirmDelete(entry)"
            >
              <AppIcon name="x" :size="12" :stroke-width="2" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useMemoryStore } from '../../stores/memory'
import type { MemoryEntry } from '../../types/memory'
import AppIcon from '../ui/AppIcon.vue'
import UiSelect, { type UiSelectOption } from '../ui/UiSelect.vue'
import { useModal } from '../../composables/useModal'

const store = useMemoryStore()
const { confirm } = useModal()

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

/** Static scope filter options (leading "all" entry uses the empty value). */
const scopeOptions: UiSelectOption[] = [
  { value: '', label: 'Tutti gli ambiti' },
  { value: 'long_term', label: 'Lungo termine' },
  { value: 'session', label: 'Sessione' }
]

/** Category filter options, derived from stats with a leading "all" entry. */
const categoryOptions = computed<UiSelectOption[]>(() => [
  { value: '', label: 'Tutte le categorie' },
  ...categories.value.map((cat) => ({ value: cat, label: cat }))
])

// ── Confirmation dialog ───────────────────────────────────────────────────

async function confirmDelete(entry: MemoryEntry): Promise<void> {
  const ok = await confirm({
    title: 'Elimina memoria',
    message: `Eliminare questa memoria?\n\n"${entry.content.slice(0, 80)}…"`,
    type: 'danger',
    confirmText: 'Elimina'
  })
  if (!ok) return
  await store.deleteMemory(entry.id)
  await store.loadStats()
}

async function confirmClearSession(): Promise<void> {
  const ok = await confirm({
    title: 'Cancella memoria di sessione',
    message: 'Cancellare tutte le memorie di sessione? Questa azione è irreversibile.',
    type: 'danger',
    confirmText: 'Cancella'
  })
  if (!ok) return
  await store.clearSessionMemory()
  await store.loadStats()
}

async function confirmClearAll(): Promise<void> {
  const ok = await confirm({
    title: 'Cancella tutta la memoria',
    message:
      'Cancellare TUTTA la memoria (sessione e lungo termine)? Questa azione è irreversibile.',
    type: 'danger',
    confirmText: 'Cancella'
  })
  if (!ok) return
  await store.clearAllMemory()
  await store.loadStats()
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
    store.loadMemories(scopeFilter.value || undefined, categoryFilter.value || undefined),
    store.loadStats()
  ])
}

// ── Watchers — reload on filter change ────────────────────────────────────
watch([scopeFilter, categoryFilter], () => {
  showSearchResults.value = false
  store.loadMemories(scopeFilter.value || undefined, categoryFilter.value || undefined)
})

// ── Formatters ────────────────────────────────────────────────────────────
function formatDate(iso?: string | null): string {
  if (!iso) return ''
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
/* ── Shared settings section typography ── */
.settings-section__title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

/* ── Stats bar ─────────────────────────────────────────────── */
.mem-stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-3);
}

.mem-stats__item {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.mem-stats__item strong {
  color: var(--accent);
  font-weight: var(--weight-semibold);
}

/* ── Filters ───────────────────────────────────────────────── */
.mem-filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  align-items: center;
}

.mem-search {
  display: flex;
  flex: 1;
  min-width: 180px;
  gap: var(--space-1);
}

.mem-search__input {
  flex: 1;
  padding: var(--space-1) var(--space-2);
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: inherit;
  outline: none;
  transition: border-color var(--transition-fast);
}

.mem-search__input::placeholder {
  color: var(--text-muted);
  opacity: var(--opacity-medium);
}

.mem-search__input:focus {
  border-color: var(--accent-border);
}

.mem-search__btn {
  padding: var(--space-1) var(--space-3);
  background: var(--accent-dim);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-sm);
  color: var(--accent);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast);
}

.mem-search__btn:hover:not(:disabled) {
  background: var(--accent-light);
  border-color: var(--accent);
}

.mem-search__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ── Action buttons ────────────────────────────────────────── */
.mem-actions {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.mem-btn {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  border: 1px solid transparent;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.mem-btn--secondary {
  background: var(--surface-2);
  border-color: var(--border);
  color: var(--text-secondary);
}

.mem-btn--secondary:hover:not(:disabled) {
  background: var(--white-light);
  color: var(--text-primary);
}

.mem-btn--danger {
  background: var(--danger-light);
  border-color: var(--danger-border);
  color: var(--danger);
}

.mem-btn--danger:hover:not(:disabled) {
  background: var(--danger-hover);
  border-color: var(--danger-strong);
}

.mem-btn--text {
  background: none;
  border: none;
  color: var(--accent);
  padding: 0;
  font-size: var(--text-xs);
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
  color: var(--text-muted);
  padding: var(--space-2);
  font-size: var(--text-sm);
}

.mem-error {
  color: var(--danger);
  padding: var(--space-2);
  font-size: var(--text-sm);
  background: var(--danger-faint);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-2);
}

.mem-empty {
  color: var(--text-muted);
  padding: var(--space-4);
  text-align: center;
  font-size: var(--text-sm);
}

/* ── Section header ────────────────────────────────────────── */
.mem-section {
  margin-bottom: var(--space-3);
}

.mem-section__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.mem-section__title {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: var(--weight-semibold);
}

/* ── Memory list ───────────────────────────────────────────── */
.mem-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 400px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--accent-dim) transparent;
}

.mem-list::-webkit-scrollbar {
  width: 4px;
}

.mem-list::-webkit-scrollbar-track {
  background: transparent;
}

.mem-list::-webkit-scrollbar-thumb {
  background: var(--accent-dim);
  border-radius: var(--radius-xs);
}

.mem-list::-webkit-scrollbar-thumb:hover {
  background: var(--accent-strong);
}

/* ── Memory entry card ─────────────────────────────────────── */
.mem-entry {
  padding: var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  transition: border-color var(--transition-fast);
}

.mem-entry:hover {
  border-color: var(--accent-border);
}

.mem-entry__content {
  font-size: var(--text-sm);
  color: var(--text-primary);
  line-height: var(--leading-normal);
  margin-bottom: var(--space-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.mem-entry__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
}

/* ── Badges ────────────────────────────────────────────────── */
.mem-badge {
  font-size: var(--text-2xs);
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  font-weight: var(--weight-medium);
  text-transform: uppercase;
  letter-spacing: var(--tracking-normal);
}

.mem-badge--scope {
  background: var(--accent-light);
  color: var(--accent);
}

.mem-badge--category {
  background: var(--accent-dim);
  color: var(--text-secondary);
}

.mem-badge--source {
  background: var(--surface-hover);
  color: var(--text-muted);
}

.mem-entry__score {
  font-size: var(--text-xs);
  color: var(--accent);
  opacity: var(--opacity-visible);
  margin-left: auto;
}

.mem-entry__date {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-left: auto;
}

.mem-entry__delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-sm);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
  flex-shrink: 0;
  margin-left: var(--space-1);
}

.mem-entry__delete:hover {
  background: var(--danger-light);
  color: var(--danger);
}
</style>
