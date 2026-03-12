<script setup lang="ts">
/**
 * ModeSwitcher.vue — Vertical floating mode pill (bottom-left).
 * Minimal in assistant mode: collapses to a dot, expands on hover.
 * Uses proper SVG icons for each mode.
 */
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUIStore, type UIMode } from '../../stores/ui'

const uiStore = useUIStore()
const router = useRouter()
const hovered = ref(false)

interface ModeEntry {
    id: UIMode
    label: string
}

const modes: ModeEntry[] = [
    { id: 'assistant', label: 'Assistente' },
    { id: 'hybrid', label: 'Ibrido' },
]

/** Active mode index for the sliding highlight. */
const activeIndex = computed(() => modes.findIndex((m) => m.id === uiStore.mode))

/** In assistant mode, collapse to a compact dot unless hovered. */
const isCollapsed = computed(() => uiStore.mode === 'assistant' && !hovered.value)

function switchMode(mode: UIMode): void {
    uiStore.setMode(mode)
    router.push({ name: mode })
}
</script>

<template>
    <div class="mode-switcher" :class="{ 'mode-switcher--collapsed': isCollapsed }" @mouseenter="hovered = true"
        @mouseleave="hovered = false">
        <!-- Sliding active highlight -->
        <div class="mode-switcher__highlight" :style="{ transform: `translateY(${activeIndex * 36}px)` }" />

        <button v-for="m in modes" :key="m.id" class="mode-switcher__btn"
            :class="{ 'mode-switcher__btn--active': uiStore.mode === m.id }" @click="switchMode(m.id)">
            <!-- Assistant: concentric orb/eye icon -->
            <svg v-if="m.id === 'assistant'" class="mode-switcher__icon" width="18" height="18" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="1.5">
                <circle cx="12" cy="12" r="10" />
                <circle cx="12" cy="12" r="6" />
                <circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" />
            </svg>

            <!-- Hybrid: overlapping circle + bubble -->
            <svg v-else class="mode-switcher__icon" width="18" height="18" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="1.5">
                <circle cx="9" cy="10" r="6" />
                <path d="M15 9a5 5 0 0 1 5 5v0a2 2 0 0 1-2 2h-5l-2.5 2.5V16" />
            </svg>

            <!-- Tooltip label (appears to the right on hover) -->
            <Transition name="label-slide">
                <span v-if="hovered" class="mode-switcher__label">{{ m.label }}</span>
            </Transition>
        </button>
    </div>
</template>

<style scoped>
.mode-switcher {
    position: fixed;
    bottom: var(--space-4);
    left: var(--space-4);
    z-index: var(--z-sticky);
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 3px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    box-shadow: var(--shadow-sm);
    transition:
        width 300ms var(--ease-out-expo, ease),
        height 300ms var(--ease-out-expo, ease),
        padding 300ms ease,
        opacity 300ms ease,
        border-radius 300ms ease,
        transform 150ms ease;
    overflow: hidden;
}

/* Collapsed state: compact dot */
.mode-switcher--collapsed {
    padding: 3px;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--surface-3);
    border-color: var(--accent-border);
    gap: 0;
    opacity: 0.6;
}

.mode-switcher--collapsed:hover {
    opacity: 1;
    transform: scale(1.1);
    border-color: var(--accent);
}

.mode-switcher--collapsed .mode-switcher__btn,
.mode-switcher--collapsed .mode-switcher__highlight {
    opacity: 0;
    pointer-events: none;
}

/* Sliding highlight behind active button */
.mode-switcher__highlight {
    position: absolute;
    top: 3px;
    left: 3px;
    right: 3px;
    height: 34px;
    border-radius: var(--radius-md);
    background: var(--surface-selected);
    border: 1px solid var(--accent-border);
    transition: transform 250ms var(--ease-out-expo, ease);
    pointer-events: none;
    z-index: 0;
}

.mode-switcher__btn {
    position: relative;
    z-index: 1;
    width: 34px;
    height: 34px;
    border: none;
    border-radius: var(--radius-md);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color var(--transition-fast);
    padding: 0;
}

.mode-switcher__btn:hover {
    color: var(--text-secondary);
}

.mode-switcher__btn--active {
    color: var(--accent);
}

.mode-switcher__icon {
    flex-shrink: 0;
}

/* Label tooltip to the right */
.mode-switcher__label {
    position: absolute;
    left: calc(100% + 8px);
    white-space: nowrap;
    font-size: var(--text-2xs);
    color: var(--text-primary);
    background: var(--surface-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 3px 8px;
    pointer-events: none;
    box-shadow: var(--shadow-sm);
}

/* ── Label slide transition (150ms enter delay to prevent flash) ── */
.label-slide-enter-active {
    transition: opacity 0.2s ease 0.15s, transform 0.2s ease 0.15s;
}

.label-slide-leave-active {
    transition: opacity 0.12s ease, transform 0.12s ease;
}

.label-slide-enter-from {
    opacity: 0;
    transform: translateX(-6px);
}

.label-slide-leave-to {
    opacity: 0;
    transform: translateX(-6px);
}
</style>
