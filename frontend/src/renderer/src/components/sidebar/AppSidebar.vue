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
import { useRoute } from 'vue-router'

import { useChatStore } from '../../stores/chat'
import { useUIStore } from '../../stores/ui'
import { useEmailStore } from '../../stores/email'
import { useModal } from '../../composables/useModal'
import { useToast } from '../../composables/useToast'
import { chatApi } from '../../services/api'
import { commandRegistry } from '../../commands'
import BrandThemeToggle from '../branding/BrandThemeToggle.vue'
import BrandWordmark from '../branding/BrandWordmark.vue'
import ConversationList from './ConversationList.vue'
import CalendarWidget from '../calendar/CalendarWidget.vue'
import AppIcon from '../ui/AppIcon.vue'

/**
 * When `docked` is true the sidebar renders inline inside its parent frame
 * (see {@link DockedSidebar}) instead of as a floating overlay: no backdrop,
 * no fixed positioning, no slide animation, and the close button is hidden
 * (collapsing is handled by the docked frame). All content and conversation
 * actions are identical between modes.
 */
const props = withDefaults(defineProps<{ docked?: boolean }>(), { docked: false })

const chatStore = useChatStore()
const uiStore = useUIStore()
const emailStore = useEmailStore()
const route = useRoute()
const { confirm } = useModal()
const toast = useToast()

const unreadBadge = computed(() => emailStore.unreadCount)

/** True while Horizon (`/assistant`), the only chat surface, is on screen. */
const isAssistantActive = computed(() => route.name === 'assistant')

/**
 * The Home affordance is "fresh conversation on the primary surface": active
 * exactly when Horizon is on screen with an empty conversation.
 */
const isHomeActive = computed(
  () =>
    isAssistantActive.value &&
    chatStore.messages.length === 0 &&
    !chatStore.isStreamingCurrentConversation
)

/**
 * Whether the sidebar body is shown.
 * - Docked: always rendered; the parent frame controls visibility/width.
 * - Floating overlay: driven by the central UI store open state.
 */
const isOpen = computed(() => props.docked || uiStore.sidebarOpen)

/**
 * Close affordance. In floating mode this toggles the overlay; in docked mode
 * nav links call this on click but we must NOT close the docked sidebar, so it
 * is a no-op there (collapse is handled by the frame / TitleBar toggle).
 */
function toggle(): void {
  if (props.docked) return
  uiStore.toggleSidebar()
}

// Conversations are loaded by useChat's onConnected handler after the
// WebSocket connects; no need to fire a potentially premature REST call here.

// -----------------------------------------------------------------------
// Conversation actions (delegated to store)
// -----------------------------------------------------------------------

/** Select an existing conversation via the command layer. */
async function onSelect(id: string): Promise<void> {
  try {
    await commandRegistry.execute('conversation.open', { conversation_id: id })
  } catch (err) {
    console.error(`[AppSidebar] Failed to open conversation ${id}:`, err)
  }
}

/**
 * Go to the Home affordance — a fresh conversation on Horizon via the command
 * layer; reuses an already-empty conversation by only creating when the
 * current one has content.
 */
async function onHome(): Promise<void> {
  toggle()
  try {
    if (chatStore.messages.length > 0) {
      await commandRegistry.execute('conversation.new', {})
    } else {
      await commandRegistry.execute('view.switch', { view: 'assistant' })
    }
  } catch (err) {
    console.error('[AppSidebar] Home action failed:', err)
  }
}

/**
 * Start a new conversation on the Home — the empty-conversation state of
 * Horizon. A fresh conversation always opens as the Home (never a stale
 * secondary route); typing the first message then cross-fades it into the
 * live conversation. `createConversation` reuses any existing empty
 * conversation, so this never leaves a trail of blank chats.
 */
