<script setup lang="ts">
/**
 * UiIconButton — Icon-only button with consistent sizing.
 *
 * For toolbar actions, inline controls, and navigation icons.
 *
 * Shares the core prop API with UiButton: `size`, `variant`, `disabled`,
 * `loading`, `ariaLabel`. The `xs` size is specific to this component
 * (there is no xs text button) and is used for tight toolbars.
 */

export interface UiIconButtonProps {
    variant?: 'ghost' | 'subtle' | 'outlined'
    size?: 'xs' | 'sm' | 'md' | 'lg'
    active?: boolean
    disabled?: boolean
    /** Shows an inline spinner and sets aria-busy. */
    loading?: boolean
    /** Native button type — defaults to "button". */
    type?: 'button' | 'submit' | 'reset'
    /**
     * Accessible label (required). Rendered as aria-label AND as the
     * native `title` tooltip, unless `title` is explicitly overridden.
     */
    label: string
    /** Override the native tooltip (defaults to `label`). Use `''` to disable. */
    title?: string
}

const props = withDefaults(defineProps<UiIconButtonProps>(), {
    variant: 'ghost',
    size: 'md',
    active: false,
    disabled: false,
    loading: false,
    type: 'button',
    title: undefined,
})

defineEmits<{
    click: [event: MouseEvent]
}>()

const nativeTitle = (): string | undefined => {
    if (props.title === '') return undefined
    return props.title ?? props.label
}
</script>

<template>
    <button class="ui-icon-btn" :class="[
        `ui-icon-btn--${variant}`,
        `ui-icon-btn--${size}`,
        { 'ui-icon-btn--active': active, 'ui-icon-btn--loading': loading },
    ]" :type="type" :disabled="disabled || loading" :aria-label="label" :aria-busy="loading || undefined"
        :aria-pressed="active || undefined" :title="nativeTitle()" @click="$emit('click', $event)">
        <span v-if="loading" class="ui-icon-btn__spinner" aria-hidden="true" />
        <span v-else class="ui-icon-btn__content"><slot /></span>
    </button>
</template>

<style scoped>
.ui-icon-btn {
    position: relative;
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
    padding: 0;
    transition:
        background-color var(--duration-fast) var(--ease-out-quart),
        border-color var(--duration-fast) var(--ease-out-quart),
        color var(--duration-fast) var(--ease-out-quart),
        transform var(--duration-fast) var(--ease-out-quart);
}

.ui-icon-btn:hover:not(:disabled) { color: var(--text-primary); }
.ui-icon-btn:active:not(:disabled) { transform: scale(0.92); }
.ui-icon-btn:disabled {
    opacity: var(--opacity-disabled);
    cursor: not-allowed;
    pointer-events: none;
}
.ui-icon-btn:focus-visible { box-shadow: var(--shadow-focus); }

.ui-icon-btn__content { display: inline-flex; align-items: center; justify-content: center; }

/* ── Sizes ─────────── */
.ui-icon-btn--xs { width: 24px; height: 24px; }
.ui-icon-btn--sm { width: var(--input-height-sm); height: var(--input-height-sm); }
.ui-icon-btn--md { width: var(--input-height-md); height: var(--input-height-md); }
.ui-icon-btn--lg { width: var(--input-height-lg); height: var(--input-height-lg); }

/* ── Variants ──────── */
.ui-icon-btn--ghost:hover:not(:disabled) { background: var(--surface-hover); }

.ui-icon-btn--subtle { background: var(--surface-hover); }
.ui-icon-btn--subtle:hover:not(:disabled) { background: var(--surface-active); }

.ui-icon-btn--outlined { border-color: var(--border); }
.ui-icon-btn--outlined:hover:not(:disabled) {
    border-color: var(--border-hover);
    background: var(--surface-hover);
}

/* ── Active ────────── */
.ui-icon-btn--active {
    color: var(--accent);
    background: var(--accent-dim);
}
.ui-icon-btn--active:hover:not(:disabled) { background: var(--accent-light); }

/* ── Loading ───────── */
.ui-icon-btn__spinner {
    width: 14px;
    height: 14px;
    border: 2px solid transparent;
    border-top-color: currentColor;
    border-radius: var(--radius-full);
    animation: ui-icon-btn-spin 0.6s linear infinite;
}

@keyframes ui-icon-btn-spin { to { transform: rotate(360deg); } }
</style>
