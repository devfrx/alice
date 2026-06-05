<script setup lang="ts">
/**
 * AssistantFab.vue — Unified floating action button for assistant view.
 *
 * Glassmorphism expandable FAB anchored at bottom-right.
 * Combines mode switching, new conversation, and settings navigation
 * into a single, state-aware control. Shows a pulsing indicator dot
 * that matches the current AI state color.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '../../stores/chat'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{
    orbState: 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'
    messageCount?: number
}>()

const emit = defineEmits<{
    'toggle-history': []
}>()

const router = useRouter()
const chatStore = useChatStore()

const expanded = ref(false)
const fabRef = ref<HTMLElement | null>(null)

const isActive = computed(() => props.orbState !== 'idle')

interface FabAction {
    id: string
    label: string
}

const actions: FabAction[] = [
    { id: 'history', label: 'Cronologia' },
    // { id: 'mode', label: 'Modalità Ibrida' },
    { id: 'new-conv', label: 'Nuova chat' },
    { id: 'settings', label: 'Impostazioni' },
]

function handleAction(id: string): void {
    switch (id) {
        case 'history':
            emit('toggle-history')
            break
        case 'mode':
            // 'hybrid' mode retired (R3) — Workspace is now the primary surface.
            router.push({ name: 'workspace' })
            break
        case 'new-conv':
            chatStore.createConversation().catch(console.error)
            break
        case 'settings':
            router.push({ name: 'settings' })
            break
    }
    expanded.value = false
}

function toggle(): void {
    expanded.value = !expanded.value
}

function onClickOutside(e: PointerEvent): void {
    if (expanded.value && fabRef.value && !fabRef.value.contains(e.target as Node)) {
        expanded.value = false
    }
}

onMounted(() => document.addEventListener('pointerdown', onClickOutside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', onClickOutside))
</script>

<template>
    <div ref="fabRef" class="fab" :class="{ 'fab--open': expanded }">
        <!-- Action menu -->
        <Transition name="fab-menu">
            <div v-if="expanded" class="fab__menu">
                <button v-for="(a, i) in actions" :key="a.id" class="fab__action"
                    :style="{ '--delay': `${(actions.length - 1 - i) * 45}ms` }" @click="handleAction(a.id)">

                    <!-- History icon -->
                    <AppIcon v-if="a.id === 'history'" name="clock" :size="16" :stroke-width="1.5"
                        class="fab__action-icon" />

                    <!-- Mode switch icon -->
                    <AppIcon v-else-if="a.id === 'mode'" name="hybrid-panel" :size="16" :stroke-width="1.5"
                        class="fab__action-icon" />

                    <!-- New conversation icon -->
                    <AppIcon v-else-if="a.id === 'new-conv'" name="message-plus" :size="16" :stroke-width="1.5"
                        class="fab__action-icon" />

                    <!-- Settings icon -->
                    <AppIcon v-else name="settings" :size="16" :stroke-width="1.5" class="fab__action-icon" />

                    <span class="fab__action-label">{{ a.label }}</span>
                </button>
            </div>
        </Transition>

        <!-- Trigger button -->
        <button class="fab__trigger" @click="toggle" aria-label="Azioni rapide">
            <span v-if="isActive && !expanded" class="fab__dot" :class="`fab__dot--${orbState}`" />
            <AppIcon name="plus" :size="16" class="fab__trigger-icon" />
        </button>
    </div>
</template>

<style scoped>
.fab {
    position: absolute;
    bottom: var(--space-5);
    right: var(--space-5);
    z-index: var(--z-overlay);
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--space-2);
}

/* ── Trigger ────────────────────────────────────────────────────── */
.fab__trigger {
    position: relative;
    width: 42px;
    height: 42px;
    border-radius: var(--radius-full);
    border: 1px solid var(--glass-border);
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    color: var(--text-secondary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition:
        border-color var(--transition-fast),
        color var(--transition-fast),
        background var(--transition-fast),
        box-shadow var(--transition-fast);
}

.fab__trigger:hover {
    border-color: var(--border-hover);
    color: var(--accent);
    background: var(--surface-3);
    box-shadow: var(--shadow-sm);
}

.fab--open .fab__trigger {
    border-color: var(--accent-border);
    color: var(--accent);
    background: var(--accent-dim);
}

.fab__trigger-icon {
    transition: transform 0.3s var(--ease-out-expo);
}

.fab--open .fab__trigger-icon {
    transform: rotate(45deg);
}

/* ── State indicator dot ────────────────────────────────────────── */
.fab__dot {
    position: absolute;
    top: 3px;
    right: 3px;
    width: 7px;
    height: 7px;
    border-radius: var(--radius-full);
    border: 1.5px solid var(--surface-2);
    animation: fabDotPulse 2s ease-in-out infinite;
}

.fab__dot--listening {
    background: var(--listening);
}

.fab__dot--thinking {
    background: var(--thinking);
}

.fab__dot--speaking {
    background: var(--speaking);
}

.fab__dot--processing {
    background: var(--thinking);
}

/* ── Menu ───────────────────────────────────────────────────────── */
.fab__menu {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--space-1);
}

/* ── Action item ────────────────────────────────────────────────── */
.fab__action {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1-5) var(--space-3) var(--space-1-5) var(--space-2-5);
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-pill);
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur-heavy));
    -webkit-backdrop-filter: blur(var(--glass-blur-heavy));
    color: var(--text-secondary);
    font-size: var(--text-xs);
    white-space: nowrap;
    cursor: pointer;
    animation: fabItemIn 0.28s var(--ease-out-expo) var(--delay) both;
    transition:
        background var(--transition-fast),
        border-color var(--transition-fast),
        color var(--transition-fast),
        box-shadow var(--transition-fast);
}

.fab__action:hover {
    background: var(--surface-3);
    border-color: var(--accent-border);
    color: var(--text-primary);
    box-shadow: 0 0 16px var(--accent-glow);
}

.fab__action-icon {
    flex-shrink: 0;
    opacity: 0.85;
    transition: opacity var(--transition-fast);
}

.fab__action:hover .fab__action-icon {
    opacity: 1;
}

.fab__action-label {
    font-weight: var(--weight-medium);
    letter-spacing: 0.015em;
}

/* ── Menu transition ────────────────────────────────────────────── */
.fab-menu-enter-active {
    transition: opacity 0.18s ease;
}

.fab-menu-leave-active {
    transition: opacity 0.12s ease;
}

.fab-menu-enter-from,
.fab-menu-leave-to {
    opacity: 0;
}

/* ── Staggered item entrance ────────────────────────────────────── */
@keyframes fabItemIn {
    from {
        opacity: 0;
        transform: translateY(8px) scale(0.9);
    }

    to {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}

/* ── Dot pulse ──────────────────────────────────────────────────── */
@keyframes fabDotPulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.35;
    }
}

@media (prefers-reduced-motion: reduce) {

    .fab__trigger-icon,
    .fab__action {
        animation: none;
        transition: none;
    }

    .fab__dot {
        animation: none;
    }
}
</style>
