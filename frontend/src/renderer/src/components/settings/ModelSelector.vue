<script setup lang="ts">
/**
 * ModelSelector.vue — Compact dropdown for switching models.
 *
 * Accepts a `modelType` prop ('llm' | 'embedding') to filter which models
 * are shown. Displays the current model name as a small button in the input
 * bar area. On click, opens a dropdown listing models with size, capability
 * badges, load status, and metadata.
 */
import { computed, onMounted, ref } from 'vue'
import { useOpenrouterStore } from '../../stores/openrouter'
import { useSettingsStore } from '../../stores/settings'
import type { LMStudioModel } from '../../types/settings'
import AliceSpinner from '../../components/ui/AliceSpinner.vue'
import AppIcon from '../ui/AppIcon.vue'
import UiPopover from '../ui/UiPopover.vue'
import UiSearchInput from '../ui/UiSearchInput.vue'
import UiIconButton from '../ui/UiIconButton.vue'

const props = withDefaults(
  defineProps<{
    /** Which model type to show: 'llm' (default) or 'embedding'. */
    modelType?: 'llm' | 'embedding'
  }>(),
  { modelType: 'llm' }
)

const settingsStore = useSettingsStore()
const openrouterStore = useOpenrouterStore()

const isOpen = ref(false)
const errorMessage = ref<string | null>(null)
const triggerRef = ref<HTMLElement | null>(null)
const searchQuery = ref('')

/** True when this selector should render the OpenRouter catalog instead of LM Studio. */
const isOpenrouterProvider = computed(
  () => settingsStore.settings.llm.provider === 'openrouter' && props.modelType === 'llm'
)

/** All models for this selector's type. */
const typeModels = computed(() =>
  props.modelType === 'embedding' ? settingsStore.embeddingModels : settingsStore.llmModels
)

/** Filter models by search query. */
function filterBySearch(models: LMStudioModel[]): LMStudioModel[] {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return models
  return models.filter((m) => {
    const name = (m.display_name || m.name).toLowerCase()
    const quant = (m.quantization?.name || '').toLowerCase()
    const params = (m.params_string || '').toLowerCase()
    return name.includes(q) || quant.includes(q) || params.includes(q)
  })
}

const loadedModels = computed(() => filterBySearch(typeModels.value.filter((m) => m.loaded)))
const availableModels = computed(() => filterBySearch(typeModels.value.filter((m) => !m.loaded)))
const showSearch = computed(() => typeModels.value.length > 5)

/** The active model for the current type. */
const active = computed(() =>
  props.modelType === 'embedding' ? settingsStore.activeEmbeddingModel : settingsStore.activeModel
)

/** Label shown on the trigger button. */
const triggerLabel = computed(() => {
  if (isOpenrouterProvider.value) {
    return settingsStore.settings.llm.openrouterModel
      ? truncateName(settingsStore.settings.llm.openrouterModel)
      : 'Scegli modello'
  }
  if (active.value) return truncateName(active.value.display_name || active.value.name)
  if (props.modelType === 'embedding') return 'Nessun embedding'
  return settingsStore.settings.llm.model
})

function formatSize(bytes: number): string {
  const gb = bytes / 1_073_741_824
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = bytes / 1_048_576
  return `${mb.toFixed(0)} MB`
}

function truncateName(name: string, maxLen = 24): string {
  return name.length > maxLen ? name.slice(0, maxLen) + '…' : name
}

function toggle(): void {
  if (!isOpen.value) {
    if (isOpenrouterProvider.value) {
      if (openrouterStore.models.length === 0) void openrouterStore.loadCatalog()
    } else if (typeModels.value.length === 0) {
      settingsStore.loadModels()
    }
  }
  isOpen.value = !isOpen.value
  errorMessage.value = null
  if (!isOpen.value) {
    searchQuery.value = ''
    if (isOpenrouterProvider.value) openrouterStore.searchQuery = ''
  }
}

/** Select an OpenRouter model as active and close the popover. */
function selectOpenrouterModel(id: string): void {
  openrouterStore.selectModel(id)
  isOpen.value = false
  openrouterStore.searchQuery = ''
}

async function toggleModelLoad(model: LMStudioModel, event: MouseEvent): Promise<void> {
  event.stopPropagation()
  errorMessage.value = null
  try {
    if (model.loaded && model.loaded_instances.length > 0) {
      await settingsStore.unloadModel(model.loaded_instances[0].id)
    } else {
      await settingsStore.loadModel(model.name)
    }
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Errore'
  }
}

