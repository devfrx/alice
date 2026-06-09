<script setup lang="ts">
/**
 * UiCheckbox — accessible checkbox built on a visually-hidden native input,
 * replacing ad-hoc <input type="checkbox"> usages. Supports v-model.
 */
import { onMounted, ref, watch } from 'vue'

import AppIcon from './AppIcon.vue'

export interface UiCheckboxProps {
    /** Checked state. */
    modelValue: boolean
    /** Sizing scale — md (default) or sm. */
    size?: 'sm' | 'md'
    /** Greys out and blocks activation. */
    disabled?: boolean
    /** Optional label text. Overridden by the #default slot. */
    label?: string
    /** Renders the mixed (dash) state; sets the native input's indeterminate flag. */
    indeterminate?: boolean
    /** Accessible label — required when no label/slot is provided. */
    ariaLabel?: string
}

const props = withDefaults(defineProps<UiCheckboxProps>(), {
    size: 'md',
    disabled: false,
    label: undefined,
    indeterminate: false,
    ariaLabel: undefined,
})

const emit = defineEmits<{
    'update:modelValue': [value: boolean]
}>()

const inputRef = ref<HTMLInputElement | null>(null)

/** Keep the native indeterminate flag in sync (it is DOM-only, not an attribute). */
function syncIndeterminate(): void {
    if (inputRef.value) inputRef.value.indeterminate = props.indeterminate
}

onMounted(syncIndeterminate)
watch(() => props.indeterminate, syncIndeterminate)

function onChange(e: Event): void {
    emit('update:modelValue', (e.target as HTMLInputElement).checked)
}
</script>

<template>
    <label class="ui-checkbox" :class="[`ui-checkbox--${size}`, { 'ui-checkbox--disabled': disabled }]">
        <input ref="inputRef" class="ui-checkbox__input" type="checkbox" :checked="modelValue" :disabled="disabled"
            :aria-label="ariaLabel || label" @change="onChange" />
        <span class="ui-checkbox__box" :class="{ 'ui-checkbox__box--on': modelValue || indeterminate }"
            aria-hidden="true">
            <AppIcon v-if="indeterminate" name="minus" :size="size === 'sm' ? 11 : 13" />
            <AppIcon v-else-if="modelValue" name="check" :size="size === 'sm' ? 11 : 13" />
        </span>
        <span v-if="label || $slots.default" class="ui-checkbox__label">
            <slot>{{ label }}</slot>
        </span>
    </label>
</template>

<style scoped>
.ui-checkbox {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    cursor: pointer;
    user-select: none;
}

.ui-checkbox--disabled {
    cursor: not-allowed;
    opacity: var(--opacity-disabled);
}

/* Visually-hidden native input (keeps keyboard + a11y semantics). */
.ui-checkbox__input {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
}

.ui-checkbox__box {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    color: var(--surface-0);
    transition:
        background var(--duration-fast) ease,
        border-color var(--duration-fast) ease;
}

.ui-checkbox__box--on {
    background: var(--accent);
    border-color: var(--accent);
}

.ui-checkbox__input:focus-visible + .ui-checkbox__box {
    outline: 2px solid var(--accent-border);
    outline-offset: 1px;
}

.ui-checkbox__label {
    font-size: var(--text-sm);
    color: var(--text-primary);
}

/* ── Sizes ────────────────────────────── */
.ui-checkbox--md .ui-checkbox__box {
    width: 18px;
    height: 18px;
}

.ui-checkbox--sm .ui-checkbox__box {
    width: 15px;
    height: 15px;
}
</style>
