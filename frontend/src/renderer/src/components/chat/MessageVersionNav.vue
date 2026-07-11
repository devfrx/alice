<script setup lang="ts">
/**
 * MessageVersionNav.vue — Arrow navigation for message edit versions.
 *
 * Displays "← 1/3 →" style navigation when a message has multiple versions.
 * Emits version-switch events to update the active version.
 */

const props = defineProps<{
  /** Current active version index (0-based). */
  activeIndex: number
  /** Total number of versions. */
  totalVersions: number
  /** Whether navigation is disabled (e.g. during streaming). */
  disabled?: boolean
}>()

import AppIcon from '../ui/AppIcon.vue'

const emit = defineEmits<{
  switch: [index: number]
}>()

function prev(): void {
  if (!props.disabled && props.activeIndex > 0) {
    emit('switch', props.activeIndex - 1)
  }
}

function next(): void {
  if (!props.disabled && props.activeIndex < props.totalVersions - 1) {
    emit('switch', props.activeIndex + 1)
  }
}
</script>

<template>
  <div
    v-if="totalVersions > 1"
    class="version-nav"
    role="navigation"
    aria-label="Versioni messaggio"
  >
    <button
      class="version-nav__btn"
      :disabled="disabled || activeIndex <= 0"
      aria-label="Versione precedente"
      @click="prev"
    >
      <AppIcon name="chevron-left" :size="12" :stroke-width="2.5" />
    </button>
    <span class="version-nav__label">{{ activeIndex + 1 }} / {{ totalVersions }}</span>
    <button
      class="version-nav__btn"
      :disabled="disabled || activeIndex >= totalVersions - 1"
      aria-label="Versione successiva"
      @click="next"
    >
      <AppIcon name="chevron-right" :size="12" :stroke-width="2.5" />
    </button>
  </div>
</template>

<style scoped>
.version-nav {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin-top: var(--space-1);
}

.version-nav__btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.version-nav__btn:hover:not(:disabled) {
  color: var(--text-primary);
  background: var(--surface-2);
}

.version-nav__btn:disabled {
  opacity: 0.3;
  cursor: default;
}

.version-nav__label {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  font-family: var(--font-mono);
  min-width: 28px;
  text-align: center;
  user-select: none;
}
</style>