/** Check if a model's load/unload action is in progress. */
function isModelBusy(model: LMStudioModel): boolean {
  if (settingsStore.isModelLoading(model.name)) return true
  if (
    model.loaded &&
    model.loaded_instances.length > 0 &&
    settingsStore.isInstanceUnloading(model.loaded_instances[0].id)
  )
    return true
  return false
}

onMounted(() => {
  settingsStore.loadModels()
})
</script>

<template>
  <div class="ms">
    <!-- Trigger button -->
    <button
      ref="triggerRef"
      class="ms__trigger"
      :class="{
        'ms__trigger--embedding': props.modelType === 'embedding',
        'ms__trigger--open': isOpen
      }"
      aria-haspopup="true"
      :aria-expanded="isOpen"
      @click="toggle"
    >
      <!-- Type icon -->
      <AppIcon
        v-if="props.modelType === 'embedding'"
        class="ms__type-icon"
        name="embedding"
        :size="11"
        title="Embedding model"
      />
      <!-- Warning icon only when LM Studio is disconnected (not relevant on OpenRouter) -->
      <AppIcon
        v-else-if="!isOpenrouterProvider && !settingsStore.lmStudioConnected"
        class="ms__warn-icon"
        name="alert-triangle"
        :size="11"
        title="LM Studio disconnesso"
      />
      <span class="ms__label">{{ triggerLabel }}</span>
      <AliceSpinner v-if="settingsStore.isAnyOperationInProgress" size="xs" />
      <AppIcon
        class="ms__chevron"
        :class="{ 'ms__chevron--open': isOpen }"
        name="chevron-down"
        :size="9"
        :stroke-width="2.5"
      />
    </button>

    <!-- Dropdown — UiPopover owns teleport/positioning/outside-click/Escape.
         Opens upward (placement="top") since the selector lives in the bottom bar. -->
    <UiPopover
      :open="isOpen"
      :anchor-el="triggerRef"
      placement="top"
      aria-label="Selettore modello"
      @update:open="isOpen = $event"
    >
      <div class="ms__dropdown" role="group">
        <!-- OpenRouter branch: active only for the LLM selector when provider === 'openrouter' -->
        <template v-if="isOpenrouterProvider">
          <div class="ms__search">
            <UiSearchInput
              v-model="openrouterStore.searchQuery"
              placeholder="Cerca modello…"
              size="sm"
              aria-label="Cerca modello"
              @keydown.stop
            />
          </div>

          <div v-if="openrouterStore.error" class="ms__error">
            {{ openrouterStore.error }}
          </div>

          <div class="ms__list">
            <!-- Loading state -->
            <div v-if="openrouterStore.loadingCatalog" class="ms__state">
              <AliceSpinner size="xs" label="Caricamento catalogo…" />
            </div>

            <!-- Empty / no results -->
            <div v-else-if="openrouterStore.filteredModels.length === 0" class="ms__state">
              {{
                openrouterStore.searchQuery
                  ? `Nessun risultato per "${openrouterStore.searchQuery}"`
                  : 'Nessun modello disponibile'
              }}
            </div>

            <template v-else>
              <div
                v-for="model in openrouterStore.filteredModels"
                :key="model.id"
                class="ms__item ms__item--or"
                :class="{
                  'ms__item--active': model.id === settingsStore.settings.llm.openrouterModel
                }"
              >
                <button
                  type="button"
                  class="ms__or-select"
                  :aria-current="
                    model.id === settingsStore.settings.llm.openrouterModel || undefined
                  "
                  @click="selectOpenrouterModel(model.id)"
                >
                  <span class="ms__name" :title="model.name">{{ model.name }}</span>
                  <span class="ms__or-id">{{ model.id }}</span>
                </button>
                <UiIconButton
                  label="Preferito"
                  variant="ghost"
                  size="xs"
                  tone="accent"
                  toggle
                  :active="openrouterStore.isFavorite(model.id)"
                  class="ms__or-fav"
                  @click.stop="openrouterStore.toggleFavorite(model.id)"
                >
                  <AppIcon name="star" :size="12" />
                </UiIconButton>
              </div>
            </template>
          </div>
        </template>

        <!-- LM Studio branch (existing flow, unchanged) -->
        <template v-else>
          <!-- Search (only when many models) -->
          <div v-if="showSearch" class="ms__search">
            <UiSearchInput
              v-model="searchQuery"
              placeholder="Cerca modello…"
              size="sm"
              aria-label="Cerca modello"
              @keydown.stop
            />
          </div>

          <!-- Error -->
          <div v-if="errorMessage" class="ms__error">
            {{ errorMessage }}
          </div>

          <!-- Global operation in progress -->
          <div v-if="settingsStore.isAnyOperationInProgress" class="ms__operation">
            <div class="ms__operation-bar">
              <div class="ms__operation-fill" />
            </div>
            <span class="ms__operation-text">{{ settingsStore.operationDescription }}</span>
          </div>

          <!-- Scrollable model list -->
          <div class="ms__list">
            <!-- Loading state -->
            <div v-if="settingsStore.isLoadingModels" class="ms__state">
              <AliceSpinner size="xs" label="Caricamento modelli…" />
            </div>

            <!-- Empty state -->
            <div v-else-if="typeModels.length === 0" class="ms__state">
              {{
                props.modelType === 'embedding'
                  ? 'Nessun modello embedding disponibile'
                  : 'Nessun modello disponibile'
              }}
            </div>

            <!-- No search results -->
            <div
              v-else-if="loadedModels.length === 0 && availableModels.length === 0 && searchQuery"
              class="ms__state"
            >
              Nessun risultato per "{{ searchQuery }}"
            </div>

            <template v-else>
              <!-- Loaded models -->
              <template v-if="loadedModels.length > 0">
                <div class="ms__section-head">
                  <span class="ms__section-dot ms__section-dot--on" />
                  Caricati ({{ loadedModels.length }})
                </div>
                <div
                  v-for="model in loadedModels"
                  :key="'l-' + model.name"
                  class="ms__item ms__item--loaded"
                  :class="{ 'ms__item--busy': isModelBusy(model) }"
                  :aria-disabled="settingsStore.isAnyOperationInProgress || undefined"
                >
                  <span class="ms__accent" />
                  <div class="ms__item-top">
                    <span class="ms__dot ms__dot--on" />
                    <span class="ms__name" :title="model.display_name || model.name">
                      {{ model.display_name || model.name }}
                    </span>
                    <UiIconButton
                      label="Scarica dalla memoria"
                      variant="outlined"
                      size="xs"
                      tone="accent"
                      :loading="isModelBusy(model)"
                      :disabled="settingsStore.isAnyOperationInProgress"
                      class="ms__action-btn"
                      @click="toggleModelLoad(model, $event)"
                    >
                      <AppIcon name="model-unload" :size="11" />
                    </UiIconButton>
                  </div>
                  <div class="ms__item-meta">
                    <span v-if="model.params_string" class="ms__tag ms__tag--params">{{
                      model.params_string
                    }}</span>
                    <span v-if="model.quantization?.name" class="ms__tag ms__tag--quant">{{
                      model.quantization.name
                    }}</span>
                    <span class="ms__tag ms__tag--size">{{ formatSize(model.size) }}</span>
                    <span
                      v-if="model.loaded && model.loaded_instances.length > 0"
                      class="ms__tag ms__tag--ctx"
                    >
                      ctx {{ model.loaded_instances[0].config.context_length.toLocaleString() }}
                    </span>
                    <span v-if="model.capabilities.vision" class="ms__cap" title="Vision">
                      <AppIcon name="eye" :size="11" />
                    </span>
                    <span v-if="model.capabilities.thinking" class="ms__cap" title="Thinking">
                      <AppIcon name="thinking-cap" :size="11" />
                    </span>
                    <span
                      v-if="model.capabilities.trained_for_tool_use"
                      class="ms__cap"
                      title="Tool Use"
                    >
                      <AppIcon name="tool" :size="11" />
                    </span>
                  </div>
                  <!-- Loading progress -->
                  <div v-if="settingsStore.isModelLoading(model.name)" class="ms__progress">
                    <div class="ms__progress-bar" />
                  </div>
                </div>
              </template>

              <!-- Divider -->
              <div
                v-if="loadedModels.length > 0 && availableModels.length > 0"
                class="ms__divider"
              />

              <!-- Available models -->
              <template v-if="availableModels.length > 0">
                <div class="ms__section-head">
                  <span class="ms__section-dot ms__section-dot--off" />
                  Disponibili ({{ availableModels.length }})
                </div>
                <div
                  v-for="model in availableModels"
                  :key="'a-' + model.name"
                  class="ms__item"
                  :class="{ 'ms__item--busy': isModelBusy(model) }"
                  :aria-disabled="settingsStore.isAnyOperationInProgress || undefined"
                >
                  <div class="ms__item-top">
                    <span class="ms__dot ms__dot--off" />
                    <span class="ms__name" :title="model.display_name || model.name">
                      {{ model.display_name || model.name }}
                    </span>
                    <UiIconButton
                      label="Carica in memoria"
                      variant="outlined"
                      size="xs"
                      tone="accent"
                      :loading="isModelBusy(model)"
                      :disabled="settingsStore.isAnyOperationInProgress"
                      class="ms__action-btn"
                      @click="toggleModelLoad(model, $event)"
                    >
                      <AppIcon name="model-load" :size="11" />
                    </UiIconButton>
                  </div>
                  <div class="ms__item-meta">
                    <span v-if="model.params_string" class="ms__tag ms__tag--params">{{
                      model.params_string
                    }}</span>
                    <span v-if="model.quantization?.name" class="ms__tag ms__tag--quant">{{
                      model.quantization.name
                    }}</span>
                    <span class="ms__tag ms__tag--size">{{ formatSize(model.size) }}</span>
                    <span v-if="model.capabilities.vision" class="ms__cap" title="Vision">
                      <AppIcon name="eye" :size="11" />
                    </span>
                    <span v-if="model.capabilities.thinking" class="ms__cap" title="Thinking">
                      <AppIcon name="thinking-cap" :size="11" />
                    </span>
                    <span
                      v-if="model.capabilities.trained_for_tool_use"
                      class="ms__cap"
                      title="Tool Use"
                    >
                      <AppIcon name="tool" :size="11" />
                    </span>
                  </div>
                  <div v-if="settingsStore.isModelLoading(model.name)" class="ms__progress">
                    <div class="ms__progress-bar" />
                  </div>
                </div>
              </template>
            </template>
          </div>
        </template>
      </div>
    </UiPopover>
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════════
   ModelSelector — solid dropdown coherent with the chat input bar
   ═══════════════════════════════════════════════════════════════ */

