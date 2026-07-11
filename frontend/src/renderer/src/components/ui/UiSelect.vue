<script setup lang="ts">
/**
 * UiSelect — Custom listbox select built on {@link UiPopover}.
 *
 * A token-styled replacement for native `<select>`: a chip-like trigger
 * showing the current label (or placeholder) and a teleported listbox menu
 * that adopts the unified floating recipe. Fully keyboard- and
 * screen-reader-accessible (`listbox` / `option`, `aria-activedescendant`).
 *
 * @example
 *   <UiSelect
 *     v-model="lang"
 *     :options="[{ value: 'it', label: 'Italiano' }, { value: 'en', label: 'English' }]"
 *     placeholder="Lingua…"
 *   />
 */
import { computed, nextTick, ref, useId, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import UiPopover from './UiPopover.vue'

export interface UiSelectOption {
  value: string | number
  label: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    /** Selected option value (`null` when nothing is chosen). */
    modelValue: string | number | null
    /** Selectable options. */
    options: UiSelectOption[]
    /** Text shown when no option is selected. */
    placeholder?: string
    /** Disable the whole control. */
    disabled?: boolean
    /** Density; default `'sm'`. */
    size?: 'sm' | 'md'
    /** Accessible label for the trigger + listbox. */
    ariaLabel?: string
  }>(),
  {
    placeholder: 'Seleziona…',
    disabled: false,
    size: 'sm',
    ariaLabel: undefined
  }
)

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
}>()

const isOpen = ref(false)
const triggerRef = ref<HTMLButtonElement | null>(null)
/** Index of the keyboard-highlighted option (-1 when none). */
const activeIndex = ref(-1)

/** Stable id base for `aria-activedescendant` wiring. */
const baseId = useId()
const listboxId = `${baseId}-listbox`
const optionId = (index: number): string => `${baseId}-opt-${index}`

const selectedOption = computed(
  () => props.options.find((o) => o.value === props.modelValue) ?? null
)

const triggerLabel = computed(() => selectedOption.value?.label ?? props.placeholder)
const hasSelection = computed(() => selectedOption.value !== null)

/** First non-disabled option index, or -1. */
function firstEnabledIndex(): number {
  return props.options.findIndex((o) => !o.disabled)
}

/** Last non-disabled option index, or -1. */
function lastEnabledIndex(): number {
  for (let i = props.options.length - 1; i >= 0; i--) {
    if (!props.options[i]!.disabled) return i
  }
  return -1
}

/**
 * Find the next selectable option index from `start` walking by `step`,
 * wrapping around the list. Returns -1 if every option is disabled.
 */
function nextEnabledIndex(start: number, step: 1 | -1): number {
  const len = props.options.length
  if (len === 0) return -1
  for (let i = 1; i <= len; i++) {
    const idx = (start + step * i + len * i) % len
    if (!props.options[idx]!.disabled) return idx
  }
  return -1
}

function open(): void {
  if (props.disabled || isOpen.value) return
  isOpen.value = true
  // Highlight the current selection, else the first selectable option.
  const selectedIdx = props.options.findIndex((o) => o.value === props.modelValue)
  activeIndex.value =
    selectedIdx >= 0 && !props.options[selectedIdx]!.disabled ? selectedIdx : firstEnabledIndex()
}

function close(focusTrigger = false): void {
  if (!isOpen.value) return
  isOpen.value = false
  activeIndex.value = -1
  if (focusTrigger) nextTick(() => triggerRef.value?.focus())
}

function toggle(): void {
  if (isOpen.value) close()
  else open()
}

function selectOption(option: UiSelectOption): void {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  close(true)
}

function selectActive(): void {
  const option = props.options[activeIndex.value]
  if (option) selectOption(option)
}

/** Keyboard handling on the trigger button. */
function onTriggerKeydown(event: KeyboardEvent): void {
  if (props.disabled) return

  if (!isOpen.value) {
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowDown') {
      event.preventDefault()
      open()
    }
    return
  }

  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      activeIndex.value = nextEnabledIndex(activeIndex.value, 1)
      break
    case 'ArrowUp':
      event.preventDefault()
      activeIndex.value = nextEnabledIndex(activeIndex.value, -1)
      break
    case 'Home':
      event.preventDefault()
      activeIndex.value = firstEnabledIndex()
      break
    case 'End':
      event.preventDefault()
      activeIndex.value = lastEnabledIndex()
      break
    case 'Enter':
    case ' ':
      event.preventDefault()
      selectActive()
      break
    case 'Escape':
      event.preventDefault()
      close(true)
      break
    case 'Tab':
      // Let focus leave naturally, but close the menu.
      close()
      break
    default:
      break
  }
}

