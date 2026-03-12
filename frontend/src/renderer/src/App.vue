<script setup lang="ts">
// O.M.N.I.A. — Root App Component
import { onMounted, provide, computed } from 'vue'

import TitleBar from './components/TitleBar.vue'
import AppSidebar from './components/sidebar/AppSidebar.vue'
import ModalContainer from './components/ModalContainer.vue'
import ModeSwitcher from './components/assistant/ModeSwitcher.vue'
import { UiToast } from './components/ui'
import { useChat, ChatApiKey } from './composables/useChat'
import { usePluginComponents } from './composables/usePluginComponents'
import { useEventsWebSocket } from './composables/useEventsWebSocket'
import { useSettingsStore } from './stores/settings'
import { useUIStore } from './stores/ui'
import { usePluginsStore } from './stores/plugins'

const chatApi = useChat()
provide(ChatApiKey, chatApi)

// Persistent WebSocket for real-time calendar and backend events.
useEventsWebSocket()

const settingsStore = useSettingsStore()
const uiStore = useUIStore()
const pluginsStore = usePluginsStore()
const { toolbarComponents } = usePluginComponents()

/** Always show sidebar (collapsed in assistant mode). */
const showSidebar = computed(() => true)

onMounted(() => {
  settingsStore.resumeOperationTracking()
  pluginsStore.loadPlugins()
})
</script>

<template>
  <div id="omnia-app" :class="`omnia-app--${uiStore.mode}`"
    :style="{ '--sidebar-offset': uiStore.sidebarOpen ? 'var(--sidebar-width)' : 'var(--sidebar-collapsed)' }">
    <TitleBar />
    <!-- Plugin toolbar mount point -->
    <div v-if="toolbarComponents.length" class="plugin-toolbar">
      <component v-for="entry in toolbarComponents" :is="entry.component" :key="entry.name" />
    </div>
    <div v-if="settingsStore.isAnyOperationInProgress" class="global-operation-bar">
      <div class="global-operation-bar__track" role="progressbar" aria-label="Operazione modello in corso">
        <div class="global-operation-bar__fill" />
      </div>
      <span class="global-operation-bar__text">{{ settingsStore.operationDescription }}</span>
    </div>
    <div class="app-body">
      <AppSidebar v-if="showSidebar" />
      <main class="app-content">
        <router-view />
      </main>
    </div>
    <ModeSwitcher />
    <ModalContainer />
    <UiToast />
  </div>
</template>

<style>
/* Theme tokens & global reset are loaded via main.css → styles/theme.css */

#omnia-app {
  width: 100vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.app-content {
  flex: 1;
  overflow: hidden;
}

/* ── Global operation indicator bar ─────────────────────────────── */
.global-operation-bar {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: var(--surface-1);
  border-bottom: 1px solid var(--border);
  padding: 0 0 var(--space-1);
  flex-shrink: 0;
}

.global-operation-bar__track {
  width: 100%;
  height: 2px;
  background: var(--surface-inset);
  overflow: hidden;
}

.global-operation-bar__fill {
  width: 40%;
  height: 100%;
  background: var(--accent);
  border-radius: var(--space-0-5);
  animation: globalOpSlide 1.4s ease-in-out infinite;
}

@keyframes globalOpSlide {
  0% {
    transform: translateX(-100%);
  }

  50% {
    transform: translateX(200%);
  }

  100% {
    transform: translateX(-100%);
  }
}

.global-operation-bar__text {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  margin-top: var(--space-0-5);
  letter-spacing: var(--tracking-tight);
}

/* ── Plugin toolbar mount point ─────────────────────────────────── */
.plugin-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-4);
  background: var(--surface-1);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

/* ── Mode-specific adjustments ──────────────────────────────────── */
.omnia-app--assistant .app-body {
  background: var(--surface-0);
}

.omnia-app--assistant .app-content {
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
