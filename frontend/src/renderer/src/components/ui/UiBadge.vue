<script setup lang="ts">
/**
 * UiBadge — Status / label badges with semantic colors.
 *
 * Variants: default | accent | success | danger | warning | info
 * Sizes:    sm | md | lg (shared scale with UiButton on the short axis)
 *
 * Use `dot` for a leading status dot (e.g. "● Online").
 * Use `removable` to expose a close affordance — listen on `@remove`.
 */

export interface UiBadgeProps {
    variant?: 'default' | 'accent' | 'success' | 'danger' | 'warning' | 'info'
    size?: 'sm' | 'md' | 'lg'
    /** Show a leading status dot. */
    dot?: boolean
    /** Show a trailing close button and emit `remove` on activation. */
    removable?: boolean
    /** Accessible label for the remove button (defaults to "Remove"). */
    removeLabel?: string
}

withDefaults(defineProps<UiBadgeProps>(), {
    variant: 'default',
    size: 'sm',
    dot: false,
    removable: false,
    removeLabel: 'Remove',
})

const emit = defineEmits<{
    remove: [event: MouseEvent]
}>()
</script>

<template>
    <span class="ui-badge" :class="[`ui-badge--${variant}`, `ui-badge--${size}`, { 'ui-badge--dot': dot }]">
        <span v-if="dot" class="ui-badge__dot" aria-hidden="true" />
        <span class="ui-badge__label">
            <slot />
        </span>
        <button v-if="removable" type="button" class="ui-badge__remove" :aria-label="removeLabel"
            @click.stop="emit('remove', $event)">
            <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                <path d="M2 2 L8 8 M8 2 L2 8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
            </svg>
        </button>
    </span>
</template>

<style scoped>
.ui-badge {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    border-radius: var(--radius-pill);
    font-weight: var(--weight-medium);
    white-space: nowrap;
    line-height: var(--leading-tight);
    max-width: 100%;
}

.ui-badge__label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
}

/* ── Sizes ────── */
.ui-badge--sm {
    padding: var(--space-0-5) var(--space-2);
    font-size: var(--text-2xs);
}

.ui-badge--md {
    padding: var(--space-1) var(--space-3);
    font-size: var(--text-xs);
}

.ui-badge--lg {
    padding: var(--space-1-5) var(--space-3);
    font-size: var(--text-sm);
}

/* ── Variants ──── */
.ui-badge--default {
    background: var(--surface-3);
    color: var(--text-secondary);
}

.ui-badge--accent {
    background: var(--accent-dim);
    color: var(--accent);
}

.ui-badge--success {
    background: var(--success-light);
    color: var(--success);
}

.ui-badge--danger {
    background: var(--danger-light);
    color: var(--danger);
}

.ui-badge--warning {
    background: var(--warning-bg);
    color: var(--warning);
}

.ui-badge--info {
    background: var(--accent-subtle);
    color: var(--text-secondary);
}

/* ── Dot ───────── */
.ui-badge__dot {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-full);
    background: currentColor;
    flex-shrink: 0;
}

/* ── Remove button ─ */
.ui-badge__remove {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    margin-inline-start: var(--space-0-5);
    width: 14px;
    height: 14px;
    border: none;
    border-radius: var(--radius-full);
    background: transparent;
    color: inherit;
    opacity: var(--opacity-medium);
    cursor: pointer;
    outline: none;
    transition: background-color var(--duration-fast) var(--ease-out-quart),
        opacity var(--duration-fast) var(--ease-out-quart);
}

.ui-badge__remove:hover {
    background: var(--surface-hover);
    opacity: 1;
}

.ui-badge__remove:focus-visible {
    box-shadow: var(--shadow-focus);
}
</style>
