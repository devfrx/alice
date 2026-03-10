<script setup lang="ts">
/**
 * UiInput — Text input with proper states, labels, and feedback.
 *
 * Features: floating label, prefix/suffix slots, error state, focus ring.
 */

export interface UiInputProps {
    modelValue?: string
    placeholder?: string
    label?: string
    error?: string
    disabled?: boolean
    size?: 'sm' | 'md' | 'lg'
    type?: string
}

withDefaults(defineProps<UiInputProps>(), {
    modelValue: '',
    placeholder: '',
    label: '',
    error: '',
    disabled: false,
    size: 'md',
    type: 'text',
})

const emit = defineEmits<{
    'update:modelValue': [value: string]
}>()

function onInput(e: Event) {
    emit('update:modelValue', (e.target as HTMLInputElement).value)
}
</script>

<template>
    <div class="ui-input" :class="[`ui-input--${size}`, { 'ui-input--error': error, 'ui-input--disabled': disabled }]">
        <label v-if="label" class="ui-input__label">{{ label }}</label>
        <div class="ui-input__wrapper">
            <span v-if="$slots.prefix" class="ui-input__prefix">
                <slot name="prefix" />
            </span>
            <input class="ui-input__field" :type="type" :value="modelValue" :placeholder="placeholder"
                :disabled="disabled" @input="onInput" />
            <span v-if="$slots.suffix" class="ui-input__suffix">
                <slot name="suffix" />
            </span>
        </div>
        <p v-if="error" class="ui-input__error">{{ error }}</p>
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
    letter-spacing: var(--tracking-normal);
    text-transform: uppercase;
}

.ui-input__wrapper {
    display: flex;
    align-items: center;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    transition:
        border-color 150ms ease,
        box-shadow 150ms ease,
        background-color 150ms ease;
}

.ui-input__wrapper:hover:not(.ui-input--disabled .ui-input__wrapper) {
    border-color: var(--border-hover);
}

.ui-input__wrapper:focus-within {
    border-color: var(--accent-border);
    box-shadow: 0 0 0 3px rgba(201, 168, 76, 0.08);
    background: var(--surface-0);
}

.ui-input__field {
    flex: 1;
    background: transparent;
    border: none;
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: inherit;
    outline: none;
    width: 100%;
}

.ui-input__field::placeholder {
    color: var(--text-muted);
}

.ui-input__prefix,
.ui-input__suffix {
    display: flex;
    align-items: center;
    color: var(--text-muted);
    flex-shrink: 0;
}

/* ── Sizes ──────────── */
.ui-input--sm .ui-input__wrapper {
    height: var(--input-height-sm);
}

.ui-input--sm .ui-input__field {
    font-size: var(--text-xs);
    padding: 0 var(--space-2);
}

.ui-input--sm .ui-input__prefix,
.ui-input--sm .ui-input__suffix {
    padding: 0 var(--space-1-5);
}

.ui-input--md .ui-input__wrapper {
    height: var(--input-height-md);
}

.ui-input--md .ui-input__field {
    font-size: var(--text-sm);
    padding: 0 var(--space-3);
}

.ui-input--md .ui-input__prefix,
.ui-input--md .ui-input__suffix {
    padding: 0 var(--space-2);
}

.ui-input--lg .ui-input__wrapper {
    height: var(--input-height-lg);
}

.ui-input--lg .ui-input__field {
    font-size: var(--text-md);
    padding: 0 var(--space-4);
}

.ui-input--lg .ui-input__prefix,
.ui-input--lg .ui-input__suffix {
    padding: 0 var(--space-3);
}

/* ── Error State ───── */
.ui-input--error .ui-input__wrapper {
    border-color: var(--danger-border);
}

.ui-input--error .ui-input__wrapper:focus-within {
    box-shadow: 0 0 0 3px rgba(196, 92, 92, 0.1);
}

.ui-input__error {
    font-size: var(--text-xs);
    color: var(--danger);
}

/* ── Disabled ──────── */
.ui-input--disabled {
    opacity: var(--opacity-disabled);
    pointer-events: none;
}
</style>
