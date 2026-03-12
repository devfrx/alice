<script setup lang="ts">
/**
 * UiTooltip — Lightweight tooltip wrapper using CSS-only approach.
 *
 * Wraps any element and shows a tooltip on hover with proper positioning.
 * Uses data attributes and CSS for zero-JS tooltip rendering.
 */

export interface UiTooltipProps {
    text: string
    position?: 'top' | 'bottom' | 'left' | 'right'
    delay?: number
}

withDefaults(defineProps<UiTooltipProps>(), {
    position: 'top',
    delay: 300,
})
</script>

<template>
    <div class="ui-tooltip-wrapper" :class="`ui-tooltip-wrapper--${position}`"
        :style="{ '--tooltip-delay': `${delay}ms` }">
        <slot />
        <div class="ui-tooltip" role="tooltip">{{ text }}</div>
    </div>
</template>

<style scoped>
.ui-tooltip-wrapper {
    position: relative;
    display: inline-flex;
}

.ui-tooltip {
    position: absolute;
    z-index: var(--z-dropdown);
    padding: var(--space-1) var(--space-2);
    background: var(--surface-3);
    color: var(--text-primary);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow-md);
    white-space: nowrap;
    pointer-events: none;
    opacity: 0;
    transition: opacity var(--transition-fast);
    transition-delay: 0ms;
}

.ui-tooltip-wrapper:hover .ui-tooltip {
    opacity: 1;
    transition-delay: var(--tooltip-delay);
}

/* ── Positions ─── */
.ui-tooltip-wrapper--top .ui-tooltip {
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
}

.ui-tooltip-wrapper--bottom .ui-tooltip {
    top: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
}

.ui-tooltip-wrapper--left .ui-tooltip {
    right: calc(100% + 6px);
    top: 50%;
    transform: translateY(-50%);
}

.ui-tooltip-wrapper--right .ui-tooltip {
    left: calc(100% + 6px);
    top: 50%;
    transform: translateY(-50%);
}
</style>
