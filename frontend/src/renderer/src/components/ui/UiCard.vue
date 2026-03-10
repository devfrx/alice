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
    border-radius: var(--radius-lg);
    border: 1px solid var(--border);
    padding: var(--space-4);
    transition:
        background-color 150ms ease,
        border-color 150ms ease,
        box-shadow 200ms ease,
        transform 200ms ease;
}

/* ── Variants ──── */
.ui-card--default {
    background: var(--surface-2);
}

.ui-card--subtle {
    background: var(--surface-1);
    border-color: transparent;
}

.ui-card--elevated {
    background: var(--surface-3);
    box-shadow: var(--shadow-elevated);
}

.ui-card--glass {
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border-color: var(--glass-border);
}

/* ── Interactive ── */
.ui-card--interactive {
    cursor: pointer;
}

.ui-card--interactive:hover {
    border-color: var(--border-hover);
    transform: translateY(-1px);
    box-shadow: var(--shadow-md);
}

.ui-card--interactive:active {
    transform: translateY(0);
}

.ui-card--interactive:focus-visible {
    box-shadow: var(--focus-ring-shadow);
}

/* ── No padding ── */
.ui-card--no-padding {
    padding: 0;
}
</style>
