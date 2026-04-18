<script setup lang="ts">
/**
 * UiTooltip — Lightweight tooltip wrapper using a CSS-only approach.
 *
 * Wraps any element and reveals a tooltip on hover AND on keyboard focus
 * (so sighted keyboard users get the same hint as mouse users).
 *
 * The tooltip hides automatically when the wrapper unmounts (no detached
 * DOM nodes can linger), and it has `pointer-events: none` so it never
 * intercepts clicks on the wrapped element.
 */

export interface UiTooltipProps {
    text: string
    position?: 'top' | 'bottom' | 'left' | 'right'
    /** Show delay in ms (default: 300). Hide is always immediate. */
    delay?: number
    /** Hide the tooltip entirely (useful for conditional disabling). */
    disabled?: boolean
}

withDefaults(defineProps<UiTooltipProps>(), {
    position: 'top',
    delay: 300,
    disabled: false,
})
</script>

<template>
    <div class="ui-tooltip-wrapper"
        :class="[`ui-tooltip-wrapper--${position}`, { 'ui-tooltip-wrapper--disabled': disabled }]"
        :style="{ '--tooltip-delay': `${delay}ms` }">
        <slot />
        <div v-if="!disabled && text" class="ui-tooltip" role="tooltip">{{ text }}</div>
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
    transition: opacity var(--duration-fast) var(--ease-out-quart);
    transition-delay: 0ms;
}

.ui-tooltip-wrapper:hover .ui-tooltip,
.ui-tooltip-wrapper:focus-within .ui-tooltip {
    opacity: 1;
    transition-delay: var(--tooltip-delay);
}

.ui-tooltip-wrapper--disabled .ui-tooltip {
    display: none;
}

/* ── Positions ─── */
.ui-tooltip-wrapper--top .ui-tooltip {
    bottom: calc(100% + var(--space-1-5));
    left: 50%;
    transform: translateX(-50%);
}

.ui-tooltip-wrapper--bottom .ui-tooltip {
    top: calc(100% + var(--space-1-5));
    left: 50%;
    transform: translateX(-50%);
}

.ui-tooltip-wrapper--left .ui-tooltip {
    right: calc(100% + var(--space-1-5));
    top: 50%;
    transform: translateY(-50%);
}

.ui-tooltip-wrapper--right .ui-tooltip {
    left: calc(100% + var(--space-1-5));
    top: 50%;
    transform: translateY(-50%);
}
</style>
