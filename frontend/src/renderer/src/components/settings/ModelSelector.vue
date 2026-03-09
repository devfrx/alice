<script setup lang="ts">
/**
 * ModelSelector.vue — Compact dropdown for switching the active LLM model.
 *
 * Displays the current model name as a small button in the input bar area.
 * On click, opens a dropdown listing all available models with size,
 * capability badges, load status, and model metadata.
 */
import { computed, onBeforeUnmount, onMounted, ref, nextTick, watch } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import type { LMStudioModel } from '../../types/settings'

const settingsStore = useSettingsStore()

const isOpen = ref(false)
const switchingModel = ref<string | null>(null)
const errorMessage = ref<string | null>(null)
const rootRef = ref<HTMLElement | null>(null)
const dropdownRef = ref<HTMLElement | null>(null)

const loadedModels = computed(() => settingsStore.models.filter((m) => m.loaded))
const availableModels = computed(() => settingsStore.models.filter((m) => !m.loaded))

function adjustDropdownPosition(): void {
  nextTick(() => {
    const dropdown = dropdownRef.value
    if (!dropdown) return
    // Reset to default position, then measure once
    dropdown.style.left = '0'
    dropdown.style.right = 'auto'
    const rect = dropdown.getBoundingClientRect()
    // If goes off-screen right, flip to right-aligned
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
  if (!isOpen.value && settingsStore.models.length === 0) {
    settingsStore.loadModels()
  }
  isOpen.value = !isOpen.value
  errorMessage.value = null
}

async function selectModel(name: string): Promise<void> {
  switchingModel.value = name
  errorMessage.value = null
  try {
    await settingsStore.switchModel(name)
    isOpen.value = false
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : 'Errore nel cambio modello'
  } finally {
    switchingModel.value = null
  }
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
  if (val) adjustDropdownPosition()
})

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
  window.addEventListener('resize', handleResize)
  settingsStore.loadModels()
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleClickOutside)
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <div ref="rootRef" class="model-selector">
    <!-- Trigger button -->
    <button class="model-selector__trigger" aria-haspopup="listbox" :aria-expanded="isOpen" @click="toggle"
      @keydown="handleKeydown">
      <!-- Warning icon only when LM Studio is disconnected -->
      <svg v-if="!settingsStore.lmStudioConnected" class="model-selector__warn-icon" title="LM Studio disconnesso"
        width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
      <span class="model-selector__label">
        {{
          settingsStore.activeModel
            ? truncateName(settingsStore.activeModel.display_name || settingsStore.activeModel.name)
            : settingsStore.settings.llm.model
        }}
      </span>
      <span v-if="loadedModels.length > 1" class="model-selector__loaded-badge">
        {{ loadedModels.length }} caricati
      </span>
      <span v-if="settingsStore.isAnyOperationInProgress" class="model-selector__trigger-spinner" />
      <svg class="model-selector__chevron" :class="{ 'model-selector__chevron--open': isOpen }" width="10" height="10"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"
        stroke-linejoin="round">
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>

    <!-- Dropdown -->
    <Transition name="dropdown">
      <div v-if="isOpen" ref="dropdownRef" class="model-selector__dropdown" role="listbox">
        <!-- Error -->
        <div v-if="errorMessage" class="model-selector__error">
          {{ errorMessage }}
        </div>

        <!-- Global operation in progress -->
        <div v-if="settingsStore.isAnyOperationInProgress" class="model-selector__operation">
          <div class="model-selector__operation-bar">
            <div class="model-selector__operation-bar-fill" />
          </div>
          <span class="model-selector__operation-text">
            {{ settingsStore.operationDescription }}
          </span>
        </div>

        <!-- Loading state -->
        <div v-if="settingsStore.isLoadingModels" class="model-selector__loading">
          <span class="model-selector__spinner" />
          <span>Caricamento modelli...</span>
        </div>

        <!-- Empty state -->
        <div v-else-if="settingsStore.models.length === 0" class="model-selector__empty">
          Nessun modello disponibile
        </div>

        <!-- Model list -->
        <template v-else>
          <!-- Loaded models section -->
          <template v-if="loadedModels.length > 0">
            <div class="model-selector__section-header">
              <span class="model-selector__section-dot model-selector__section-dot--loaded" />
              Caricati ({{ loadedModels.length }})
            </div>
            <button v-for="model in loadedModels" :key="'loaded-' + model.name" class="model-selector__item" :class="{
              'model-selector__item--active': model.is_active,
              'model-selector__item--loaded': true,
              'model-selector__item--switching': switchingModel === model.name,
              'model-selector__item--busy': isModelBusy(model)
            }" :disabled="switchingModel !== null || settingsStore.isAnyOperationInProgress"
              @click="selectModel(model.name)">
              <!-- Left accent bar for loaded models -->
              <span v-if="model.loaded" class="model-selector__accent-bar" />

              <!-- Main row -->
              <span class="model-selector__item-left">
                <span class="model-selector__load-dot" :class="model.loaded
                  ? 'model-selector__load-dot--loaded'
                  : 'model-selector__load-dot--unloaded'" :title="model.loaded ? 'Caricato' : 'Non caricato'" />
                <span class="model-selector__item-name">
                  {{ truncateName(model.display_name || model.name) }}
                </span>
              </span>

              <!-- Meta info -->
              <span class="model-selector__item-meta">
                <span v-if="model.params_string" class="model-selector__item-params">
                  {{ model.params_string }}
                </span>
                <span v-if="model.quantization?.name" class="model-selector__item-quant">
                  {{ model.quantization.name }}
                </span>
                <span class="model-selector__item-size">{{ formatSize(model.size) }}</span>
                <span v-if="model.loaded && model.loaded_instances.length > 0" class="model-selector__item-ctx">
                  ctx {{ model.loaded_instances[0].config.context_length.toLocaleString() }}
                </span>

                <!-- Capability badges -->
                <span v-if="model.capabilities.vision" class="model-selector__badge" title="Vision">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </span>
                <span v-if="model.capabilities.thinking" class="model-selector__badge" title="Thinking">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 2a7 7 0 0 0-4.6 12.3c.6.5 1 1.2 1.1 2V17h7v-.7c.2-.8.5-1.5 1.1-2A7 7 0 0 0 12 2z" />
                    <path d="M10 21h4" />
                    <path d="M9 17h6" />
                  </svg>
                </span>
                <span v-if="model.capabilities.trained_for_tool_use" class="model-selector__badge" title="Tool Use">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <path
                      d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                  </svg>
                </span>

                <!-- Load / Unload button -->
                <button class="model-selector__load-btn"
                  :class="{ 'model-selector__load-btn--busy': isModelBusy(model) }"
                  :title="model.loaded ? 'Scarica dalla memoria' : 'Carica in memoria'"
                  :disabled="isModelBusy(model) || settingsStore.isAnyOperationInProgress"
                  @click="toggleModelLoad(model, $event)">
                  <!-- Loading spinner -->
                  <span v-if="isModelBusy(model)" class="model-selector__btn-spinner" />
                  <!-- Unload icon (arrow up from tray) -->
                  <svg v-else-if="model.loaded" width="12" height="12" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="17 11 12 6 7 11" />
                    <line x1="12" y1="6" x2="12" y2="18" />
                    <line x1="5" y1="21" x2="19" y2="21" />
                  </svg>
                  <!-- Load icon (arrow down to tray) -->
                  <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="7 13 12 18 17 13" />
                    <line x1="12" y1="18" x2="12" y2="6" />
                    <line x1="5" y1="21" x2="19" y2="21" />
                  </svg>
                </button>
              </span>

              <!-- Switching spinner overlay -->
              <span v-if="switchingModel === model.name" class="model-selector__item-loading">
                <span class="model-selector__spinner model-selector__spinner--small" />
              </span>

              <!-- Loading progress bar -->
              <div v-if="settingsStore.isModelLoading(model.name) && !switchingModel"
                class="model-selector__load-progress">
                <div class="model-selector__load-progress-bar" />
                <span class="model-selector__load-progress-text">Caricamento in corso...</span>
              </div>
            </button>
          </template>

          <!-- Divider between sections -->
          <div v-if="loadedModels.length > 0 && availableModels.length > 0" class="model-selector__section-divider" />

          <!-- Available models section -->
          <template v-if="availableModels.length > 0">
            <div class="model-selector__section-header">
              <span class="model-selector__section-dot model-selector__section-dot--available" />
              Disponibili ({{ availableModels.length }})
            </div>
            <button v-for="model in availableModels" :key="'avail-' + model.name" class="model-selector__item" :class="{
              'model-selector__item--active': model.is_active,
              'model-selector__item--switching': switchingModel === model.name,
              'model-selector__item--busy': isModelBusy(model)
            }" :disabled="switchingModel !== null || settingsStore.isAnyOperationInProgress"
              @click="selectModel(model.name)">
              <span class="model-selector__item-left">
                <span class="model-selector__load-dot model-selector__load-dot--unloaded" title="Non caricato" />
                <span class="model-selector__item-name">
                  {{ truncateName(model.display_name || model.name) }}
                </span>
              </span>
              <span class="model-selector__item-meta">
                <span v-if="model.params_string" class="model-selector__item-params">
                  {{ model.params_string }}
                </span>
                <span v-if="model.quantization?.name" class="model-selector__item-quant">
                  {{ model.quantization.name }}
                </span>
                <span class="model-selector__item-size">{{ formatSize(model.size) }}</span>
                <span v-if="model.capabilities.vision" class="model-selector__badge" title="Vision">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </span>
                <span v-if="model.capabilities.thinking" class="model-selector__badge" title="Thinking">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 2a7 7 0 0 0-4.6 12.3c.6.5 1 1.2 1.1 2V17h7v-.7c.2-.8.5-1.5 1.1-2A7 7 0 0 0 12 2z" />
                    <path d="M10 21h4" />
                    <path d="M9 17h6" />
                  </svg>
                </span>
                <span v-if="model.capabilities.trained_for_tool_use" class="model-selector__badge" title="Tool Use">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <path
                      d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
                  </svg>
                </span>
                <button class="model-selector__load-btn"
                  :class="{ 'model-selector__load-btn--busy': isModelBusy(model) }" title="Carica in memoria"
                  :disabled="isModelBusy(model) || settingsStore.isAnyOperationInProgress"
                  @click="toggleModelLoad(model, $event)">
                  <span v-if="isModelBusy(model)" class="model-selector__btn-spinner" />
                  <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="7 13 12 18 17 13" />
                    <line x1="12" y1="18" x2="12" y2="6" />
                    <line x1="5" y1="21" x2="19" y2="21" />
                  </svg>
                </button>
              </span>
              <span v-if="switchingModel === model.name" class="model-selector__item-loading">
                <span class="model-selector__spinner model-selector__spinner--small" />
              </span>
              <div v-if="settingsStore.isModelLoading(model.name) && !switchingModel"
                class="model-selector__load-progress">
                <div class="model-selector__load-progress-bar" />
                <span class="model-selector__load-progress-text">Caricamento in corso...</span>
              </div>
            </button>
          </template>
        </template>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.model-selector {
  position: relative;
  display: inline-flex;
}

