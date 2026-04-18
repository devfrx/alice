<script setup lang="ts">
/**
 * UiButton — World-class button component with multiple variants.
 *
 * Variants: primary | secondary | ghost | danger
 * Sizes:    sm | md | lg
 * States:   default | hover | active | focus-visible | disabled | loading
 *
 * All interactive primitives in the UI library share the same prop contract:
 *   size, variant, disabled, loading, iconPosition, ariaLabel.
 *
 * `type` defaults to "button" to avoid accidental form submits when the
 * component is rendered inside a <form>. Pass `type="submit"` explicitly
 * on a real submit button.
 */

export interface UiButtonProps {
    /** Visual style of the button. */
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    /** Sizing scale — shared with UiInput. */
    size?: 'sm' | 'md' | 'lg'
    /** Shows an inline spinner, sets aria-busy, blocks activation. */
    loading?: boolean
    /** Greys out and blocks pointer + keyboard activation. */
    disabled?: boolean
    /** Render as icon-only (square) — requires `ariaLabel`. */
    icon?: boolean
    /** Stretch to fill the parent width. */
    fullWidth?: boolean
    /** Native button type — defaults to "button" to prevent form submit. */
    type?: 'button' | 'submit' | 'reset'
    /** Position of the `#icon` slot relative to the label. */
    iconPosition?: 'start' | 'end'
    /** Accessible label — required when icon-only or when label is non-textual. */
    ariaLabel?: string
}

withDefaults(defineProps<UiButtonProps>(), {
    variant: 'secondary',
    size: 'md',
    loading: false,
    disabled: false,
    icon: false,
    fullWidth: false,
    type: 'button',
    iconPosition: 'start',
    ariaLabel: undefined,
})

defineEmits<{
    click: [event: MouseEvent]
}>()
</script>

<template>
    <button class="ui-btn" :class="[
        `ui-btn--${variant}`,
        `ui-btn--${size}`,
        `ui-btn--icon-${iconPosition}`,
        { 'ui-btn--loading': loading, 'ui-btn--icon': icon, 'ui-btn--full': fullWidth },
    ]" :type="type" :disabled="disabled || loading" :aria-busy="loading || undefined"
        :aria-disabled="disabled || undefined" :aria-label="ariaLabel" @click="$emit('click', $event)">
        <span v-if="loading" class="ui-btn__spinner" aria-hidden="true" />
        <span class="ui-btn__content" :class="{ 'ui-btn__content--hidden': loading }">
            <span v-if="$slots.icon && iconPosition === 'start'" class="ui-btn__icon">
                <slot name="icon" />
            </span>
            <slot />
            <span v-if="$slots.icon && iconPosition === 'end'" class="ui-btn__icon">
                <slot name="icon" />
            </span>
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
        background-color var(--duration-fast) var(--ease-out-quart),
        border-color var(--duration-fast) var(--ease-out-quart),
        color var(--duration-fast) var(--ease-out-quart),
        transform var(--duration-fast) var(--ease-out-quart);
}

.ui-btn:active:not(:disabled) {
    transform: scale(0.98);
}

.ui-btn:disabled {
    opacity: var(--opacity-disabled);
    cursor: not-allowed;
    pointer-events: none;
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

/* ── Slot wrappers ─────────────────── */
.ui-btn__content {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
}

.ui-btn__icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

/* ── Loading ───────────────────────── */
.ui-btn__spinner {
    position: absolute;
    width: 1em;
    height: 1em;
    border: 2px solid transparent;
    border-top-color: currentColor;
    border-radius: var(--radius-full);
    animation: ui-btn-spin 0.6s linear infinite;
}

.ui-btn__content--hidden {
    visibility: hidden;
}

@keyframes ui-btn-spin {
    to { transform: rotate(360deg); }
}
</style>