.ms {
  position: relative;
  display: inline-flex;
}

/* ── Trigger ──────────────────────────────────────────────────── */
.ms__trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  height: 26px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  cursor: pointer;
  white-space: nowrap;
  transition:
    background var(--duration-fast) ease,
    border-color var(--duration-fast) ease,
    color var(--duration-fast) ease;
}

.ms__trigger:hover {
  background: var(--surface-3);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.ms__trigger--open {
  background: var(--surface-3);
  border-color: var(--accent-border);
  color: var(--text-primary);
}

/* Embedding selector: same style, no special background needed */
.ms__trigger--embedding {
  background: var(--surface-2);
}

.ms__trigger--embedding:hover {
  background: var(--surface-3);
}

.ms__warn-icon {
  flex-shrink: 0;
  color: var(--danger);
  animation: ms-warn-blink 2s ease-in-out infinite;
}

@keyframes ms-warn-blink {
  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.4;
  }
}

.ms__type-icon {
  flex-shrink: 0;
  color: var(--text-muted);
  opacity: 0.7;
}

.ms__label {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ms__chevron {
  transition: transform var(--transition-fast);
  color: var(--text-muted);
  flex-shrink: 0;
}

.ms__chevron--open {
  transform: rotate(180deg);
}

/* ── Dropdown content ── slot content teleported to <body> by UiPopover.
   No `panel-class` is passed here, so unlike ChatToolControls/ScopeIndicator
   there is no UiPopover-owned wrapper to reach: the entire dropdown
   (`.ms__dropdown` and everything inside it) is written in THIS component's
   own template as UiPopover's default slot, so it keeps this component's
   scope attribute wherever Teleport relocates the DOM node. ─────────────── */
.ms__dropdown {
  min-width: 340px;
  max-width: min(440px, calc(100vw - 32px));
  display: flex;
  flex-direction: column;
}

/* ── Search ───────────────────────────────────────────────────── */
.ms__search {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-2) var(--space-2-5);
  border-bottom: 1px solid var(--border);
}