/* ── Trigger button ───────────────────────────────────────────────── */
.model-selector__trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: var(--space-1) var(--space-2-5);
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast);
  white-space: nowrap;
}

.model-selector__trigger:hover {
  background: var(--bg-secondary);
  border-color: var(--border-hover);
}

.model-selector__warn-icon {
  flex-shrink: 0;
  color: var(--danger);
  animation: msWarnBlink 2s ease-in-out infinite;
}

@keyframes msWarnBlink {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.4;
  }
}

.model-selector__label {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-selector__chevron {
  transition: transform var(--transition-fast);
  color: var(--text-secondary);
}

.model-selector__chevron--open {
  transform: rotate(180deg);
}

.model-selector__loaded-badge {
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  padding: var(--space-px) 5px;
  background: var(--success-medium);
  color: var(--success);
  border: 1px solid var(--success-border);
  border-radius: var(--radius-pill);
  white-space: nowrap;
  line-height: var(--leading-tight);
}

/* ── Section headers & divider ────────────────────────────────────── */
.model-selector__section-header {
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

.model-selector__section-dot {
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.model-selector__section-dot--loaded {
  background: var(--success);
  box-shadow: 0 0 4px var(--success-glow);
}

.model-selector__section-dot--available {
  background: var(--text-muted);
}

.model-selector__section-divider {
  height: var(--space-px);
  background: var(--border);
  margin: var(--space-1) var(--space-2);
}

/* ── Dropdown panel ───────────────────────────────────────────────── */
.model-selector__dropdown {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  min-width: 380px;
  max-width: min(480px, calc(100vw - 32px));
  max-height: 360px;
  overflow-y: auto;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-dropdown);
  z-index: var(--z-dropdown);
  display: flex;
  flex-direction: column;
  padding: var(--space-1);
}

/* Scrollbar */
.model-selector__dropdown::-webkit-scrollbar {
  width: var(--space-1);
}

.model-selector__dropdown::-webkit-scrollbar-track {
  background: transparent;
}

.model-selector__dropdown::-webkit-scrollbar-thumb {
  background: var(--border-hover);
  border-radius: var(--space-0-5);
}

/* ── Dropdown transition ──────────────────────────────────────────── */
.dropdown-enter-active,
.dropdown-leave-active {
  transition:
    opacity var(--transition-normal),
    transform var(--transition-normal);
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

/* ── Model list transitions ───────────────────────────────────────── */
.model-list-enter-active,
.model-list-leave-active {
  transition: all var(--transition-normal);
}

.model-list-enter-from {
  opacity: 0;
  transform: translateX(-8px);
}

.model-list-leave-to {
  opacity: 0;
  transform: translateX(8px);
}

.model-list-move {
  transition: transform var(--transition-normal);
}

/* ── Error state ──────────────────────────────────────────────────── */
.model-selector__error {
  padding: var(--space-2) var(--space-2-5);
  color: var(--danger);
  font-size: 0.75rem;
  background: var(--danger-light);
  border: 1px solid var(--danger-hover);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-1);
}

/* ── Loading / empty states ───────────────────────────────────────── */
.model-selector__loading,
.model-selector__empty {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 14px 12px;
  color: var(--text-secondary);
  font-size: var(--text-base);
}

.model-selector__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: var(--radius-full);
  animation: ms-spin 0.6s linear infinite;
  flex-shrink: 0;
}

.model-selector__spinner--small {
  width: 10px;
  height: 10px;
  border-width: 1.5px;
}

.model-selector__trigger-spinner {
  width: 10px;
  height: 10px;
  border: 1.5px solid var(--border);
  border-top-color: var(--accent);
  border-radius: var(--radius-full);
  animation: ms-spin 0.6s linear infinite;
  flex-shrink: 0;
}

@keyframes ms-spin {
  to {
    transform: rotate(360deg);
  }
}

/* ── Model item ───────────────────────────────────────────────────── */
.model-selector__item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-2-5) var(--space-2) var(--space-3);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  cursor: pointer;
  text-align: left;
  overflow: hidden;
  transition:
    background var(--transition-fast),
    opacity var(--transition-fast),
    transform var(--transition-fast);
}

