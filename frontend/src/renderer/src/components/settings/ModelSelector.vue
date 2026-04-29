<script setup lang="ts">
/**
 * ModelSelector.vue — Compact dropdown for switching models.
 *
 * Accepts a `modelType` prop ('llm' | 'embedding') to filter which models
 * are shown. Displays the current model name as a small button in the input
 * bar area. On click, opens a dropdown listing models with size, capability
 * badges, load status, and metadata.
 */
import { computed, onBeforeUnmount, onMounted, ref, nextTick, watch } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import type { LMStudioModel } from '../../types/settings'
import AliceSpinner from '../../components/ui/AliceSpinner.vue'
import AppIcon from '../ui/AppIcon.vue'

const props = withDefaults(defineProps<{
  /** Which model type to show: 'llm' (default) or 'embedding'. */
  modelType?: 'llm' | 'embedding'
}>(), { modelType: 'llm' })

const settingsStore = useSettingsStore()

const isOpen = ref(false)
const errorMessage = ref<string | null>(null)
const rootRef = ref<HTMLElement | null>(null)
const dropdownRef = ref<HTMLElement | null>(null)
const searchQuery = ref('')

/** All models for this selector's type. */
const typeModels = computed(() =>
  props.modelType === 'embedding'
    ? settingsStore.embeddingModels
    : settingsStore.llmModels
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
  props.modelType === 'embedding'
    ? settingsStore.activeEmbeddingModel
    : settingsStore.activeModel
)

/** Label shown on the trigger button. */
const triggerLabel = computed(() => {
  if (active.value) return truncateName(active.value.display_name || active.value.name)
  if (props.modelType === 'embedding') return 'Nessun embedding'
  return settingsStore.settings.llm.model
})

function adjustDropdownPosition(): void {
  nextTick(() => {
    const dropdown = dropdownRef.value
    if (!dropdown) return
    dropdown.style.left = '0'
    dropdown.style.right = 'auto'
    const rect = dropdown.getBoundingClientRect()
    if (rect.right > window.innerWidth - 8) {
      dropdown.style.left = 'auto'
      dropdown.style.right = '0'
    }
  })
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    isOpen.value = false
  }
}

function handleResize(): void {
  if (isOpen.value) adjustDropdownPosition()
}

function formatSize(bytes: number): string {
  const gb = bytes / 1_073_741_824
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = bytes / 1_048_576
  return `${mb.toFixed(0)} MB`
}

function truncateName(name: string, maxLen = 24): string {
  return name.length > maxLen ? name.slice(0, maxLen) + '\u2026' : name
}

function toggle(): void {
  if (!isOpen.value && typeModels.value.length === 0) {
    settingsStore.loadModels()
  }
  isOpen.value = !isOpen.value
  errorMessage.value = null
  if (!isOpen.value) searchQuery.value = ''
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
  ) return true
  return false
}

