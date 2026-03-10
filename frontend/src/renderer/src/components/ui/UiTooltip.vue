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
    background: var(--surface-4);
    color: var(--text-primary);
    font-size: var(--text-2xs);
    font-weight: var(--weight-medium);
    letter-spacing: var(--tracking-tight);
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    box-shadow: var(--shadow-elevated);
    white-space: nowrap;
    pointer-events: none;
    opacity: 0;
    transform: scale(0.95);
    transition:
        opacity 150ms ease,
        transform 150ms var(--ease-spring);
    transition-delay: 0ms;
}

.ui-tooltip-wrapper:hover .ui-tooltip {
    opacity: 1;
    transform: scale(1);
    transition-delay: var(--tooltip-delay);
}

/* ── Positions ─── */
.ui-tooltip-wrapper--top .ui-tooltip {
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%) scale(0.95);
}

.ui-tooltip-wrapper--top:hover .ui-tooltip {
    transform: translateX(-50%) scale(1);
}

.ui-tooltip-wrapper--bottom .ui-tooltip {
    top: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%) scale(0.95);
}

.ui-tooltip-wrapper--bottom:hover .ui-tooltip {
    transform: translateX(-50%) scale(1);
}

.ui-tooltip-wrapper--left .ui-tooltip {
    right: calc(100% + 6px);
    top: 50%;
    transform: translateY(-50%) scale(0.95);
}

.ui-tooltip-wrapper--left:hover .ui-tooltip {
    transform: translateY(-50%) scale(1);
}

.ui-tooltip-wrapper--right .ui-tooltip {
    left: calc(100% + 6px);
    top: 50%;
    transform: translateY(-50%) scale(0.95);
}

.ui-tooltip-wrapper--right:hover .ui-tooltip {
    transform: translateY(-50%) scale(1);
}
</style>
