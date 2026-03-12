<script setup lang="ts">
/**
 * UiButton — World-class button component with multiple variants.
 *
 * Variants: primary | secondary | ghost | danger
 * Sizes:    sm | md | lg
 * States:   default | hover | active | focus | disabled | loading
 */

export interface UiButtonProps {
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'sm' | 'md' | 'lg'
    loading?: boolean
    disabled?: boolean
    icon?: boolean
    fullWidth?: boolean
}

withDefaults(defineProps<UiButtonProps>(), {
    variant: 'secondary',
    size: 'md',
    loading: false,
    disabled: false,
    icon: false,
    fullWidth: false,
})

defineEmits<{
    click: [event: MouseEvent]
}>()
</script>

<template>
    <button class="ui-btn" :class="[
        `ui-btn--${variant}`,
        `ui-btn--${size}`,
        { 'ui-btn--loading': loading, 'ui-btn--icon': icon, 'ui-btn--full': fullWidth },
    ]" :disabled="disabled || loading" @click="$emit('click', $event)">
        <span v-if="loading" class="ui-btn__spinner" />
        <span class="ui-btn__content" :class="{ 'ui-btn__content--hidden': loading }">
            <slot />
        </span>
    </button>
</template>

<style scoped>
.ui-btn {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    font-family: var(--font-sans);
    font-weight: var(--weight-medium);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
    outline: none;
    transition:
        background-color var(--transition-fast),
        border-color var(--transition-fast),
        color var(--transition-fast);
}

.ui-btn:active:not(:disabled) {
    transform: scale(0.98);
}

.ui-btn:disabled {
    opacity: var(--opacity-disabled);
    cursor: not-allowed;
}

.ui-btn:focus-visible {
    box-shadow: var(--shadow-focus);
}

/* ── Sizes ─────────────────────────── */
.ui-btn--sm {
    height: var(--input-height-sm);
    padding: 0 var(--space-3);
    font-size: var(--text-xs);
}

.ui-btn--md {
    height: var(--input-height-md);
    padding: 0 var(--space-4);
    font-size: var(--text-sm);
}

.ui-btn--lg {
    height: var(--input-height-lg);
    padding: 0 var(--space-6);
    font-size: var(--text-md);
}

/* ── Variants ──────────────────────── */
.ui-btn--primary {
    background: var(--accent);
    color: var(--surface-0);
}

.ui-btn--primary:hover:not(:disabled) {
    background: var(--accent-hover);
}

.ui-btn--secondary {
    background: transparent;
    color: var(--text-primary);
    border-color: var(--border);
}

.ui-btn--secondary:hover:not(:disabled) {
    background: var(--surface-hover);
    border-color: var(--border-hover);
}

.ui-btn--ghost {
    background: transparent;
    color: var(--text-secondary);
}

.ui-btn--ghost:hover:not(:disabled) {
    background: var(--surface-hover);
    color: var(--text-primary);
}

.ui-btn--danger {
    background: transparent;
    border-color: var(--danger-border);
    color: var(--danger);
}

.ui-btn--danger:hover:not(:disabled) {
    background: var(--danger-faint);
}

/* ── Icon-only ─────────────────────── */
.ui-btn--icon {
    padding: 0;
}

.ui-btn--icon.ui-btn--sm {
    width: var(--input-height-sm);
}

.ui-btn--icon.ui-btn--md {
    width: var(--input-height-md);
}

.ui-btn--icon.ui-btn--lg {
    width: var(--input-height-lg);
}

/* ── Full Width ────────────────────── */
.ui-btn--full {
    width: 100%;
}

/* ── Loading ───────────────────────── */
.ui-btn__spinner {
    position: absolute;
    width: 16px;
    height: 16px;
    border: 2px solid transparent;
    border-top-color: currentColor;
    border-radius: var(--radius-full);
    animation: spin 0.6s linear infinite;
}

.ui-btn__content--hidden {
    visibility: hidden;
}
</style>
