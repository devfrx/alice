<script setup lang="ts">
/**
 * ConversationDrawer.vue — Slide-in panel showing full conversation history.
 *
 * Allows the user to see the complete message thread in assistant mode
 * without breaking the "OMNIA speaks" illusion. Slides from the left.
 */
import { ref, watch, nextTick } from 'vue'
import { renderMarkdown } from '../../utils/markdownRenderer'
import MessageVersionNav from '../chat/MessageVersionNav.vue'
import type { ChatMessage } from '../../types/chat'

const props = defineProps<{
    open: boolean
    messages: ChatMessage[]
    /** Whether the assistant is currently streaming (disables edit/version nav). */
    isStreaming?: boolean
    /** Whether branching is disabled (streaming or other guard). */
    branchDisabled?: boolean
    /** Getter: returns total version count for a given version_group_id. */
    getVersionCount?: (groupId: string) => number
    /** Getter: returns active version index for a given version_group_id. */
    getActiveVersionIndex?: (groupId: string) => number
}>()

const emit = defineEmits<{
    close: []
    /** User wants to edit a message. */
    edit: [messageId: string]
    /** User wants to switch version. */
    'switch-version': [versionGroupId: string, versionIndex: number]
    /** User wants to branch from this assistant message. */
    branch: [messageId: string]
}>()

const scrollContainer = ref<HTMLElement | null>(null)

/** Auto-scroll to bottom when opened. */
watch(() => props.open, async (isOpen) => {
    if (isOpen) {
        await nextTick()
        if (scrollContainer.value) {
            scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight
        }
    }
})

function roleLabel(role: string): string {
    switch (role) {
        case 'user': return 'Tu'
        case 'assistant': return 'OMNIA'
        case 'tool': return 'Strumento'
        case 'system': return 'Sistema'
        default: return role
    }
}

function formatTime(dateStr: string): string {
    try {
        const d = new Date(dateStr)
        return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
    } catch {
        return ''
    }
}

/** Truncate tool results for compact display. */
function truncateContent(content: string, maxLen = 200): string {
    if (content.length <= maxLen) return content
    return content.slice(0, maxLen) + '…'
}
</script>

<template>
    <Teleport to="body">
        <!-- Backdrop -->
        <Transition name="drawer-backdrop">
            <div v-if="open" class="drawer-backdrop" @click="emit('close')" />
        </Transition>

        <!-- Drawer panel -->
        <Transition name="drawer-slide">
            <div v-if="open" class="drawer">
                <div class="drawer__header">
                    <h2 class="drawer__title">Cronologia</h2>
                    <span v-if="messages.length" class="drawer__count">{{ messages.length }}</span>
                    <button class="drawer__close" aria-label="Chiudi cronologia" @click="emit('close')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    </button>
                </div>

                <div ref="scrollContainer" class="drawer__messages">
                    <div v-if="messages.length === 0" class="drawer__empty">
                        <p>Nessun messaggio in questa conversazione.</p>
                    </div>

                    <div v-for="msg in messages" :key="msg.id" class="drawer__msg" :class="`drawer__msg--${msg.role}`">
                        <div class="drawer__msg-header">
                            <span class="drawer__msg-role">{{ roleLabel(msg.role) }}</span>
                            <div class="drawer__msg-actions">
                                <button v-if="msg.role === 'user' && !isStreaming" class="drawer__edit-btn"
                                    aria-label="Modifica messaggio" @click="emit('edit', msg.id)">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                        stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                                    </svg>
                                </button>
                                <button v-if="msg.role === 'assistant' && !branchDisabled"
                                    class="drawer-msg__branch-btn" aria-label="Dirama da qui"
                                    @click="emit('branch', msg.id)">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                        stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                        <circle cx="6" cy="18" r="3" />
                                        <circle cx="6" cy="6" r="3" />
                                        <circle cx="18" cy="6" r="3" />
                                        <path d="M6 9v6" />
                                        <path d="M18 9a9 9 0 0 1-9 9" />
                                    </svg>
                                </button>
                                <span class="drawer__msg-time">{{ formatTime(msg.created_at) }}</span>
                            </div>
                        </div>
                        <div v-if="msg.role === 'tool'" class="drawer__msg-content drawer__msg-content--tool">
                            {{ truncateContent(msg.content) }}
                        </div>
                        <div v-else class="drawer__msg-content" v-html="renderMarkdown(msg.content || '')" />
                        <!-- Version navigator for user messages with multiple versions -->
                        <MessageVersionNav v-if="msg.role === 'user' && msg.version_group_id
                            && getVersionCount && getVersionCount(msg.version_group_id) > 1"
                            :active-index="getActiveVersionIndex?.(msg.version_group_id) ?? 0"
                            :total-versions="getVersionCount(msg.version_group_id)" :disabled="isStreaming" @switch="(idx) => {
                                if (msg.version_group_id) emit('switch-version', msg.version_group_id, idx)
                            }" />
                    </div>
                </div>
            </div>
        </Transition>
    </Teleport>