/* ── Scrollable list ──────────────────────────────────────────── */
.ms__list {
  max-height: min(420px, 50vh);
  overflow-y: auto;
  padding: var(--space-1);
}

.ms__list::-webkit-scrollbar {
  width: 4px;
}

.ms__list::-webkit-scrollbar-track {
  background: transparent;
}

.ms__list::-webkit-scrollbar-thumb {
  background: var(--border-hover);
  border-radius: 2px;
}

.ms__list::-webkit-scrollbar-thumb:hover {
  background: var(--accent-medium);
}

/* ── Error ────────────────────────────────────────────────────── */
.ms__error {
  padding: var(--space-2) var(--space-2-5);
  color: var(--danger);
  font-size: var(--text-xs);
  background: var(--danger-light);
  border-bottom: 1px solid var(--danger-hover);
}

/* ── Loading / empty states ───────────────────────────────────── */
.ms__state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-3);
  color: var(--text-secondary);
  font-size: var(--text-base);
  justify-content: center;
}

/* ── Operation progress ───────────────────────────────────────── */
.ms__operation {
  padding: var(--space-2) var(--space-2-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  border-bottom: 1px solid var(--border);
}

.ms__operation-bar {
  height: 2px;
  background: var(--bg-primary);
  border-radius: 1px;
  overflow: hidden;
}

.ms__operation-fill {
  height: 100%;
  width: 40%;
  background: linear-gradient(90deg, var(--accent), var(--accent-hover));
  border-radius: 1px;
  animation: ms-slide 1.2s ease-in-out infinite;
}

.ms__operation-text {
  font-size: var(--text-xs);
  color: var(--accent);
  text-align: center;
}

@keyframes ms-slide {
  0% {
    transform: translateX(-100%);
  }

  100% {
    transform: translateX(350%);
  }
}

/* ── Section headers ──────────────────────────────────────────── */
.ms__section-head {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-1-5) var(--space-2-5) var(--space-1);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: var(--tracking-normal);
  user-select: none;
}

