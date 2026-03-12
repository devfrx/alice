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
import { useModal } from '../../composables/useModal'
import { api } from '../../services/api'
import ConversationList from './ConversationList.vue'
import CalendarWidget from '../calendar/CalendarWidget.vue'

const chatStore = useChatStore()
const uiStore = useUIStore()
const router = useRouter()
const { confirm } = useModal()

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

/** Select an existing conversation and navigate to hybrid mode. */
async function onSelect(id: string): Promise<void> {
  try {
    await chatStore.loadConversation(id)
  } catch (err) {
    // Graceful degradation — log the failure and stay on the current view
    // rather than leaving the UI in an inconsistent state.
    console.error(`[AppSidebar] Failed to load conversation ${id}:`, err)
    return
  }
  if (router.currentRoute.value.name !== 'hybrid') {
    await router.push({ name: 'hybrid' })
  }
}

/** Create a new conversation and navigate to hybrid mode. */
async function onCreate(): Promise<void> {
  await chatStore.createConversation()
  if (router.currentRoute.value.name !== 'hybrid') {
    await router.push({ name: 'hybrid' })
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
  <aside class="sidebar" :class="{ 'sidebar--collapsed': !isOpen }">

    <!-- Primary navigation — icons always visible, labels hidden when collapsed -->
    <nav class="sidebar__nav" aria-label="Navigazione principale">
      <router-link to="/settings" class="sidebar__link" active-class="sidebar__link--active" title="Impostazioni">
        <span class="sidebar__link-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3" />
            <path
              d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1.08 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1.08 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1.08z" />
          </svg>
        </span>
        <span class="sidebar__link-label">Impostazioni</span>
      </router-link>

      <router-link to="/assistant" class="sidebar__link" active-class="sidebar__link--active" title="Assistente">
        <span class="sidebar__link-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" />
            <circle cx="12" cy="12" r="4" />
          </svg>
        </span>
        <span class="sidebar__link-label">Assistente</span>
      </router-link>

      <router-link to="/hybrid" class="sidebar__link" active-class="sidebar__link--active" title="Ibrido">
        <span class="sidebar__link-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="8" r="6" />
            <path d="M4 20h16" opacity="0.5" />
          </svg>
        </span>
        <span class="sidebar__link-label">Ibrido</span>
      </router-link>
    </nav>

    <!-- Calendar widget — shows today's events and next upcoming -->
    <CalendarWidget :collapsed="!isOpen" />

    <!-- Conversations section — only shown when expanded -->
    <div v-show="isOpen" class="sidebar__conversations">
      <!-- Section divider with micro uppercase label -->
      <div class="sidebar__section-label">
        <span>Conversazioni</span>
      </div>

      <!-- Virtualised conversation list -->
      <ConversationList :conversations="chatStore.conversations" :active-id="chatStore.currentConversation?.id ?? null"
        :streaming-id="chatStore.streamingConversationId" @select="onSelect" @create="onCreate" @delete="onDelete"
        @delete-all="onDeleteAll" @rename="onRename" @open-file="onOpenFile" />
    </div>

    <!-- Toggle button — bottom of sidebar, circular chevron -->
    <button class="sidebar__toggle" :aria-label="isOpen ? 'Chiudi sidebar' : 'Apri sidebar'" :aria-expanded="isOpen"
      @click="toggle">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
        stroke-linecap="round" stroke-linejoin="round">
        <polyline v-if="isOpen" points="15 18 9 12 15 6" />
        <polyline v-else points="9 18 15 12 9 6" />
      </svg>
    </button>
  </aside>
</template>

<style scoped>
/* ─── AppSidebar — Supabase-style flat sidebar ─── */

/* Root */
.sidebar {
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  overflow: hidden;
  position: relative;
  z-index: var(--z-sticky);
  transition:
    width var(--transition-normal) ease,
    min-width var(--transition-normal) ease;
}

.sidebar--collapsed {
  width: var(--sidebar-collapsed);
  min-width: var(--sidebar-collapsed);
}

/* Navigation */
.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-4) var(--space-3) var(--space-3);
  flex-shrink: 0;
  transition: padding var(--transition-normal) ease;
}

.sidebar--collapsed .sidebar__nav {
  padding: var(--space-4) var(--space-1) var(--space-3);
  align-items: center;
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

/* Active state — subtle bg fill only, no accent bar */
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

/* Collapsed link — centered icon circle */
.sidebar--collapsed .sidebar__link {
  justify-content: center;
  gap: 0;
  padding: var(--space-2);
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  margin: 0 auto;
}

.sidebar--collapsed .sidebar__link--active {
  background: var(--surface-active);
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

/* Label — collapses with width + opacity */
.sidebar__link-label {
  white-space: nowrap;
  overflow: hidden;
  max-width: 160px;
  opacity: 1;
  transition:
    opacity var(--transition-normal) ease,
    max-width var(--transition-normal) ease;
}

.sidebar--collapsed .sidebar__link-label {
  opacity: 0;
  max-width: 0;
  pointer-events: none;
}

/* Conversations section */
.sidebar__conversations {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

/* Section label — simple uppercase micro text with border line */
.sidebar__section-label {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4) var(--space-2);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  flex-shrink: 0;
  border-top: 1px solid var(--border);
}

.sidebar__section-label::after {
  content: none;
}

/* Toggle button — minimal */
.sidebar__toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
  margin: var(--space-2) auto var(--space-3);
  transition:
    color var(--transition-fast) ease,
    background var(--transition-fast) ease;
}

.sidebar__toggle:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}

.sidebar__toggle:focus-visible {
  box-shadow: var(--focus-ring-shadow);
}

/* Scrollbar — thin, subtle */
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

/* Reduced motion */
@media (prefers-reduced-motion: reduce) {

  .sidebar,
  .sidebar__nav,
  .sidebar__link,
  .sidebar__link-icon,
  .sidebar__link-label,
  .sidebar__toggle {
    transition: none;
  }
}
</style>
