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
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { useChatStore } from '../../stores/chat'
import { useUIStore } from '../../stores/ui'
import { useEmailStore } from '../../stores/email'
import { useModal } from '../../composables/useModal'
import { api } from '../../services/api'
import ConversationList from './ConversationList.vue'
import CalendarWidget from '../calendar/CalendarWidget.vue'
import AppIcon from '../ui/AppIcon.vue'

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

// Conversations are loaded by useChat's onConnected handler after the
// WebSocket connects; no need to fire a potentially premature REST call here.

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
    try {
      await router.push({ name: uiStore.mode })
    } catch (err) {
      console.error('[AppSidebar] Navigation failed, falling back to home:', err)
      await router.replace({ name: 'home' }).catch(() => { })
    }
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
          <span class="sidebar__brand">AL\CE</span>
          <button class="sidebar__close" aria-label="Chiudi sidebar" @click="toggle">
            <AppIcon name="x" :size="14" :stroke-width="2.5" />
          </button>
        </div>

        <!-- Mode switcher tabs: Assistente / Ibrido -->
        <div class="sidebar__mode-tabs">
          <router-link to="/assistant" class="sidebar__mode-tab" active-class="sidebar__mode-tab--active"
            @click="toggle">
            <AppIcon name="orb" :size="14" />
            <span>Assistente</span>
          </router-link>
          <router-link to="/hybrid" class="sidebar__mode-tab" active-class="sidebar__mode-tab--active" @click="toggle">
            <AppIcon name="hybrid-sidebar" :size="14" />
            <span>Ibrido</span>
          </router-link>
        </div>

        <!-- Secondary navigation (tools) -->
        <nav class="sidebar__nav" aria-label="Navigazione principale">
          <router-link to="/notes" class="sidebar__link" active-class="sidebar__link--active" title="Note"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="file-text" :size="15" />
            </span>
            <span class="sidebar__link-label">Note</span>
          </router-link>

          <router-link to="/whiteboard" class="sidebar__link" active-class="sidebar__link--active" title="Lavagna"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="whiteboard-card" :size="15" />
            </span>
            <span class="sidebar__link-label">Lavagna</span>
          </router-link>

          <router-link to="/board" class="sidebar__link" active-class="sidebar__link--active" title="Bacheca artefatti"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="bookmark" :size="15" />
            </span>
            <span class="sidebar__link-label">Bacheca</span>
          </router-link>

          <router-link to="/email" class="sidebar__link" active-class="sidebar__link--active" title="Email"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="email" :size="15" />
            </span>
            <span class="sidebar__link-label">Email</span>
            <span v-if="unreadBadge" class="sidebar__badge">{{ unreadBadge }}</span>
          </router-link>

          <router-link to="/services" class="sidebar__link" active-class="sidebar__link--active" title="Servizi"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="server" :size="15" />
            </span>
            <span class="sidebar__link-label">Servizi</span>
          </router-link>
        </nav>

        <!-- Calendar widget -->
        <CalendarWidget :collapsed="false" />

        <!-- Conversations section -->
        <div class="sidebar__conversations">
          <ConversationList :conversations="chatStore.conversations"
            :active-id="chatStore.currentConversation?.id ?? null" :streaming-id="chatStore.streamingConversationId"
            @select="onSelect" @create="onCreate" @delete="onDelete" @delete-all="onDeleteAll" @rename="onRename"
            @open-file="onOpenFile" />
        </div>

        <!-- Footer: settings -->
        <div class="sidebar__footer">
          <router-link to="/settings" class="sidebar__link sidebar__link--footer" active-class="sidebar__link--active"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="settings" :size="15" />
            </span>
            <span class="sidebar__link-label">Impostazioni</span>
          </router-link>
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
  background: var(--black-light);
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
  /* Navigation chrome — text in nav items must not be selectable */
  user-select: none;
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
  padding: 0 var(--space-3) var(--space-2);
  flex-shrink: 0;
}

/* ── Mode tabs (Assistente / Ibrido) ───────────────────────── */
.sidebar__mode-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  margin: 0 var(--space-3) var(--space-3);
  padding: 3px;
  background: var(--surface-2);
  border-radius: var(--radius-md);
  border: 1px solid var(--glass-border);
  flex-shrink: 0;
}

.sidebar__mode-tab {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1-5);
  padding: 6px var(--space-2);
  border-radius: calc(var(--radius-md) - 3px);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--text-muted);
  text-decoration: none;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    box-shadow var(--transition-fast);
  white-space: nowrap;
}

.sidebar__mode-tab:hover {
  color: var(--text-secondary);
  background: var(--surface-hover);
}

.sidebar__mode-tab--active {
  background: var(--surface-4);
  color: var(--text-primary);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}

/* ── Footer (impostazioni) ─────────────────────────────────── */
.sidebar__footer {
  padding: var(--space-2) var(--space-3) var(--space-3);
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

.sidebar__link--footer {
  color: var(--text-muted);
}

.sidebar__link--footer:hover {
  color: var(--text-secondary);
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

/* Badge — unread count indicator */
.sidebar__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: var(--space-4);
  height: var(--space-4);
  padding: 0 var(--space-1);
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: var(--bg-primary);
  font-size: var(--text-2xs);
  font-weight: var(--weight-bold);
  line-height: 1;
  margin-left: auto;
  font-variant-numeric: tabular-nums;
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
