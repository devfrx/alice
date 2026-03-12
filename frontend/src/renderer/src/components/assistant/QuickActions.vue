<script setup lang="ts">
/**
 * QuickActions.vue — Bottom-right contextual action menu.
 * Trigger is a three-dot icon; expands to show labeled actions.
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '../../stores/chat'

const router = useRouter()
const chatStore = useChatStore()
const expanded = ref(false)

interface QuickAction {
    id: string
    label: string
    action: () => void
}

const actions: QuickAction[] = [
    {
        id: 'new-conv',
        label: 'Nuova conversazione',
        action: () => {
            chatStore.createConversation().catch(console.error)
            expanded.value = false
        },
    },
    {
        id: 'settings',
        label: 'Impostazioni',
        action: () => {
            router.push({ name: 'settings' })
            expanded.value = false
        },
    },
]

function toggleExpand(): void {
    expanded.value = !expanded.value
}
</script>

<template>
    <div class="quick-actions" :class="{ 'quick-actions--expanded': expanded }">
        <!-- Expanded menu items -->
        <Transition name="menu-slide">
            <div v-if="expanded" class="quick-actions__menu">
                <button v-for="a in actions" :key="a.id" class="quick-actions__item" @click="a.action()">
                    <!-- New conversation -->
                    <svg v-if="a.id === 'new-conv'" class="quick-actions__item-icon" width="16" height="16"
                        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                        <line x1="12" y1="8" x2="12" y2="14" />
                        <line x1="9" y1="11" x2="15" y2="11" />
                    </svg>

                    <!-- Settings -->
                    <svg v-else-if="a.id === 'settings'" class="quick-actions__item-icon" width="16" height="16"
                        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <circle cx="12" cy="12" r="3" />
                        <path
                            d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                    </svg>

                    <span class="quick-actions__item-label">{{ a.label }}</span>
                </button>
            </div>
        </Transition>

        <!-- Trigger: three-dot icon -->
        <button class="quick-actions__trigger" :class="{ 'quick-actions__trigger--active': expanded }"
            @click="toggleExpand">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"
                :style="{ transition: 'transform 0.3s ease', transform: expanded ? 'rotate(90deg)' : 'rotate(0)' }">
                <circle cx="12" cy="5" r="1.5" />
                <circle cx="12" cy="12" r="1.5" />
                <circle cx="12" cy="19" r="1.5" />
            </svg>
        </button>
    </div>
</template>

<style scoped>
.quick-actions {
    position: absolute;
    bottom: var(--space-4);
    right: var(--space-4);
    z-index: 5;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: var(--space-1-5);
}

/* ── Trigger button ── */
.quick-actions__trigger {
    width: 40px;
    height: 40px;
    border-radius: var(--radius-full);
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--text-secondary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: border-color var(--transition-fast),
        color var(--transition-fast),
        background var(--transition-fast);
}

.quick-actions__trigger:hover {
    border-color: var(--border-hover);
    color: var(--accent);
    background: var(--surface-3);
}

.quick-actions__trigger--active {
    border-color: var(--accent-border);
    background: var(--accent-dim);
    color: var(--accent);
}

/* ── Menu ── */
.quick-actions__menu {
    display: flex;
    flex-direction: column;
    gap: var(--space-0-5);
    padding: var(--space-1);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
    min-width: 180px;
}

/* ── Menu item ── */
.quick-actions__item {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
    text-align: left;
    width: 100%;
}

.quick-actions__item:hover {
    background: var(--surface-hover);
    color: var(--text-primary);
}

.quick-actions__item-icon {
    flex-shrink: 0;
    opacity: var(--opacity-visible);
}

.quick-actions__item:hover .quick-actions__item-icon {
    opacity: 1;
}

.quick-actions__item-label {
    font-size: var(--text-sm);
    white-space: nowrap;
}

/* ── Menu slide transition ── */
.menu-slide-enter-active {
    transition: opacity var(--duration-fast) ease,
        transform var(--duration-fast) var(--ease-bounce);
}

.menu-slide-leave-active {
    transition: opacity var(--duration-fast) ease,
        transform var(--duration-fast) ease;
}

.menu-slide-enter-from {
    opacity: 0;
    transform: translateY(8px) scale(0.95);
}

.menu-slide-leave-to {
    opacity: 0;
    transform: translateY(8px) scale(0.95);
}
</style>
