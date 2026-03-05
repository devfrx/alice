<script setup lang="ts">
/**
 * ModelSelector.vue — Compact dropdown for switching the active LLM model.
 *
 * Displays the current model name as a small button. On click, opens a
 * dropdown listing all available models with size and capability badges.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useSettingsStore } from '../../stores/settings'

const settingsStore = useSettingsStore()

/** Whether the dropdown is open. */
const isOpen = ref(false)

/** Root element ref for click-outside detection. */
const rootRef = ref<HTMLElement | null>(null)

/** Format bytes to a human-readable size string (e.g. "5.4 GB"). */
function formatSize(bytes: number): string {
  const gb = bytes / 1_073_741_824
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = bytes / 1_048_576
  return `${mb.toFixed(0)} MB`
}

/** Truncate a model name for display. */
function truncateName(name: string, maxLen = 24): string {
  return name.length > maxLen ? name.slice(0, maxLen) + '…' : name
}

/** Toggle the dropdown and fetch models if needed. */
function toggle(): void {
  if (!isOpen.value && settingsStore.models.length === 0) {
    settingsStore.loadModels()
  }
  isOpen.value = !isOpen.value
}

/** Select a model and close the dropdown. */
async function selectModel(name: string): Promise<void> {
  isOpen.value = false
  await settingsStore.switchModel(name)
}

/** Close the dropdown when clicking outside. */
function handleClickOutside(event: MouseEvent): void {
  if (rootRef.value && !rootRef.value.contains(event.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('mousedown', handleClickOutside)
  settingsStore.loadModels()
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', handleClickOutside)
})
</script>

<template>
  <div ref="rootRef" class="model-selector">
    <button class="model-selector__trigger" @click="toggle">
      <span class="model-selector__label">
        {{ settingsStore.activeModel ? truncateName(settingsStore.activeModel.name) : settingsStore.settings.llm.model }}
      </span>
      <svg
        class="model-selector__chevron"
        :class="{ 'model-selector__chevron--open': isOpen }"
        width="10"
        height="10"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>

    <Transition name="dropdown">
      <div v-if="isOpen" class="model-selector__dropdown">
        <!-- Loading state -->
        <div v-if="settingsStore.isLoadingModels" class="model-selector__loading">
          <span class="model-selector__spinner" />
          <span>Caricamento modelli…</span>
        </div>

        <!-- Empty state -->
        <div v-else-if="settingsStore.models.length === 0" class="model-selector__empty">
          Nessun modello disponibile
        </div>

        <!-- Model list -->
        <template v-else>
          <button
            v-for="model in settingsStore.models"
            :key="model.name"
            class="model-selector__item"
            :class="{ 'model-selector__item--active': model.is_active }"
            @click="selectModel(model.name)"
          >
            <span class="model-selector__item-name">{{ truncateName(model.name) }}</span>
            <span class="model-selector__item-meta">
              <span class="model-selector__item-size">{{ formatSize(model.size) }}</span>
              <span v-if="model.capabilities.vision" class="model-selector__badge" title="Vision">🔭</span>
              <span v-if="model.capabilities.thinking" class="model-selector__badge" title="Thinking">💭</span>
            </span>
          </button>
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

/* ── Trigger button ── */
.model-selector__trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 0.8rem;
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

.model-selector__chevron {
  transition: transform var(--transition-fast);
  color: var(--text-secondary);
}

.model-selector__chevron--open {
  transform: rotate(180deg);
}

/* ── Dropdown panel ── */
.model-selector__dropdown {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  min-width: 240px;
  max-height: 300px;
  overflow-y: auto;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  z-index: 100;
  display: flex;
  flex-direction: column;
  padding: 4px;
}

/* ── Transition ── */
.dropdown-enter-active,
.dropdown-leave-active {
  transition:
    opacity var(--transition-fast),
    transform var(--transition-fast);
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

/* ── Loading / empty states ── */
.model-selector__loading,
.model-selector__empty {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 10px;
  color: var(--text-secondary);
  font-size: 0.8rem;
}

.model-selector__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* ── Model item ── */
.model-selector__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 7px 10px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 0.8rem;
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast);
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

/* ── Item parts ── */
.model-selector__item-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-selector__item-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.model-selector__item-size {
  color: var(--text-secondary);
  font-size: 0.7rem;
}

.model-selector__badge {
  font-size: 0.65rem;
  line-height: 1;
}
</style>