async function onCreate(): Promise<void> {
  try {
    await commandRegistry.execute('conversation.new', {})
  } catch (err) {
    console.error('[AppSidebar] Failed to start a new conversation:', err)
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

/** Export a single conversation as JSON into a user-chosen directory. */
async function onExportConversation(id: string): Promise<void> {
  try {
    const dir = await window.electron.fileOps.selectDirectory()
    if (!dir) return
    const res = await chatApi.backupConversations(dir, [id])
    if (res.exported === 0) {
      toast.warning('Conversazione non trovata sul backend: nessun file esportato')
      return
    }
    window.electron.fileOps.showInFolder(`${res.path}/${id}.json`)
  } catch (err) {
    console.error(`[AppSidebar] Failed to export conversation ${id}:`, err)
    toast.error("Esportazione fallita: impossibile completare l'export")
  }
}

/** Backup ALL conversations as JSON files into a user-chosen directory. */
async function onBackupAll(): Promise<void> {
  try {
    const dir = await window.electron.fileOps.selectDirectory()
    if (!dir) return
    const res = await chatApi.backupConversations(dir)
    if (res.exported === 0) {
      toast.warning('Nessuna conversazione da esportare')
      return
    }
    toast.success(`Esportate ${res.exported} conversazioni`)
    window.electron.fileOps.showInFolder(res.path)
  } catch (err) {
    console.error('[AppSidebar] Failed to backup conversations:', err)
    toast.error('Backup fallito: impossibile completare l\'export')
  }
}
</script>

<template>
  <div class="sidebar__root" :class="{ 'sidebar__root--docked': props.docked }">
    <!-- Backdrop overlay — click to close (floating overlay mode only) -->
    <Transition v-if="!props.docked" name="sidebar-backdrop">
      <div v-if="isOpen" class="sidebar__backdrop" @click="toggle" />
    </Transition>

    <!-- Sidebar panel: floating (overlay) or docked (inline frame) -->
    <Transition :name="props.docked ? '' : 'sidebar-slide'">
      <aside v-if="isOpen" class="sidebar" :class="{ 'sidebar--docked': props.docked }">
        <!-- Header with close button (close hidden when docked) -->
        <div class="sidebar__header">
          <span class="sidebar__brand">
            <BrandWordmark brand="alce" />
          </span>
          <button v-if="!props.docked" class="sidebar__close" aria-label="Chiudi sidebar" @click="toggle">
            <AppIcon name="x" :size="14" :stroke-width="2.5" />
          </button>
        </div>

        <!-- Secondary navigation (tools) -->
        <nav class="sidebar__nav" aria-label="Navigazione principale">
          <button type="button" class="sidebar__link" :class="{ 'sidebar__link--active': isHomeActive }"
            title="Home" @click="onHome">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="home" :size="15" />
            </span>
            <span class="sidebar__link-label">Home</span>
          </button>

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

          <router-link to="/terminal" class="sidebar__link" active-class="sidebar__link--active" title="Terminale"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="terminal" :size="15" />
            </span>
            <span class="sidebar__link-label">Terminale</span>
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
            @export="onExportConversation" @backup-all="onBackupAll" />
        </div>

        <!-- Footer: settings -->
        <div class="sidebar__footer">
          <div class="sidebar__theme-row">
            <span class="sidebar__theme-label">Tema</span>
            <BrandThemeToggle />
          </div>

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
  /* Solid, fully-opaque surface — no glass / semi-transparency. */
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 20px;
  box-shadow: var(--panel-shadow, var(--shadow-md));
  z-index: calc(var(--z-overlay) - 1);
  overflow: hidden;
}

/* ── Docked mode: fill the parent frame, no overlay chrome ───────── */
.sidebar__root--docked {
  width: 100%;
  height: 100%;
}

/*
 * Docked mode: fill the parent DockedSidebar frame, which now provides the
 * floating card chrome (surface, border, radius, shadow). The sidebar itself
 * is transparent and inherits the frame's rounded clip; its inner sections
 * (nav / conversations / footer) scroll within the card.
 */
.sidebar--docked {
  position: relative;
  top: auto;
  left: auto;
  width: 100%;
  height: 100%;
  border: none;
  border-radius: inherit;
  box-shadow: none;
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  z-index: auto;
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
  display: inline-flex;
  align-items: center;
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  letter-spacing: 0;
  color: var(--text-primary);
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

/* ── Footer (impostazioni) ─────────────────────────────────── */
.sidebar__footer {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3) var(--space-3);
  flex-shrink: 0;
}

.sidebar__theme-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: var(--input-height-md);
  padding: 0 var(--space-3);
}

.sidebar__theme-label {
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  letter-spacing: 0;
}

.sidebar__theme-row :deep(.brand-theme-toggle) {
  flex: 0 0 auto;
}

.sidebar__link--footer {
  color: var(--text-muted);
}

.sidebar__link--footer:hover {
  color: var(--text-secondary);
}

/* Nav link — shared by <router-link> (<a>) and the Home <button>. */
.sidebar__link {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  font-family: inherit;
  font-size: var(--text-sm);
  font-weight: var(--weight-regular);
  color: var(--text-secondary);
  text-align: left;
  text-decoration: none;
  cursor: pointer;
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
  outline: none;
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