.model-selector__item:hover {
  background: var(--bg-tertiary);
}

.model-selector__item--active {
  background: var(--accent-dim);
  color: var(--accent);
}

.model-selector__item--active:hover {
  background: var(--accent-dim);
}

.model-selector__item--loaded {
  background: var(--success-faint);
}

.model-selector__item--switching {
  opacity: var(--opacity-dim);
  pointer-events: none;
  animation: msSwitching 1s ease-in-out infinite;
}

@keyframes msSwitching {

  0%,
  100% {
    opacity: 0.5;
  }

  50% {
    opacity: 0.3;
  }
}

.model-selector__item--busy {
  animation: ms-pulse 1.5s ease-in-out infinite;
}

.model-selector__item:disabled {
  cursor: not-allowed;
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

/* ── Left accent bar for loaded models ────────────────────────────── */
.model-selector__accent-bar {
  position: absolute;
  left: 0;
  top: 3px;
  bottom: 3px;
  width: 3px;
  border-radius: 0 2px 2px 0;
  background: var(--success);
  box-shadow: 0 0 6px var(--success-glow);
  transition: opacity var(--transition-fast);
}

/* ── Load dot indicator ───────────────────────────────────────────── */
.model-selector__load-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.model-selector__load-dot--loaded {
  background: var(--success);
  box-shadow: 0 0 4px var(--success-glow);
}

.model-selector__load-dot--unloaded {
  background: var(--text-muted);
}

/* ── Item parts ───────────────────────────────────────────────────── */
.model-selector__item-left {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  flex: 1;
  min-width: 0;
}

.model-selector__item-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: var(--weight-medium);
}