</template>

<style scoped>
/* ── Backdrop ── */
.drawer-backdrop {
    position: fixed;
    inset: 0;
    z-index: 900;
    background: rgba(0, 0, 0, 0.45);
    backdrop-filter: blur(2px);
    -webkit-backdrop-filter: blur(2px);
}

.drawer-backdrop-enter-active {
    transition: opacity 250ms var(--ease-smooth);
}

.drawer-backdrop-leave-active {
    transition: opacity 200ms ease;
}

.drawer-backdrop-enter-from,
.drawer-backdrop-leave-to {
    opacity: 0;
}

/* ── Drawer panel ── */
.drawer {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: min(420px, 85vw);
    z-index: 901;
    display: flex;
    flex-direction: column;
    background: var(--surface-1);
    border-right: 1px solid var(--border);
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.3);
}

.drawer-slide-enter-active {
    transition: transform 350ms var(--ease-out-expo);
}

.drawer-slide-leave-active {
    transition: transform 250ms var(--ease-smooth);
}

.drawer-slide-enter-from,
.drawer-slide-leave-to {
    transform: translateX(-100%);
}

/* ── Header ── */
.drawer__header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-4) var(--space-5);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
}

.drawer__title {
    font-size: var(--text-md);
    font-weight: var(--weight-medium);
    color: var(--text-primary);
    margin: 0;
}

.drawer__count {
    font-size: var(--text-2xs);
    color: var(--text-muted);
    background: var(--surface-3);
    padding: 1px 7px;
    border-radius: var(--radius-pill);
    font-variant-numeric: tabular-nums;
}

.drawer__close {
    margin-left: auto;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 150ms, color 150ms;
}

.drawer__close:hover {
    background: var(--surface-3);
    color: var(--text-primary);
}

/* ── Messages list ── */
.drawer__messages {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-3) var(--space-4);
}

.drawer__messages::-webkit-scrollbar {
    width: 4px;
}

.drawer__messages::-webkit-scrollbar-track {
    background: transparent;
}

.drawer__messages::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 2px;
}

.drawer__empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 120px;
    color: var(--text-muted);
    font-size: var(--text-sm);
}

/* ── Individual message ── */
.drawer__msg {
    padding: var(--space-2-5) var(--space-3);
    border-radius: var(--radius-sm);
    margin-bottom: var(--space-2);
    transition: background 150ms;
}

.drawer__msg:hover {
    background: var(--surface-2);
}

.drawer__msg--user {
    border-left: 2px solid var(--accent);
}

.drawer__msg--assistant {
    border-left: 2px solid var(--speaking, #2dd4bf);
}

.drawer__msg--tool {
    border-left: 2px solid var(--text-muted);
    opacity: 0.7;
}

.drawer__msg--system {
    border-left: 2px solid var(--thinking, #60a5fa);
    opacity: 0.6;
}

.drawer__msg-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: var(--space-1);
}

.drawer__msg-role {
    font-size: var(--text-2xs);
    font-weight: var(--weight-medium);
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

.drawer__msg-time {
    font-size: 10px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
}

.drawer__msg-content {
    font-size: var(--text-sm);
    line-height: var(--leading-relaxed);
    color: var(--text-primary);
    overflow-wrap: break-word;
    word-break: break-word;
}

.drawer__msg-content--tool {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    white-space: pre-wrap;
}

/* Markdown inside drawer messages */
.drawer__msg-content :deep(p) {
    margin: 0 0 0.5em;
    font-size: var(--text-sm);
}

.drawer__msg-content :deep(p:last-child) {
    margin-bottom: 0;
}

.drawer__msg-content :deep(pre) {
    font-size: var(--text-xs);
    margin: 0.5em 0;
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--surface-3);
    overflow-x: auto;
}

.drawer__msg-content :deep(code) {
    font-size: var(--text-xs);
}

.drawer__msg-content :deep(ul),
.drawer__msg-content :deep(ol) {
    margin: 0.3em 0;
    padding-left: 1.2em;
}

.drawer__msg-content :deep(li) {
    font-size: var(--text-sm);
    margin-bottom: 2px;
}

/* ── Edit & actions ── */
.drawer__msg-actions {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
}

.drawer__edit-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    padding: 0;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    opacity: 0;
    transition: opacity 150ms, color 150ms, background 150ms;
}

.drawer__msg:hover .drawer__edit-btn {
    opacity: 1;
}

.drawer__edit-btn:hover {
    color: var(--text-primary);
    background: var(--surface-3);
}

.drawer-msg__branch-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    padding: 0;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    opacity: 0;
    transition: opacity 150ms, color 150ms, background 150ms;
}

.drawer__msg:hover .drawer-msg__branch-btn {
    opacity: 1;
}

.drawer-msg__branch-btn:hover {
    color: var(--text-primary);
    background: var(--surface-3);
}
</style>
