<script setup lang="ts">
/** Press-and-hold state preview controls for visual QA in dev builds. */
import type { OrbState } from './veil-orb/types'

withDefaults(defineProps<{
    activeState: OrbState | null
    compact?: boolean
    orientation?: 'vertical' | 'horizontal'
}>(), {
    compact: false,
    orientation: 'vertical',
})

const emit = defineEmits<{
    'preview-start': [state: OrbState]
    'preview-end': []
}>()

const options: Array<{ state: OrbState; label: string; title: string }> = [
    { state: 'idle', label: 'I', title: 'Idle' },
    { state: 'listening', label: 'L', title: 'Listening' },
    { state: 'thinking', label: 'T', title: 'Thinking' },
    { state: 'speaking', label: 'S', title: 'Speaking' },
    { state: 'processing', label: 'P', title: 'Processing' },
]

function startPreview(state: OrbState): void {
    emit('preview-start', state)
}

function endPreview(): void {
    emit('preview-end')
}
</script>

<template>
    <div class="state-preview-controls" :class="[
        `state-preview-controls--${orientation}`,
        { 'state-preview-controls--compact': compact },
    ]"
        aria-label="Dev state preview">
        <button v-for="option in options" :key="option.state" class="state-preview-controls__btn" type="button"
            :class="{ 'state-preview-controls__btn--active': activeState === option.state }" :title="option.title"
            :aria-label="`Preview ${option.title}`" @pointerdown.stop.prevent="startPreview(option.state)"
            @pointerup.stop.prevent="endPreview" @pointerleave.stop="endPreview" @pointercancel.stop="endPreview"
            @blur="endPreview" @keydown.enter.stop.prevent="startPreview(option.state)"
            @keyup.enter.stop.prevent="endPreview" @keydown.space.stop.prevent="startPreview(option.state)"
            @keyup.space.stop.prevent="endPreview">
            {{ option.label }}
        </button>
    </div>
</template>

<style scoped>
.state-preview-controls {
    display: inline-flex;
    flex-direction: column;
    gap: 4px;
    padding: 4px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--surface-2) 84%, transparent);
    box-shadow: var(--shadow-xs);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
}

.state-preview-controls--horizontal {
    flex-direction: row;
    align-items: center;
}

.state-preview-controls--compact {
    gap: 3px;
    padding: 3px;
}

.state-preview-controls--horizontal.state-preview-controls--compact {
    gap: 4px;
    padding: 4px;
}

.state-preview-controls__btn {
    width: 22px;
    height: 19px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid transparent;
    border-radius: calc(var(--radius-sm) - 2px);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    font-weight: var(--weight-semibold);
    letter-spacing: 0;
    transition:
        color var(--transition-fast),
        background var(--transition-fast),
        border-color var(--transition-fast);
}

.state-preview-controls--horizontal .state-preview-controls__btn {
    width: 20px;
    height: 20px;
}

.state-preview-controls__btn:hover,
.state-preview-controls__btn--active {
    background: var(--accent-dim);
    border-color: var(--accent-border);
    color: var(--accent);
}

.state-preview-controls__btn:focus-visible {
    outline: none;
    box-shadow: var(--shadow-focus);
}
</style>
