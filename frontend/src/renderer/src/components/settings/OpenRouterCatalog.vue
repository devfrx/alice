<script setup lang="ts">
/**
 * OpenRouterCatalog.vue — Editorial catalog of OpenRouter models: search,
 * capability filters, tabular pricing, favorites, and active-model selection.
 *
 * Mounted inside OpenRouterManager.vue when provider === 'openrouter'.
 */
import { computed } from 'vue'
import { useOpenrouterStore, type CapabilityFilter } from '../../stores/openrouter'
import { useSettingsStore } from '../../stores/settings'
import type { OpenRouterModel } from '../../types/openrouter'
import AliceSpinner from '../ui/AliceSpinner.vue'
import AppIcon from '../ui/AppIcon.vue'
import UiBadge from '../ui/UiBadge.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiSearchInput from '../ui/UiSearchInput.vue'
import UiSegmented, { type UiSegmentedOption } from '../ui/UiSegmented.vue'

const store = useOpenrouterStore()
const settingsStore = useSettingsStore()

const CAPABILITY_OPTIONS: UiSegmentedOption[] = [
  { value: 'all', label: 'Tutti' },
  { value: 'tools', label: 'Tools', icon: 'tool' },
  { value: 'vision', label: 'Vision', icon: 'eye' },
  { value: 'reasoning', label: 'Reasoning', icon: 'thinking-cap' }
]

/** The currently active OpenRouter model id, from settings. */
const activeModelId = computed(() => settingsStore.settings.llm.openrouterModel)

/** `200000` → `"200k ctx"`; `1048576` → `"1M ctx"`; `0`/`undefined` → `"—"`. */
function formatContext(length?: number): string {
  if (!length) return '—'
  if (length >= 1_000_000) {
    const millions = Math.round((length / 1_000_000) * 10) / 10
    return `${millions % 1 === 0 ? millions.toFixed(0) : millions.toFixed(1)}M ctx`
  }
  if (length >= 1000) return `${Math.round(length / 1000)}k ctx`
  return `${length} ctx`
}

/** Per-token USD price → per-Mtok price, e.g. `0.0000005` → `"$0.50"`; `null`/`undefined` → `"—"`. */
function pricePerMtok(perToken: number | null | undefined): string {
  if (perToken == null) return '—'
  return `$${(perToken * 1_000_000).toFixed(2)}`
}

/** True when both prompt and completion pricing are exactly zero (free model). */
function isFree(model: OpenRouterModel): boolean {
  return model.pricing?.prompt === 0 && model.pricing?.completion === 0
}

function hasAnyCapability(model: OpenRouterModel): boolean {
  return !!(model.supports_tools || model.supports_vision || model.supports_reasoning)
}

function favoriteLabel(id: string): string {
  return store.isFavorite(id) ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti'
}
</script>

<template>
  <div class="or-catalog">
    <div class="or-catalog__toolbar">
      <UiSearchInput
        v-model="store.searchQuery"
        class="or-catalog__search"
        placeholder="Cerca modello…"
        aria-label="Cerca modello"
      />
      <UiSegmented
        :model-value="store.capabilityFilter"
        :options="CAPABILITY_OPTIONS"
        :equal="false"
        size="sm"
        aria-label="Filtro capacità"
        @update:model-value="(v) => (store.capabilityFilter = v as CapabilityFilter)"
      />
      <UiIconButton
        label="Ricarica catalogo"
        variant="ghost"
        size="sm"
        :loading="store.loadingCatalog"
        @click="store.loadCatalog(true)"
      >
        <AppIcon name="refresh-cw" :size="14" />
      </UiIconButton>
    </div>

    <div v-if="store.loadingCatalog" class="or-catalog__status">
      <AliceSpinner size="sm" label="Caricamento catalogo…" />
    </div>

    <UiEmptyState
      v-else-if="store.error"
      icon="alert-triangle"
      title="Errore nel caricamento del catalogo"
      :subtitle="store.error"
      compact
    />

    <UiEmptyState
      v-else-if="store.filteredModels.length === 0"
      icon="search"
      title="Nessun modello corrisponde ai filtri"
      compact
    />

    <ul v-else class="or-catalog__list">
      <li
        v-for="model in store.filteredModels"
        :key="model.id"
        class="or-row"
        :class="{ 'or-row--active': model.id === activeModelId }"
      >
        <button
          type="button"
          class="or-row__select"
          :aria-current="model.id === activeModelId ? 'true' : undefined"
          @click="store.selectModel(model.id)"
        >
          <span class="or-row__main">
            <span class="or-row__name">{{ model.name }}</span>
            <span class="or-row__id">{{ model.id }}</span>
            <span v-if="hasAnyCapability(model)" class="or-row__caps">
              <UiBadge v-if="model.supports_tools" size="sm">tools</UiBadge>
              <UiBadge v-if="model.supports_vision" size="sm">vision</UiBadge>
              <UiBadge v-if="model.supports_reasoning" size="sm">reasoning</UiBadge>
            </span>
          </span>
          <span class="or-row__meta">
            <span class="or-row__ctx">{{ formatContext(model.context_length) }}</span>
            <span v-if="isFree(model)" class="or-row__price or-row__price--free">gratis</span>
            <span v-else class="or-row__price">
              {{ pricePerMtok(model.pricing?.prompt) }} in /
              {{ pricePerMtok(model.pricing?.completion) }} out · Mtok
            </span>
          </span>
        </button>
        <UiIconButton
          class="or-row__fav"
          :label="favoriteLabel(model.id)"
          variant="ghost"
          size="sm"
          toggle
          :active="store.isFavorite(model.id)"
          @click="store.toggleFavorite(model.id)"
        >
          <AppIcon name="star" :size="14" />
        </UiIconButton>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.or-catalog {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.or-catalog__toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.or-catalog__search {
  flex: 1;
  min-width: 0;
}

.or-catalog__status {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5) 0;
}

/* ── List ─────────────────────────────────────────────────────── */

.or-catalog__list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 420px;
  overflow-y: auto;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
}

.or-row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  border-bottom: 1px solid var(--border-subtle);
}

.or-row:last-child {
  border-bottom: none;
}

.or-row--active {
  background: var(--surface-selected, var(--surface-2));
}

.or-row__select {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--duration-fast) var(--ease-out-quart);
}

.or-row:not(.or-row--active) .or-row__select:hover {
  background: var(--surface-hover);
}

.or-row__fav {
  flex-shrink: 0;
  margin-inline-end: var(--space-1);
}

/* Editorial restraint: the favorite affordance changes color only when
   active, no filled background pill (kit default for UiIconButton). */
.or-row :deep(.or-row__fav.ui-icon-btn--active) {
  background: transparent;
}

.or-row :deep(.or-row__fav.ui-icon-btn--active:hover) {
  background: var(--surface-hover);
}

/* ── Row content ──────────────────────────────────────────────── */

.or-row__main {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: baseline;
  gap: var(--space-2);
}

.or-row__name {
  flex-shrink: 0;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
}

.or-row__id {
  min-width: 0;
  overflow: hidden;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.or-row__caps {
  display: inline-flex;
  flex-shrink: 0;
  gap: var(--space-1);
}

.or-row__meta {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--space-0-5);
  font-variant-numeric: tabular-nums;
}

.or-row__ctx {
  font-size: var(--text-2xs);
  color: var(--text-muted);
}

.or-row__price {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  white-space: nowrap;
}

.or-row__price--free {
  color: var(--text-muted);
  font-style: italic;
}
</style>
