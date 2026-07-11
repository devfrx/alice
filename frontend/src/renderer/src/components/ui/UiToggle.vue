<script setup lang="ts">
/**
 * UiToggle — pill on/off switch. Consolidates the previously duplicated
 * sv__toggle / settings-toggle / ctc__sw / trellis-card__toggle styles.
 *
 * Render modes:
 *   - Bare (no label/hint/#default): renders just the <button role="switch">.
 *     Requires `ariaLabel`. Used inline (ChatToolControls, BrandThemeToggle).
 *   - Row (label/hint/#default present): text block left, switch right; the
 *     whole row is clickable. Used for settings rows.
 *
 * Supports `v-model`. Where toggling has a side effect, bind `:model-value`
 * and handle `@update:model-value` explicitly instead of a bare v-model.
 */
import { computed, useId, useSlots } from 'vue'

export interface UiToggleProps {
  /** Current on/off state. */
  modelValue: boolean
  /** Sizing scale. md = 36×20 (default), sm = compact for dense lists. */
  size?: 'sm' | 'md'
  /** Greys out and blocks activation. */
  disabled?: boolean
  /** Optional label text (row mode). Overridden by the #default slot. */
  label?: string
  /** Optional secondary hint under the label (row mode only). */
  hint?: string
  /** Accessible label — required when used bare (no label/slot). */
  ariaLabel?: string
}

const props = withDefaults(defineProps<UiToggleProps>(), {
  size: 'md',
  disabled: false,
  label: undefined,
  hint: undefined,
  ariaLabel: undefined
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const slots = useSlots()

/** Stable ids for aria-labelledby / aria-describedby in row mode. */
const labelId = useId()
const hintId = useId()

/** True when there is a visible label (prop or slot) to name the switch. */
const hasLabel = computed(() => Boolean(props.label || slots.default))
/** True when there is any text to render → use the row layout. */
const hasText = computed(() => hasLabel.value || Boolean(props.hint))

function toggle(): void {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <div
    v-if="hasText"
    class="ui-toggle-row"
    :class="{ 'ui-toggle-row--disabled': disabled }"
    @click="toggle"
  >
    <div class="ui-toggle-row__text">
      <span v-if="hasLabel" :id="labelId" class="ui-toggle-row__label">
        <slot>{{ label }}</slot>
      </span>
      <span v-if="hint" :id="hintId" class="ui-toggle-row__hint">{{ hint }}</span>
    </div>
    <button
      class="ui-toggle"
      :class="[`ui-toggle--${size}`, { 'ui-toggle--on': modelValue }]"
      type="button"
      role="switch"
      :aria-checked="modelValue"
      :aria-labelledby="hasLabel ? labelId : undefined"
      :aria-label="hasLabel ? undefined : ariaLabel"
      :aria-describedby="hint ? hintId : undefined"
      :disabled="disabled"
      @click.stop="toggle"
    >
      <span class="ui-toggle__thumb" />
    </button>
  </div>
  <button
    v-else
    class="ui-toggle"
    :class="[`ui-toggle--${size}`, { 'ui-toggle--on': modelValue }]"
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="ariaLabel"
    :disabled="disabled"
    @click="toggle"
  >
    <span class="ui-toggle__thumb" />
  </button>
</template>

<style scoped>
/* ── Row layout ───────────────────────── */
.ui-toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  cursor: pointer;
}

.ui-toggle-row--disabled {
  cursor: not-allowed;
  opacity: var(--opacity-disabled);
}

.ui-toggle-row__text {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.ui-toggle-row__label {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
}

.ui-toggle-row__hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

/* ── Switch ───────────────────────────── */
.ui-toggle {
  position: relative;
  border: none;
  border-radius: var(--radius-pill);
  background: var(--surface-3);
  cursor: pointer;
  padding: 0;
  flex-shrink: 0;
  transition: background var(--duration-fast) ease;
}

.ui-toggle:focus-visible {
  outline: 2px solid var(--accent-border);
  outline-offset: 2px;
}

.ui-toggle:disabled {
  cursor: not-allowed;
  opacity: var(--opacity-disabled);
}

.ui-toggle--on {
  background: var(--accent);
}

.ui-toggle__thumb {
  position: absolute;
  border-radius: 50%;
  background: var(--text-primary);
  transition:
    transform var(--duration-fast) ease,
    background var(--duration-fast) ease;
}

.ui-toggle--on .ui-toggle__thumb {
  background: var(--surface-0);
}

/* ── Sizes ────────────────────────────── */
.ui-toggle--md {
  width: 36px;
  height: 20px;
}

.ui-toggle--md .ui-toggle__thumb {
  top: 3px;
  left: 3px;
  width: 14px;
  height: 14px;
}

.ui-toggle--md.ui-toggle--on .ui-toggle__thumb {
  transform: translateX(16px);
}

.ui-toggle--sm {
  width: 30px;
  height: 17px;
}

.ui-toggle--sm .ui-toggle__thumb {
  top: 2.5px;
  left: 2.5px;
  width: 12px;
  height: 12px;
}

.ui-toggle--sm.ui-toggle--on .ui-toggle__thumb {
  transform: translateX(13px);
}
</style>
