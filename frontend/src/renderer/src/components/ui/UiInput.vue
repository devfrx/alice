<script setup lang="ts">
/**
 * UiInput — Text input with proper states, label association, and a11y.
 *
 * Features:
 *  - Real <label for> / <input id> association (id auto-generated via useId).
 *  - aria-invalid + aria-describedby wiring for error / hint messages.
 *  - Prefix / suffix slots (icons, units, inline actions).
 *  - Consistent size scale with UiButton (sm | md | lg).
 *  - Loading state (inline spinner + aria-busy).
 */
import { computed, useId } from 'vue'

export interface UiInputProps {
    /** v-model value. */
    modelValue?: string
    placeholder?: string
    label?: string
    /** Helper text shown below (hidden when `error` is set). */
    hint?: string
    /** Error message — toggles error styling and aria-invalid. */
    error?: string
    disabled?: boolean
    readonly?: boolean
    required?: boolean
    /** Replaces the suffix slot with a spinner and sets aria-busy. */
    loading?: boolean
    /** Shared size scale with UiButton. */
    size?: 'sm' | 'md' | 'lg'
    type?: string
    name?: string
    autocomplete?: string
    maxlength?: number
    /** Override the auto-generated id. */
    id?: string
    /** Accessible label when no visible `label` is provided. */
    ariaLabel?: string
}

const props = withDefaults(defineProps<UiInputProps>(), {
    modelValue: '',
    placeholder: '',
    label: '',
    hint: '',
    error: '',
    disabled: false,
    readonly: false,
    required: false,
    loading: false,
    size: 'md',
    type: 'text',
    name: undefined,
    autocomplete: undefined,
    maxlength: undefined,
    id: undefined,
    ariaLabel: undefined,
})

const emit = defineEmits<{
    'update:modelValue': [value: string]
    focus: [event: FocusEvent]
    blur: [event: FocusEvent]
}>()

const autoId = useId()
const inputId = computed(() => props.id ?? `ui-input-${autoId}`)
const errorId = computed(() => `${inputId.value}-error`)
const hintId = computed(() => `${inputId.value}-hint`)

const describedBy = computed(() => {
    if (props.error) return errorId.value
    if (props.hint) return hintId.value
    return undefined
})

function onInput(e: Event): void {
    emit('update:modelValue', (e.target as HTMLInputElement).value)
}
</script>

<template>
    <div class="ui-input" :class="[
        `ui-input--${size}`,
        { 'ui-input--error': error, 'ui-input--disabled': disabled, 'ui-input--loading': loading },
    ]">
        <label v-if="label" :for="inputId" class="ui-input__label">
            {{ label }}
            <span v-if="required" class="ui-input__required" aria-hidden="true">*</span>
        </label>
        <div class="ui-input__wrapper">
            <span v-if="$slots.prefix" class="ui-input__prefix">
                <slot name="prefix" />
            </span>
            <input :id="inputId" class="ui-input__field" :type="type" :value="modelValue" :placeholder="placeholder"
                :disabled="disabled" :readonly="readonly" :required="required" :name="name"
                :autocomplete="autocomplete" :maxlength="maxlength" :aria-label="ariaLabel || undefined"
                :aria-invalid="!!error || undefined" :aria-describedby="describedBy"
                :aria-busy="loading || undefined" @input="onInput" @focus="emit('focus', $event)"
                @blur="emit('blur', $event)" />
            <span v-if="loading" class="ui-input__spinner" aria-hidden="true" />
            <span v-else-if="$slots.suffix" class="ui-input__suffix">
                <slot name="suffix" />
            </span>
        </div>
        <p v-if="error" :id="errorId" class="ui-input__error" role="alert">{{ error }}</p>
        <p v-else-if="hint" :id="hintId" class="ui-input__hint">{{ hint }}</p>
    </div>
</template>

<style scoped>
.ui-input {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
}

.ui-input__label {
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    color: var(--text-secondary);
    display: inline-flex;
    gap: var(--space-1);
}

.ui-input__required { color: var(--danger); }

.ui-input__wrapper {
    display: flex;
    align-items: center;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    transition:
        background-color var(--duration-fast) var(--ease-out-quart),
        border-color var(--duration-fast) var(--ease-out-quart),
        box-shadow var(--duration-fast) var(--ease-out-quart);
}

.ui-input:not(.ui-input--disabled):not(.ui-input--error) .ui-input__wrapper:hover {
    border-color: var(--border-hover);
}

.ui-input__wrapper:focus-within { box-shadow: var(--shadow-focus); }
.ui-input:not(.ui-input--error) .ui-input__wrapper:focus-within {
    border-color: var(--accent-border);
}

.ui-input__field {
    flex: 1;
    min-width: 0;
    background: transparent;
    border: none;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: inherit;
    outline: none;
    width: 100%;
}

.ui-input__field::placeholder { color: var(--text-muted); }
.ui-input__field:read-only { cursor: default; }

.ui-input__prefix,
.ui-input__suffix,
.ui-input__spinner {
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    flex-shrink: 0;
}

.ui-input__spinner {
    width: 14px;
    height: 14px;
    border: 2px solid transparent;
    border-top-color: currentColor;
    border-radius: var(--radius-full);
    animation: ui-input-spin 0.6s linear infinite;
}

@keyframes ui-input-spin { to { transform: rotate(360deg); } }

/* ── Sizes ──────────── */
.ui-input--sm .ui-input__wrapper { height: var(--input-height-sm); }
.ui-input--sm .ui-input__field   { font-size: var(--text-xs); padding: 0 var(--space-2); }
.ui-input--sm .ui-input__prefix,
.ui-input--sm .ui-input__suffix,
.ui-input--sm .ui-input__spinner { padding: 0 var(--space-1-5); }

.ui-input--md .ui-input__wrapper { height: var(--input-height-md); }
.ui-input--md .ui-input__field   { font-size: var(--text-sm); padding: 0 var(--space-3); }
.ui-input--md .ui-input__prefix,
.ui-input--md .ui-input__suffix,
.ui-input--md .ui-input__spinner { padding: 0 var(--space-2); }

.ui-input--lg .ui-input__wrapper { height: var(--input-height-lg); }
.ui-input--lg .ui-input__field   { font-size: var(--text-md); padding: 0 var(--space-4); }
.ui-input--lg .ui-input__prefix,
.ui-input--lg .ui-input__suffix,
.ui-input--lg .ui-input__spinner { padding: 0 var(--space-3); }

/* ── Error State ───── */
.ui-input--error .ui-input__wrapper { border-color: var(--danger-border); }
.ui-input--error .ui-input__wrapper:focus-within {
    box-shadow: 0 0 0 2px var(--surface-0), 0 0 0 4px var(--danger-border);
}
.ui-input__error { font-size: var(--text-xs); color: var(--danger); }
.ui-input__hint  { font-size: var(--text-xs); color: var(--text-muted); }

/* ── Disabled ──────── */
.ui-input--disabled { opacity: var(--opacity-disabled); pointer-events: none; }
.ui-input--disabled .ui-input__wrapper { background: var(--surface-inset); }
</style>
