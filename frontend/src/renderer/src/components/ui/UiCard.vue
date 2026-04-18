<script setup lang="ts">
/**
 * UiCard — Elevated surface with consistent styling.
 *
 * Variants:
 *   default  — surface-1 + subtle border
 *   subtle   — surface-1, borderless
 *   elevated — surface-2 + elevated shadow
 *   glass    — frosted surface (backdrop-filter)
 *
 * When `interactive` is true the card becomes keyboard-focusable
 * (tabindex=0) and emits `click` on Enter / Space, so it works as a
 * real button-like affordance without losing the semantic `<div>`.
 */

export interface UiCardProps {
    variant?: 'default' | 'subtle' | 'elevated' | 'glass'
    /** Makes the card focusable + keyboard-activatable. */
    interactive?: boolean
    /** Strip internal padding (useful for media-first layouts). */
    noPadding?: boolean
    /** Semantic role applied when `interactive` is true. */
    role?: string
}

withDefaults(defineProps<UiCardProps>(), {
    variant: 'default',
    interactive: false,
    noPadding: false,
    role: 'button',
})

const emit = defineEmits<{
    click: [event: MouseEvent | KeyboardEvent]
}>()

function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        emit('click', e)
    }
}
</script>

<template>
    <div class="ui-card" :class="[
        `ui-card--${variant}`,
        { 'ui-card--interactive': interactive, 'ui-card--no-padding': noPadding },
    ]" :tabindex="interactive ? 0 : undefined" :role="interactive ? role : undefined"
        @click="interactive && emit('click', $event)" @keydown="interactive && onKeydown($event)">
        <slot />
    </div>
</template>

<style scoped>
.ui-card {
    border-radius: var(--radius-md);
    border: 1px solid var(--border);
    padding: var(--space-5);
    transition:
        background-color var(--duration-fast) var(--ease-out-quart),
        border-color var(--duration-fast) var(--ease-out-quart),
        transform var(--duration-fast) var(--ease-out-quart);
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
    background: var(--glass-bg);
    border-color: var(--glass-border);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
}

/* ── Interactive ── */
.ui-card--interactive {
    cursor: pointer;
    outline: none;
}

.ui-card--interactive:hover {
    border-color: var(--border-hover);
}

.ui-card--interactive:active {
    transform: scale(0.995);
}

.ui-card--interactive:focus-visible {
    box-shadow: var(--shadow-focus);
}

/* ── No padding ── */
.ui-card--no-padding {
    padding: 0;
}
</style>