.model-selector__item-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}

.model-selector__item-params {
  color: var(--accent);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
}

.model-selector__item-quant {
  color: var(--text-muted);
  font-size: var(--text-2xs);
  font-family: var(--font-mono);
}

.model-selector__item-size {
  color: var(--text-secondary);
  font-size: var(--text-xs);
}

.model-selector__item-ctx {
  color: var(--success);
  font-size: var(--text-2xs);
  font-family: var(--font-mono);
}

/* ── Capability badges ────────────────────────────────────────────── */
.model-selector__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: var(--space-1);
  background: var(--white-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
  font-size: var(--text-2xs);
  line-height: 1;
  white-space: nowrap;
  transition: all var(--transition-fast);
}

.model-selector__badge svg {
  flex-shrink: 0;
  opacity: var(--opacity-visible);
}

.model-selector__badge-label {
  font-size: 0.55rem;
  font-weight: var(--weight-medium);
  text-transform: uppercase;
  letter-spacing: var(--tracking-tight);
}

.model-selector__item--active .model-selector__badge {
  color: var(--accent);
  border-color: var(--accent-border);
  background: var(--accent-dim);
}

/* ── Load / Unload button ─────────────────────────────────────────── */
.model-selector__load-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  padding: 0;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.model-selector__load-btn:hover:not(:disabled) {
  background: var(--bg-primary);
  border-color: var(--accent-border);
  color: var(--accent);
}

