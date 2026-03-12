<script setup lang="ts">
/**
 * UiBadge — Status/label badges with semantic colors.
 *
 * Variants: default | accent | success | danger | warning
 * Sizes:    sm | md
 */

export interface UiBadgeProps {
    variant?: 'default' | 'accent' | 'success' | 'danger' | 'warning'
    size?: 'sm' | 'md'
    dot?: boolean
}

withDefaults(defineProps<UiBadgeProps>(), {
    variant: 'default',
    size: 'sm',
    dot: false,
})
</script>

<template>
    <span class="ui-badge" :class="[`ui-badge--${variant}`, `ui-badge--${size}`, { 'ui-badge--dot': dot }]">
        <span v-if="dot" class="ui-badge__dot" />
        <slot />
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
    line-height: 1;
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

/* ── Dot ───────── */
.ui-badge__dot {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-full);
    background: currentColor;
    flex-shrink: 0;
}
</style>
