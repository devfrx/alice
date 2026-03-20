<script setup lang="ts">
/**
 * AppSidebar.vue — Collapsible sidebar wrapping navigation and conversations.
 *
 * Layout:
 * - Top: navigation links (Settings)
 * - Middle: {@link ConversationList} (scrollable)
 * - Toggle button to collapse/expand (0 ↔ 260 px)
 *
 * The component owns no data — it reads from the Pinia chat store
 * and delegates mutations back through events / store actions.
 */
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useChatStore } from '../../stores/chat'
import { useUIStore } from '../../stores/ui'
import { useEmailStore } from '../../stores/email'
import { useModal } from '../../composables/useModal'
import { api } from '../../services/api'
import ConversationList from './ConversationList.vue'
import CalendarWidget from '../calendar/CalendarWidget.vue'

const chatStore = useChatStore()
const uiStore = useUIStore()
const emailStore = useEmailStore()
const router = useRouter()
const { confirm } = useModal()

const unreadBadge = computed(() => emailStore.unreadCount)

/** Whether the sidebar is expanded (wired to central UI store). */
const isOpen = computed(() => uiStore.sidebarOpen)

/** Toggle collapsed state via central UI store. */
function toggle(): void {
  uiStore.toggleSidebar()
}

/** Load conversations on mount so the sidebar is populated immediately. */
onMounted(() => {
  chatStore.loadConversations().catch(console.error)
})

// -----------------------------------------------------------------------
// Conversation actions (delegated to store)
// -----------------------------------------------------------------------

/** Select an existing conversation — stay in the current mode. */
async function onSelect(id: string): Promise<void> {
  try {
    await chatStore.loadConversation(id)
  } catch (err) {
    console.error(`[AppSidebar] Failed to load conversation ${id}:`, err)
    return
  }
  const current = router.currentRoute.value.name as string
  if (current !== 'assistant' && current !== 'hybrid') {
    await router.push({ name: uiStore.mode })
  }
}

/** Create a new conversation — stay in the current mode. */
async function onCreate(): Promise<void> {
  await chatStore.createConversation()
  const current = router.currentRoute.value.name as string
  if (current !== 'assistant' && current !== 'hybrid') {
    await router.push({ name: uiStore.mode })
  }
}

/** Delete a conversation. */
async function onDelete(id: string): Promise<void> {
  await chatStore.deleteConversation(id)
}

/** Delete ALL conversations (with confirmation). */
let deleteAllPending = false
async function onDeleteAll(): Promise<void> {
  if (deleteAllPending) return
  deleteAllPending = true
  try {
    const confirmed = await confirm({
      title: 'Elimina tutte le conversazioni',
      message: 'Eliminare tutte le conversazioni? Questa azione è irreversibile.',
      type: 'danger',
      confirmText: 'Elimina tutto',
    })
    if (!confirmed) return
    await chatStore.deleteAllConversations()
  } catch (err) {
    console.error('[AppSidebar] Failed to delete all conversations:', err)
  } finally {
    deleteAllPending = false
  }
}

/** Rename a conversation. */
async function onRename(id: string, title: string): Promise<void> {
  await chatStore.renameConversation(id, title)
}

/** Open the conversation file in the system file manager. */
async function onOpenFile(id: string): Promise<void> {
  try {
    const { path } = await api.getConversationFilePath(id)
    window.electron.fileOps.showInFolder(path)
  } catch (err) {
    console.error(`[AppSidebar] Failed to open file for conversation ${id}:`, err)
  }
}
</script>

<template>
  <div class="sidebar__root">
    <!-- Backdrop overlay — click to close -->
    <Transition name="sidebar-backdrop">
      <div v-if="isOpen" class="sidebar__backdrop" @click="toggle" />
    </Transition>

    <!-- Floating sidebar panel -->
    <Transition name="sidebar-slide">
      <aside v-if="isOpen" class="sidebar">
        <!-- Header with close button -->
        <div class="sidebar__header">
          <span class="sidebar__brand">O.M.N.I.A.</span>
          <button class="sidebar__close" aria-label="Chiudi sidebar" @click="toggle">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
              stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <!-- Primary navigation -->
        <nav class="sidebar__nav" aria-label="Navigazione principale">
          <router-link to="/settings" class="sidebar__link" active-class="sidebar__link--active" title="Impostazioni"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3" />
                <path
                  d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1.08 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1.08 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1.08z" />
              </svg>
            </span>
            <span class="sidebar__link-label">Impostazioni</span>
          </router-link>

          <router-link to="/assistant" class="sidebar__link" active-class="sidebar__link--active" title="Assistente"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10" />
                <circle cx="12" cy="12" r="4" />
              </svg>
            </span>
            <span class="sidebar__link-label">Assistente</span>
          </router-link>

          <router-link to="/hybrid" class="sidebar__link" active-class="sidebar__link--active" title="Ibrido"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="8" r="6" />
                <path d="M4 20h16" opacity="0.5" />
              </svg>
            </span>
            <span class="sidebar__link-label">Ibrido</span>
          </router-link>

          <router-link to="/notes" class="sidebar__link" active-class="sidebar__link--active" title="Note"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
                <polyline points="10 9 9 9 8 9" />
              </svg>
            </span>
            <span class="sidebar__link-label">Note</span>
          </router-link>

          <router-link to="/email" class="sidebar__link" active-class="sidebar__link--active" title="Email"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="2" y="4" width="20" height="16" rx="2" />
                <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
              </svg>
            </span>
            <span class="sidebar__link-label">Email</span>
            <span v-if="unreadBadge" class="sidebar__badge">{{ unreadBadge }}</span>
          </router-link>
        </nav>

        <!-- Calendar widget — shows today's events and next upcoming -->
        <CalendarWidget :collapsed="false" />

        <!-- Conversations section -->
        <div class="sidebar__conversations">
          <div class="sidebar__section-label">
            <span>Conversazioni</span>
          </div>

          <ConversationList :conversations="chatStore.conversations"
            :active-id="chatStore.currentConversation?.id ?? null" :streaming-id="chatStore.streamingConversationId"
            @select="onSelect" @create="onCreate" @delete="onDelete" @delete-all="onDeleteAll" @rename="onRename"
            @open-file="onOpenFile" />
        </div>
      </aside>
    </Transition>
  </div>
