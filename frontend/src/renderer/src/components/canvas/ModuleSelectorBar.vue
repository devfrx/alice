<script setup lang="ts">
/**
 * ModuleSelectorBar — slim "pick which item" bar for multi-item workspace tiles.
 *
 * Sits at the top of a module body (ChartModule / WhiteboardModule / Cad3dModule)
 * and lets the user switch between the charts / whiteboards / 3D models present
 * in the conversation. It is a thin wrapper around the shared {@link UiSegmented}
 * tab control (same sliding-indicator motion used everywhere else), so the three
 * modules stay perfectly consistent.
 *
 * Renders nothing when there is one item or fewer — a selector for a single
 * item would be noise. Overflows horizontally (scroll) when many long-titled
 * items don't fit the narrow panel.
 */
import UiSegmented, { type UiSegmentedOption } from '../ui/UiSegmented.vue'

defineProps<{
  /** Currently displayed item id (null = none). */
  modelValue: string | null
  /** One option per available item. */
  options: UiSegmentedOption[]
  /** Accessible label for the control. */
  ariaLabel?: string
}>()

defineEmits<{
  'update:modelValue': [value: string | number]
}>()
</script>

<template>
  <div v-if="options.length > 1" class="module-selector">
    <UiSegmented
      class="module-selector__seg"
      size="sm"
      :equal="false"
      :model-value="modelValue"
      :options="options"
      :aria-label="ariaLabel ?? 'Seleziona elemento'"
      @update:model-value="$emit('update:modelValue', $event)"
    />
  </div>
</template>

<style scoped>
.module-selector {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  padding: 0 var(--space-2) var(--space-1-5);
  /* Flush with the panel header surface — minimal chrome, no separators. */
  background: var(--surface-1);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}

.module-selector__seg {
  min-width: min-content;
}

/* Cap tab width so long titles truncate instead of stretching the bar. */
.module-selector :deep(.ui-seg__label) {
  max-width: 140px;
}
</style>
