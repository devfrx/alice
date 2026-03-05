<script setup lang="ts">
/**
 * AppSidebar.vue — Collapsible sidebar wrapping navigation and conversations.
 *
 * Layout:
 * - Top: navigation links (Chat, Settings)
 * - Middle: {@link ConversationList} (scrollable)
 * - Toggle button to collapse/expand (0 ↔ 260 px)
 *
 * The component owns no data — it reads from the Pinia chat store
 * and delegates mutations back through events / store actions.
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useChatStore } from '../../stores/chat'
import { api } from '../../services/api'
import ConversationList from './ConversationList.vue'

const chatStore = useChatStore()
const router = useRouter()

/** Whether the sidebar is expanded. */
const isOpen = ref(true)

/** Toggle collapsed state. */
function toggle(): void {
  isOpen.value = !isOpen.value
}

/** Load conversations on mount so the sidebar is populated immediately. */
onMounted(() => {
  chatStore.loadConversations().catch(console.error)
})

// -----------------------------------------------------------------------
// Conversation actions (delegated to store)
// -----------------------------------------------------------------------

/** Select an existing conversation and navigate to /chat. */
async function onSelect(id: string): Promise<void> {
  try {
    await chatStore.loadConversation(id)
  } catch (err) {
    // Graceful degradation — log the failure and stay on the current view
    // rather than leaving the UI in an inconsistent state.
    console.error(`[AppSidebar] Failed to load conversation ${id}:`, err)
    return
  }
  if (router.currentRoute.value.name !== 'chat') {
    await router.push({ name: 'chat' })
  }
}

/** Create a new conversation and navigate to /chat. */
async function onCreate(): Promise<void> {
  await chatStore.createConversation()
  if (router.currentRoute.value.name !== 'chat') {
    await router.push({ name: 'chat' })
  }
}

/** Delete a conversation. */
async function onDelete(id: string): Promise<void> {
  await chatStore.deleteConversation(id)
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
    <!-- Toggle button (always visible) -->
    <button class="sidebar__toggle" aria-label="Toggle sidebar" @click="toggle">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
        stroke-linecap="round" stroke-linejoin="round">
        <line x1="3" y1="6" x2="21" y2="6" />
        <line x1="3" y1="12" x2="21" y2="12" />
        <line x1="3" y1="18" x2="21" y2="18" />
      </svg>
    </button>

    <!-- Content (hidden when collapsed) -->
    <div v-show="isOpen" class="sidebar__content">
      <!-- Navigation -->
      <nav class="sidebar__nav">
        <router-link to="/chat" class="sidebar__link" active-class="sidebar__link--active">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span>Chat</span>
        </router-link>
        <router-link to="/settings" class="sidebar__link" active-class="sidebar__link--active">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3" />
            <path
              d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1.08 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1.08 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1.08z" />
          </svg>
          <span>Impostazioni</span>
        </router-link>
      </nav>

      <div class="sidebar__divider" />

      <!-- Conversation list -->
      <ConversationList :conversations="chatStore.conversations" :active-id="chatStore.currentConversation?.id ?? null"
        @select="onSelect" @create="onCreate" @delete="onDelete" @rename="onRename" @open-file="onOpenFile" />
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  box-shadow: 1px 0 8px rgba(0, 0, 0, 0.3);
  transition: width var(--transition-normal), min-width var(--transition-normal);
  overflow: hidden;
}

.sidebar--collapsed {
  width: var(--sidebar-collapsed);
  min-width: var(--sidebar-collapsed);
}

/* ------------------------------------------------- Toggle */
.sidebar__toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 36px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  transition: color var(--transition-fast), background var(--transition-fast);
}

.sidebar__toggle:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.05);
}

/* ------------------------------------------------- Content */
.sidebar__content {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

/* ------------------------------------------------- Navigation */
.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 8px;
}

.sidebar__link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  font-size: 0.84rem;
  color: var(--text-secondary);
  text-decoration: none;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.sidebar__link:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
}

.sidebar__link--active {
  color: var(--accent);
  background: var(--accent-dim);
}

/* ------------------------------------------------- Divider */
.sidebar__divider {
  height: 1px;
  margin: 4px 12px;
  background: var(--border);
}
</style>
