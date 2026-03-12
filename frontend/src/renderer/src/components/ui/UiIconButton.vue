<script setup lang="ts">
/**
 * UiIconButton — Circular/square icon-only button with consistent sizing.
 *
 * For toolbar actions, inline controls, and navigation icons.
 */

export interface UiIconButtonProps {
    variant?: 'ghost' | 'subtle' | 'outlined'
    size?: 'xs' | 'sm' | 'md' | 'lg'
    active?: boolean
    disabled?: boolean
    label: string
}

withDefaults(defineProps<UiIconButtonProps>(), {
    variant: 'ghost',
    size: 'md',
    active: false,
    disabled: false,
})

defineEmits<{
    click: [event: MouseEvent]
}>()
</script>

<template>
    <button class="ui-icon-btn" :class="[
        `ui-icon-btn--${variant}`,
        `ui-icon-btn--${size}`,
        { 'ui-icon-btn--active': active },
    ]" :disabled="disabled" :aria-label="label" :title="label" @click="$emit('click', $event)">
        <slot />
    </button>
</template>

<style scoped>
.ui-icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    outline: none;
    flex-shrink: 0;
    transition:
        background-color var(--transition-fast),
        border-color var(--transition-fast),
        color var(--transition-fast);
}

.ui-icon-btn:hover:not(:disabled) {
    color: var(--text-primary);
}

.ui-icon-btn:active:not(:disabled) {
    transform: scale(0.92);
}

.ui-icon-btn:disabled {
    opacity: var(--opacity-disabled);
    cursor: not-allowed;
}

.ui-icon-btn:focus-visible {
    box-shadow: var(--shadow-focus);
}

/* ── Sizes ─────────── */
.ui-icon-btn--xs {
    width: 24px;
    height: 24px;
}

.ui-icon-btn--sm {
    width: 28px;
    height: 28px;
}

.ui-icon-btn--md {
    width: 34px;
    height: 34px;
}

.ui-icon-btn--lg {
    width: 40px;
    height: 40px;
}

/* ── Variants ──────── */
.ui-icon-btn--ghost:hover:not(:disabled) {
    background: var(--surface-hover);
}

.ui-icon-btn--subtle {
    background: var(--surface-hover);
}

.ui-icon-btn--subtle:hover:not(:disabled) {
    background: var(--surface-active);
}

.ui-icon-btn--outlined {
    border-color: var(--border);
}

.ui-icon-btn--outlined:hover:not(:disabled) {
    border-color: var(--border-hover);
    background: var(--surface-hover);
}

/* ── Active ────────── */
.ui-icon-btn--active {
    color: var(--accent);
    background: var(--accent-dim);
}

.ui-icon-btn--active:hover:not(:disabled) {
    background: var(--accent-light);
}
</style>
