<script setup lang="ts">
/**
 * UiCard — Elevated surface with consistent styling.
 *
 * Variants: default (surface-2), subtle (surface-1), elevated (surface-3 + shadow)
 * Optional interactive hover, padding, border.
 */

export interface UiCardProps {
    variant?: 'default' | 'subtle' | 'elevated' | 'glass'
    interactive?: boolean
    noPadding?: boolean
}

withDefaults(defineProps<UiCardProps>(), {
    variant: 'default',
    interactive: false,
    noPadding: false,
})
</script>

<template>
    <div class="ui-card" :class="[
        `ui-card--${variant}`,
        { 'ui-card--interactive': interactive, 'ui-card--no-padding': noPadding },
    ]">
        <slot />
    </div>
</template>

<style scoped>
.ui-card {
    border-radius: var(--radius-md);
    border: 1px solid var(--border);
    padding: var(--space-5);
    transition:
        background-color var(--transition-fast),
        border-color var(--transition-fast);
}

/* ── Variants ──── */
.ui-card--default {
    background: var(--surface-1);
}

.ui-card--subtle {
    background: var(--surface-1);
    border-color: transparent;
}

.ui-card--elevated {
    background: var(--surface-2);
    box-shadow: var(--shadow-elevated);
}

.ui-card--glass {
    background: var(--surface-2);
}

/* ── Interactive ── */
.ui-card--interactive {
    cursor: pointer;
}

.ui-card--interactive:hover {
    border-color: var(--border-hover);
}

.ui-card--interactive:focus-visible {
    box-shadow: var(--shadow-focus);
}

/* ── No padding ── */
.ui-card--no-padding {
    padding: 0;
}
</style>