.ms__section-dot {
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.ms__section-dot--on {
  background: var(--success);
  /* box-shadow: 0 0 4px var(--success-glow); */
}

.ms__section-dot--off {
  background: var(--text-muted);
}

.ms__divider {
  height: 1px;
  background: var(--border);
  margin: var(--space-1) var(--space-2);
}

/* ── Model item ───────────────────────────────────────────────── */
.ms__item {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-2-5) var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  cursor: default;
  transition:
    background var(--transition-fast),
    opacity var(--transition-fast);
}

.ms__item:hover {
  background: var(--surface-hover);
}

.ms__item--loaded {
  background: var(--success-faint);
}

.ms__item--loaded:hover {
  background: var(--success-light);
}

.ms__item--busy {
  animation: ms-pulse 1.5s ease-in-out infinite;
}

@keyframes ms-pulse {
  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.6;
  }
}

/* ── OpenRouter item (selection button + favorite star as siblings) ──── */
.ms__item--or {
  flex-direction: row;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-1) 0 0;
}

.ms__item--active {
  background: var(--surface-selected, var(--surface-2));
}

.ms__item--active:hover {
  background: var(--surface-selected, var(--surface-3));
}

.ms__or-select {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-2-5) var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  font: inherit;
}

.ms__or-id {
  min-width: 0;
  overflow: hidden;
  flex-shrink: 1;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.ms__or-fav {
  flex-shrink: 0;
}

/* ── Accent bar (loaded) ──────────────────────────────────────── */
.ms__accent {
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 2px;
  border-radius: 0 2px 2px 0;
  /* background: var(--success); */
  /* box-shadow: 0 0 6px var(--success-glow); */
}

/* ── Item top row (dot + name + action) ───────────────────────── */
.ms__item-top {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  min-width: 0;
}

.ms__dot {
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.ms__dot--on {
  background: var(--success);
  /* box-shadow: 0 0 4px var(--success-glow); */
}

.ms__dot--off {
  background: var(--text-muted);
}

.ms__name {
  flex: 1;
  font-size: var(--text-base);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

/* ── Action button (load/unload) ──────────────────────────────── */
.ms__action-btn {
  margin-left: auto;
  flex-shrink: 0;
}

/* ── Item meta row (tags + capabilities) ──────────────────────── */
.ms__item-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  padding-left: 11px;
  flex-wrap: wrap;
}

.ms__tag {
  font-size: var(--text-2xs);
  line-height: 1;
  white-space: nowrap;
}

.ms__tag--params {
  color: var(--accent);
  font-weight: var(--weight-semibold);
}

.ms__tag--quant {
  color: var(--text-muted);
  font-family: var(--font-mono);
}

.ms__tag--size {
  color: var(--text-secondary);
}

.ms__tag--ctx {
  color: var(--success);
  font-family: var(--font-mono);
}

/* ── Capability icons ─────────────────────────────────────────── */
.ms__cap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  background: var(--white-faint);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  transition: all var(--transition-fast);
}

.ms__item:hover .ms__cap {
  color: var(--text-secondary);
}

/* ── Loading progress ─────────────────────────────────────────── */
.ms__progress {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--bg-primary);
  overflow: hidden;
}

.ms__progress-bar {
  height: 100%;
  width: 40%;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: ms-slide 1.5s ease-in-out infinite;
}
</style>