function handleClickOutside(event: MouseEvent): void {
  if (rootRef.value && !rootRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

watch(isOpen, (val) => {
  if (val) {
    adjustDropdownPosition()
    document.addEventListener('keydown', handleKeydown)
  } else {
    document.removeEventListener('keydown', handleKeydown)
  }
})

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
  window.addEventListener('resize', handleResize)
  settingsStore.loadModels()
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleClickOutside)
  window.removeEventListener('resize', handleResize)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div ref="rootRef" class="ms">
    <!-- Trigger button -->
    <button class="ms__trigger" :class="{
      'ms__trigger--embedding': props.modelType === 'embedding',
      'ms__trigger--open': isOpen
    }" aria-haspopup="true" :aria-expanded="isOpen" @click="toggle" @keydown="handleKeydown">
      <!-- Type icon -->
      <AppIcon v-if="props.modelType === 'embedding'" class="ms__type-icon" name="embedding" :size="11"
        title="Embedding model" />
      <!-- Warning icon only when LM Studio is disconnected -->
      <AppIcon v-else-if="!settingsStore.lmStudioConnected" class="ms__warn-icon" name="alert-triangle" :size="11"
        title="LM Studio disconnesso" />
      <span class="ms__label">{{ triggerLabel }}</span>
      <AliceSpinner v-if="settingsStore.isAnyOperationInProgress" size="xs" />
      <AppIcon class="ms__chevron" :class="{ 'ms__chevron--open': isOpen }" name="chevron-down" :size="9"
        :stroke-width="2.5" />
    </button>

    <!-- Dropdown -->
    <Transition name="ms-drop">
      <div v-if="isOpen" ref="dropdownRef" class="ms__dropdown" role="group">
        <!-- Search (only when many models) -->
        <div v-if="showSearch" class="ms__search">
          <AppIcon class="ms__search-icon" name="search" :size="12" />
          <input v-model="searchQuery" class="ms__search-input" type="text" placeholder="Cerca modello…"
            @keydown.stop />
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
            {{ props.modelType === 'embedding' ? 'Nessun modello embedding disponibile' : 'Nessun modello disponibile'
            }}
          </div>

          <!-- No search results -->
          <div v-else-if="loadedModels.length === 0 && availableModels.length === 0 && searchQuery" class="ms__state">
            Nessun risultato per "{{ searchQuery }}"
          </div>

          <template v-else>
            <!-- Loaded models -->
            <template v-if="loadedModels.length > 0">
              <div class="ms__section-head">
                <span class="ms__section-dot ms__section-dot--on" />
                Caricati ({{ loadedModels.length }})
              </div>
              <div v-for="model in loadedModels" :key="'l-' + model.name" class="ms__item ms__item--loaded"
                :class="{ 'ms__item--busy': isModelBusy(model) }"
                :aria-disabled="settingsStore.isAnyOperationInProgress || undefined">
                <span class="ms__accent" />
                <div class="ms__item-top">
                  <span class="ms__dot ms__dot--on" />
                  <span class="ms__name" :title="model.display_name || model.name">
                    {{ model.display_name || model.name }}
                  </span>
                  <button class="ms__action-btn" :class="{ 'ms__action-btn--busy': isModelBusy(model) }"
                    title="Scarica dalla memoria"
                    :disabled="isModelBusy(model) || settingsStore.isAnyOperationInProgress"
                    @click="toggleModelLoad(model, $event)">
                    <AliceSpinner v-if="isModelBusy(model)" size="xs" />
                    <AppIcon v-else name="model-unload" :size="11" />
                  </button>
                </div>
                <div class="ms__item-meta">
                  <span v-if="model.params_string" class="ms__tag ms__tag--params">{{ model.params_string }}</span>
                  <span v-if="model.quantization?.name" class="ms__tag ms__tag--quant">{{ model.quantization.name
                  }}</span>
                  <span class="ms__tag ms__tag--size">{{ formatSize(model.size) }}</span>
                  <span v-if="model.loaded && model.loaded_instances.length > 0" class="ms__tag ms__tag--ctx">
                    ctx {{ model.loaded_instances[0].config.context_length.toLocaleString() }}
                  </span>
                  <span v-if="model.capabilities.vision" class="ms__cap" title="Vision">
                    <AppIcon name="eye" :size="11" />
                  </span>
                  <span v-if="model.capabilities.thinking" class="ms__cap" title="Thinking">
                    <AppIcon name="thinking-cap" :size="11" />
                  </span>
                  <span v-if="model.capabilities.trained_for_tool_use" class="ms__cap" title="Tool Use">
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
            <div v-if="loadedModels.length > 0 && availableModels.length > 0" class="ms__divider" />

            <!-- Available models -->
            <template v-if="availableModels.length > 0">
              <div class="ms__section-head">
                <span class="ms__section-dot ms__section-dot--off" />
                Disponibili ({{ availableModels.length }})
              </div>
              <div v-for="model in availableModels" :key="'a-' + model.name" class="ms__item"
                :class="{ 'ms__item--busy': isModelBusy(model) }"
                :aria-disabled="settingsStore.isAnyOperationInProgress || undefined">
                <div class="ms__item-top">
                  <span class="ms__dot ms__dot--off" />
                  <span class="ms__name" :title="model.display_name || model.name">
                    {{ model.display_name || model.name }}
                  </span>
                  <button class="ms__action-btn" :class="{ 'ms__action-btn--busy': isModelBusy(model) }"
                    title="Carica in memoria" :disabled="isModelBusy(model) || settingsStore.isAnyOperationInProgress"
                    @click="toggleModelLoad(model, $event)">
                    <AliceSpinner v-if="isModelBusy(model)" size="xs" />
                    <AppIcon v-else name="model-load" :size="11" />
                  </button>
                </div>
                <div class="ms__item-meta">
                  <span v-if="model.params_string" class="ms__tag ms__tag--params">{{ model.params_string }}</span>
                  <span v-if="model.quantization?.name" class="ms__tag ms__tag--quant">{{ model.quantization.name
                  }}</span>
                  <span class="ms__tag ms__tag--size">{{ formatSize(model.size) }}</span>
                  <span v-if="model.capabilities.vision" class="ms__cap" title="Vision">
                    <AppIcon name="eye" :size="11" />
                  </span>
                  <span v-if="model.capabilities.thinking" class="ms__cap" title="Thinking">
                    <AppIcon name="thinking-cap" :size="11" />
                  </span>
                  <span v-if="model.capabilities.trained_for_tool_use" class="ms__cap" title="Tool Use">
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
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════════
   ModelSelector — Glassmorphism dropdown coherent with FloatingInputBar
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
  padding: 3px 8px;
  background: var(--white-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--text-xs);
  cursor: pointer;
  white-space: nowrap;
  height: 24px;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.ms__trigger:hover {
  background: var(--white-light);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.ms__trigger--open {
  background: var(--white-medium);
  border-color: var(--accent-border);
  color: var(--text-primary);
}

.ms__trigger--embedding {
  background: var(--white-faint);
}

.ms__trigger--embedding:hover {
  background: var(--white-light);
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

/* ── Dropdown ─────────────────────────────────────────────────── */
.ms__dropdown {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  min-width: 340px;
  max-width: min(440px, calc(100vw - 32px));
  background: var(--surface-2);
  backdrop-filter: blur(var(--glass-blur-heavy));
  -webkit-backdrop-filter: blur(var(--glass-blur-heavy));
  border: 1px solid var(--border-hover);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-floating), inset 0 1px 0 var(--white-subtle);
  z-index: var(--z-dropdown);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Search ───────────────────────────────────────────────────── */
.ms__search {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-2) var(--space-2-5);
  border-bottom: 1px solid var(--border);
}

.ms__search-icon {
  flex-shrink: 0;
  color: var(--text-muted);
}

.ms__search-input {
  flex: 1;
  background: none;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  padding: 0;
}

.ms__search-input::placeholder {
  color: var(--text-muted);
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

/* ── Dropdown transition ──────────────────────────────────────── */
.ms-drop-enter-active,
.ms-drop-leave-active {
  transition:
    opacity 200ms var(--ease-smooth),
    transform 200ms var(--ease-smooth);
}

.ms-drop-enter-from,
.ms-drop-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.97);
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
  background: var(--white-subtle);
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  margin-left: auto;
  flex-shrink: 0;
  background: var(--white-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.ms__action-btn:hover:not(:disabled) {
  background: var(--white-medium);
  border-color: var(--accent-border);
  color: var(--accent);
}

.ms__action-btn:disabled {
  opacity: var(--opacity-soft);
  cursor: not-allowed;
}

.ms__action-btn--busy {
  border-color: var(--accent-border);
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
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  transition: all var(--transition-fast);
}

.ms__item:hover .ms__cap {
  color: var(--text-secondary);
  border-color: var(--border-hover);
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
