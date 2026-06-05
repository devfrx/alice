<script setup lang="ts">
/**
 * ModulePanel — Floating-card chrome for a single workspace module.
 *
 * Provides the shared header (icon + title + actions + close) and a body
 * slot. Uses NEW panel token names with fallbacks so it renders correctly
 * before Task T12 introduces them.
 */
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import type { AppIconName } from '../../assets/icons'

withDefaults(
  defineProps<{
    /** Title shown in the header. */
    title: string
    /** Optional leading icon. */
    icon?: AppIconName
    /** Whether to show the close button. */
    closable?: boolean
    /** Highlights the panel as the active leaf. */
    active?: boolean
  }>(),
  { icon: undefined, closable: true, active: false }
)

const emit = defineEmits<{
  close: []
}>()
</script>

<template>
  <div class="module-panel" :class="{ 'module-panel--active': active }">
    <header class="module-panel__header">
      <AppIcon v-if="icon" :name="icon" :size="14" class="module-panel__icon" />
      <span class="module-panel__title">{{ title }}</span>
      <div class="module-panel__actions">
        <slot name="actions" />
      </div>
      <UiIconButton
        v-if="closable"
        label="Chiudi modulo"
        size="xs"
        variant="ghost"
        class="module-panel__close"
        @click="emit('close')"
      >
        <AppIcon name="x" :size="12" />
      </UiIconButton>
    </header>
    <div class="module-panel__body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.module-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  border-radius: var(--panel-radius, var(--radius-md));
  box-shadow: var(--panel-shadow, var(--shadow-floating));
  background: var(--surface-1);
  border: 1px solid var(--border);
  overflow: hidden;
}

.module-panel--active {
  border-color: var(--accent-border);
}

.module-panel__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: var(--panel-header-height, 30px);
  flex-shrink: 0;
  padding: 0 var(--space-2);
  border-bottom: 1px solid var(--border);
  background: var(--surface-2, var(--surface-1));
}

.module-panel__icon {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.module-panel__title {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.module-panel__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin-left: auto;
}

.module-panel__close {
  flex-shrink: 0;
}

.module-panel__body {
  flex: 1;
  overflow: hidden;
  min-height: 0;
}
</style>