.model-selector__load-btn:disabled {
  opacity: var(--opacity-soft);
  cursor: not-allowed;
}

.model-selector__load-btn--busy {
  border-color: var(--accent-border);
}

/* Inline spinner inside the load button */
.model-selector__btn-spinner {
  width: 10px;
  height: 10px;
  border: 1.5px solid var(--border);
  border-top-color: var(--accent);
  border-radius: var(--radius-full);
  animation: ms-spin 0.6s linear infinite;
}

/* ── Switching overlay spinner ────────────────────────────────────── */
.model-selector__item-loading {
  display: flex;
  align-items: center;
  margin-left: var(--space-1);
}

/* ── Loading progress bar ─────────────────────────────────────────── */
.model-selector__load-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: var(--space-0-5);
  background: var(--bg-primary);
  overflow: hidden;
}

.model-selector__load-progress-bar {
  height: 100%;
  width: 40%;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: msLoadSlide 1.5s ease-in-out infinite;
}

@keyframes msLoadSlide {
  0% {
    transform: translateX(-100%);
  }

  100% {
    transform: translateX(350%);
  }
}

.model-selector__load-progress-text {
  display: none;
}

/* ── Global operation progress ────────────────────────────────────── */
.model-selector__operation {
  padding: var(--space-2) var(--space-2-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.model-selector__operation-bar {
  height: 3px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
}

.model-selector__operation-bar-fill {
  height: 100%;
  width: 40%;
  background: linear-gradient(90deg, var(--accent), var(--accent-hover));
  border-radius: 2px;
  animation: msOpProgress 1.2s ease-in-out infinite;
}

@keyframes msOpProgress {
  0% {
    transform: translateX(-100%);
  }

  100% {
    transform: translateX(350%);
  }
}

.model-selector__operation-text {
  font-size: var(--text-xs);
  color: var(--accent);
  text-align: center;
}
</style>