// Keep the highlight valid if the options list changes while open.
watch(
  () => props.options,
  () => {
    if (isOpen.value && (activeIndex.value < 0 || props.options[activeIndex.value]?.disabled)) {
      activeIndex.value = firstEnabledIndex()
    }
  }
)

// Scroll the highlighted option into view. Focus stays on the trigger
// (aria-activedescendant pattern), so the list won't auto-scroll on its own.
// The list is teleported to <body>, so resolve the element by id.
watch(activeIndex, (index) => {
  if (!isOpen.value || index < 0) return
  nextTick(() => {
    document.getElementById(optionId(index))?.scrollIntoView({ block: 'nearest' })
  })
})
</script>

<template>
  <div class="ui-select" :class="`ui-select--${size}`">
    <button
      ref="triggerRef"
      type="button"
      class="ui-select__trigger"
      :class="{
        'ui-select__trigger--open': isOpen,
        'ui-select__trigger--placeholder': !hasSelection
      }"
      :disabled="disabled"
      role="combobox"
      aria-haspopup="listbox"
      :aria-expanded="isOpen"
      :aria-controls="listboxId"
      :aria-label="ariaLabel"
      :aria-activedescendant="isOpen && activeIndex >= 0 ? optionId(activeIndex) : undefined"
      @click="toggle"
      @keydown="onTriggerKeydown"
    >
      <span class="ui-select__label">{{ triggerLabel }}</span>
      <AppIcon
        class="ui-select__chevron"
        :class="{ 'ui-select__chevron--open': isOpen }"
        name="chevron-down"
        :size="size === 'md' ? 12 : 10"
      />
    </button>

    <UiPopover
      :open="isOpen"
      :anchor-el="triggerRef"
      placement="bottom"
      align="start"
      match-width
      :aria-label="ariaLabel"
      panel-class="ui-select__popover"
      @update:open="isOpen = $event"
    >
      <ul :id="listboxId" class="ui-select__list" role="listbox" :aria-label="ariaLabel">
        <li
          v-for="(option, index) in options"
          :id="optionId(index)"
          :key="option.value"
          class="ui-select__option"
          :class="{
            'ui-select__option--active': index === activeIndex,
            'ui-select__option--selected': option.value === modelValue,
            'ui-select__option--disabled': option.disabled
          }"
          role="option"
          :aria-selected="option.value === modelValue"
          :aria-disabled="option.disabled || undefined"
          @click="selectOption(option)"
          @mousemove="!option.disabled && (activeIndex = index)"
        >
          <span class="ui-select__option-label">{{ option.label }}</span>
          <AppIcon
            v-if="option.value === modelValue"
            class="ui-select__check"
            name="check"
            :size="13"
          />
        </li>
        <li v-if="options.length === 0" class="ui-select__empty" role="presentation">
          Nessuna opzione
        </li>
      </ul>
    </UiPopover>
  </div>
</template>

<style scoped>
.ui-select {
  display: inline-flex;
  position: relative;
}

/* ── Trigger (chip-like control) ── */
.ui-select__trigger {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-1-5);
  width: 100%;
  height: var(--input-height-sm);
  padding: 0 var(--space-2);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
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

.ui-select--md .ui-select__trigger {
  height: var(--input-height-md, 34px);
  font-size: var(--text-sm);
  padding: 0 var(--space-2-5);
}

.ui-select__trigger:hover:not(:disabled) {
  background: var(--surface-3);
  border-color: var(--border-hover);
}

.ui-select__trigger--open {
  background: var(--surface-3);
  border-color: var(--accent-border);
}

.ui-select__trigger:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--focus-ring-color);
}

.ui-select__trigger:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

.ui-select__trigger--placeholder .ui-select__label {
  color: var(--text-muted);
}

.ui-select__label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: left;
}

.ui-select__chevron {
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform var(--duration-fast) ease;
}

.ui-select__chevron--open {
  transform: rotate(180deg);
}

/* ── Listbox ── */
.ui-select__list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: min(320px, 50vh);
  overflow-y: auto;
}

.ui-select__option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1-5) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--text-primary);
  cursor: pointer;
  user-select: none;
}

.ui-select--md .ui-select__option {
  font-size: var(--text-sm);
}

.ui-select__option--active {
  background: var(--surface-hover);
}

.ui-select__option--selected {
  background: var(--surface-selected);
  color: var(--accent);
  font-weight: var(--weight-semibold);
}

.ui-select__option--selected.ui-select__option--active {
  background: var(--surface-selected);
}

.ui-select__option--disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

.ui-select__option-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ui-select__check {
  flex-shrink: 0;
  color: var(--accent);
}

.ui-select__empty {
  padding: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-align: center;
}
</style>