</template>

<style scoped>
/* ─── AppSidebar — Floating glass panel ─── */

/* Backdrop overlay */
.sidebar__backdrop {
  position: fixed;
  inset: 0;
  top: var(--titlebar-height, 38px);
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  z-index: calc(var(--z-overlay) - 2);
}

.sidebar-backdrop-enter-active,
.sidebar-backdrop-leave-active {
  transition: opacity 0.3s ease;
}

.sidebar-backdrop-enter-from,
.sidebar-backdrop-leave-to {
  opacity: 0;
}

/* Sidebar panel */
.sidebar {
  position: fixed;
  top: calc(var(--titlebar-height, 38px) + 8px);
  left: 12px;
  width: 280px;
  height: calc(100vh - var(--titlebar-height, 38px) - 16px);
  display: flex;
  flex-direction: column;
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur-heavy));
  -webkit-backdrop-filter: blur(var(--glass-blur-heavy));
  border: 1px solid var(--glass-border);
  border-radius: 20px;
  box-shadow: var(--shadow-floating);
  z-index: calc(var(--z-overlay) - 1);
  overflow: hidden;
}

/* Slide animation */
.sidebar-slide-enter-active {
  transition: transform 0.3s var(--ease-out-expo);
}

.sidebar-slide-leave-active {
  transition: transform 0.25s var(--ease-decel);
}

.sidebar-slide-enter-from,
.sidebar-slide-leave-to {
  transform: translateX(calc(-100% - 12px));
}

/* Header */
.sidebar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-4) var(--space-3);
  flex-shrink: 0;
}

.sidebar__brand {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 3px;
  color: var(--text-muted);
  text-transform: uppercase;
}

.sidebar__close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.sidebar__close:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}

/* Navigation */
.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  padding: 0 var(--space-3) var(--space-3);
  flex-shrink: 0;
}

/* Nav link */
.sidebar__link {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: var(--weight-regular);
  color: var(--text-secondary);
  text-decoration: none;
  transition:
    background var(--transition-fast) ease,
    color var(--transition-fast) ease;
}

.sidebar__link:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.sidebar__link:hover .sidebar__link-icon {
  color: var(--text-primary);
}

/* Active state */
.sidebar__link--active {
  background: var(--surface-selected);
  color: var(--text-primary);
}

.sidebar__link--active .sidebar__link-icon {
  color: var(--text-primary);
}

.sidebar__link:focus-visible {
  box-shadow: var(--focus-ring-shadow);
}

/* Icon */
.sidebar__link-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--text-muted);
  transition: color var(--transition-fast) ease;
}

/* Label */
.sidebar__link-label {
  white-space: nowrap;
}

/* Conversations section */
.sidebar__conversations {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

/* Section label */
.sidebar__section-label {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4) var(--space-2);
  margin-top: var(--space-2);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  flex-shrink: 0;
  border-top: 1px solid var(--border);
}

/* Scrollbar */
.sidebar :deep(::-webkit-scrollbar) {
  width: 4px;
}

.sidebar :deep(::-webkit-scrollbar-track) {
  background: transparent;
}

.sidebar :deep(::-webkit-scrollbar-thumb) {
  background: var(--surface-3);
  border-radius: var(--radius-pill);
}

.sidebar :deep(::-webkit-scrollbar-thumb:hover) {
  background: var(--surface-4);
}

/* Badge */
.sidebar__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--accent);
  color: var(--bg-primary);
  font-size: 0.65rem;
  font-weight: 700;
  line-height: 1;
  margin-left: auto;
}

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {

  .sidebar,
  .sidebar__backdrop,
  .sidebar__link,
  .sidebar__link-icon,
  .sidebar__close,
  .sidebar-slide-enter-active,
  .sidebar-slide-leave-active,
  .sidebar-backdrop-enter-active,
  .sidebar-backdrop-leave-active {
    transition: none;
  }
}
</style>
