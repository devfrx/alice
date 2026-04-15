<script setup lang="ts">
// AL\CE — Root App Component
import { onErrorCaptured, onMounted, provide, computed, ref, watchEffect } from 'vue'
import { useRouter } from 'vue-router'

import TitleBar from './components/TitleBar.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
import AppSidebar from './components/sidebar/AppSidebar.vue'
import ModalContainer from './components/ModalContainer.vue'
// ModeSwitcher is managed inside AssistantFab for assistant mode
import { UiToast, AliceLoader } from './components/ui'
import { useChat, ChatApiKey } from './composables/useChat'
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
const router = useRouter()

// Catch setup/render errors in child views (e.g. corrupted injection after HMR)
// and redirect to home instead of crashing the whole app.
onErrorCaptured((err) => {
  if (err instanceof Error && err.message.includes('not provided')) {
    console.warn('[App] Child view setup error caught, redirecting to home:', err.message)
    router.replace({ name: 'home' })
    return false
  }
})

// ── Startup loader ────────────────────────────────────────────────
const startupLoading = ref(true)

const startupMessage = computed(() => {
  switch (chatApi.connectionStatus.value) {
    case 'connecting': return 'Connessione al backend…'
    case 'error': return 'Errore di connessione…'
    default: return 'Avvio in corso…'
  }
})

watchEffect(() => {
  if (chatApi.isConnected.value) {
    startupLoading.value = false
  }
})

// Apply data-theme attribute to <html> so CSS variable overrides take effect.
watchEffect(() => {
  document.documentElement.setAttribute('data-theme', settingsStore.settings.ui.theme)
})

onMounted(() => {
  settingsStore.resumeOperationTracking()
  pluginsStore.loadPlugins()
  setTimeout(() => { startupLoading.value = false }, 10_000)
})
</script>

<template>
  <div id="alice-app" :class="`alice-app--${uiStore.mode}`">
    <TitleBar />
    <div v-if="settingsStore.isAnyOperationInProgress" class="global-operation-bar">
      <div class="global-operation-bar__track" role="progressbar" aria-label="Operazione modello in corso">
        <div class="global-operation-bar__fill" />
      </div>
      <span class="global-operation-bar__text">{{ settingsStore.operationDescription }}</span>
    </div>
    <div class="app-body">
      <main class="app-content">
        <ErrorBoundary>
          <router-view />
        </ErrorBoundary>
      </main>
    </div>
    <!-- Floating sidebar (renders its own backdrop) -->
    <AppSidebar />
    <!-- <ModeSwitcher v-if="uiStore.mode !== 'assistant'" /> NON ATTIVARE! -->
    <ModalContainer />
    <UiToast />
    <AliceLoader :visible="startupLoading" :message="startupMessage" />
  </div>
</template>

<style>
/* Theme tokens & global reset are loaded via main.css → styles/theme.css */

#alice-app {
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

/* ── Mode-specific adjustments ──────────────────────────────────── */
.alice-app--assistant .app-body {
  background: var(--surface-0);
}

.alice-app--assistant .app-content {
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
