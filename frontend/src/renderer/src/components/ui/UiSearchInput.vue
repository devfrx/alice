<script setup lang="ts">
/**
 * UiSearchInput — Standard search field: leading lens, clear affordance,
 * Esc clears. Thin wrapper over UiInput so states/a11y stay in one place.
 */
import UiInput from './UiInput.vue'
import AppIcon from './AppIcon.vue'

export interface UiSearchInputProps {
  modelValue?: string
  placeholder?: string
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  /** Accessible label (there is usually no visible label on search fields). */
  ariaLabel?: string
  clearLabel?: string
}

const props = withDefaults(defineProps<UiSearchInputProps>(), {
  modelValue: '',
  placeholder: 'Cerca…',
  size: 'sm',
  disabled: false,
  ariaLabel: 'Cerca',
  clearLabel: 'Svuota ricerca'
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  clear: []
}>()

function clear(): void {
  if (!props.modelValue) return
  emit('update:modelValue', '')
  emit('clear')
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && props.modelValue) {
    // Chromium clears input[type=search] natively on Escape (even with the
    // cancel button hidden) — prevent it so clear() emits exactly once.
    e.preventDefault()
    e.stopPropagation()
    clear()
  }
}
</script>

<template>
  <UiInput
    class="ui-search"
    :model-value="modelValue"
    :placeholder="placeholder"
    :size="size"
    :disabled="disabled"
    :aria-label="ariaLabel"
    type="search"
    @update:model-value="emit('update:modelValue', $event)"
    @keydown="onKeydown"
  >
    <template #prefix>
      <AppIcon name="search" :size="14" />
    </template>
    <template #suffix>
      <button
        v-if="modelValue"
        type="button"
        class="ui-search__clear"
        :aria-label="clearLabel"
        @click="clear"
      >
        <AppIcon name="x" :size="12" />
      </button>
    </template>
  </UiInput>
</template>

<style scoped>
.ui-search__clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-0-5);
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    color var(--duration-fast) var(--ease-out-quart),
    background-color var(--duration-fast) var(--ease-out-quart);
}

.ui-search__clear:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}
</style>
