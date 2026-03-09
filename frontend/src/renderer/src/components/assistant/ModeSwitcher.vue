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
        <div class="mode-switcher__highlight" :style="{ transform: `translateY(${activeIndex * 38}px)` }" />

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
    padding: 4px;
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: 22px;
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    transition:
        width 0.4s cubic-bezier(0.4, 0, 0.2, 1),
        height 0.4s cubic-bezier(0.4, 0, 0.2, 1),
        padding 0.4s cubic-bezier(0.4, 0, 0.2, 1),
        opacity 0.4s cubic-bezier(0.4, 0, 0.2, 1),
        border-radius 0.4s cubic-bezier(0.4, 0, 0.2, 1),
        background 0.3s ease,
        border-color 0.3s ease,
        box-shadow 0.3s ease,
        transform 0.2s ease;
    overflow: hidden;
}

/* Collapsed state: compact gold dot with subtle pulse */
.mode-switcher--collapsed {
    padding: 4px;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--accent-dim);
    border-color: var(--accent-border);
    gap: 0;
    opacity: 0.7;
    box-shadow: 0 0 8px rgba(201, 168, 76, 0.15);
    animation: collapsed-pulse 3s ease-in-out infinite;
}

.mode-switcher--collapsed:hover {
    opacity: 1;
    transform: scale(1.15);
    box-shadow: 0 0 16px rgba(201, 168, 76, 0.35);
    border-color: var(--accent);
}

@keyframes collapsed-pulse {

    0%,
    100% {
        box-shadow: 0 0 8px rgba(201, 168, 76, 0.15);
    }

    50% {
        box-shadow: 0 0 14px rgba(201, 168, 76, 0.28);
    }
}

.mode-switcher--collapsed .mode-switcher__btn,
.mode-switcher--collapsed .mode-switcher__highlight {
    opacity: 0;
    pointer-events: none;
}

/* Sliding highlight behind active button */
.mode-switcher__highlight {
    position: absolute;
    top: 4px;
    left: 4px;
    right: 4px;
    height: 36px;
    border-radius: 18px;
    background: var(--accent-dim);
    border: 1px solid var(--accent-border);
    box-shadow: 0 0 12px rgba(201, 168, 76, 0.1);
    transition: transform 0.35s cubic-bezier(0.25, 0.46, 0.45, 0.94);
    pointer-events: none;
    z-index: 0;
}

.mode-switcher__btn {
    position: relative;
    z-index: 1;
    width: 36px;
    height: 36px;
    border: none;
    border-radius: 18px;
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: color 0.2s ease;
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
    left: calc(100% + 10px);
    white-space: nowrap;
    font-size: 12px;
    color: var(--text-primary);
    background: var(--glass-bg);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-md);
    padding: 4px 10px;
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    pointer-events: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
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
