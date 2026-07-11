<script setup lang="ts">
/**
 * UiChip — Interactive chip (filter, selectable tag, removable token).
 *
 * UiBadge is for non-interactive status; UiChip is a real <button>:
 * hover / active / selected / focus-visible / disabled states,
 * optional remove affordance (click on ✕ or Delete/Backspace key).
 */
export interface UiChipProps {
  /** Selected/pressed state (aria-pressed). */
  selected?: boolean
  disabled?: boolean
  /** Show a trailing ✕ and emit `remove`. */
  removable?: boolean
  size?: 'sm' | 'md'
  /** Accessible label for the remove affordance. */
  removeLabel?: string
}

const props = withDefaults(defineProps<UiChipProps>(), {
  selected: false,
  disabled: false,
  removable: false,
  size: 'sm',
  removeLabel: 'Rimuovi'
})

const emit = defineEmits<{
  click: [event: MouseEvent]
  remove: [event: Event]
}>()

function onKeydown(e: KeyboardEvent): void {
  if (props.removable && (e.key === 'Delete' || e.key === 'Backspace')) {
    e.preventDefault()
    emit('remove', e)
  }
}
</script>

<template>
  <button
    type="button"
    class="ui-chip"
    :class="[`ui-chip--${size}`, { 'ui-chip--selected': selected }]"
    :disabled="disabled"
    :aria-pressed="selected || undefined"
    @click="emit('click', $event)"
    @keydown="onKeydown"
  >
    <span v-if="$slots.icon" class="ui-chip__icon" aria-hidden="true">
      <slot name="icon" />
    </span>
    <span class="ui-chip__label"><slot /></span>
    <!-- span aria-hidden, non button: un button annidato in un button è HTML
         invalido. Da tastiera la rimozione passa per Delete/Backspace sul chip
         (onKeydown sopra); `removeLabel` resta per screen reader via title. -->
    <span
      v-if="removable"
      class="ui-chip__remove"
      :title="removeLabel"
      aria-hidden="true"
      @click.stop="emit('remove', $event)"
    >
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
        <path
          d="M2 2 L8 8 M8 2 L2 8"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linecap="round"
        />
      </svg>
    </span>
  </button>
</template>

<style scoped>
.ui-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-weight: var(--weight-medium);
  white-space: nowrap;
  cursor: pointer;
  max-width: 100%;
  transition:
    background-color var(--duration-fast) var(--ease-out-quart),
    border-color var(--duration-fast) var(--ease-out-quart),
    color var(--duration-fast) var(--ease-out-quart);
}

.ui-chip:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.ui-chip:active:not(:disabled) {
  background: var(--surface-active);
}

.ui-chip:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
  pointer-events: none;
}

.ui-chip--selected {
  background: var(--accent-dim);
  border-color: var(--accent-border);
  color: var(--accent);
}

.ui-chip--selected:hover:not(:disabled) {
  background: var(--accent-light);
  color: var(--accent);
}

/* ── Sizes ────── */
.ui-chip--sm {
  padding: var(--space-0-5) var(--space-2);
  font-size: var(--text-2xs);
}

.ui-chip--md {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
}

.ui-chip__label {
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.ui-chip__icon {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.ui-chip__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  margin-inline-start: var(--space-0-5);
  border-radius: var(--radius-full);
  color: inherit;
  opacity: var(--opacity-medium);
  flex-shrink: 0;
  transition:
    background-color var(--duration-fast) var(--ease-out-quart),
    opacity var(--duration-fast) var(--ease-out-quart);
}

.ui-chip__remove:hover {
  background: var(--surface-hover);
  opacity: 1;
}
</style>
