<script setup lang="ts">
// AL\CE — Root App Component
import { onErrorCaptured, onMounted, onUnmounted, provide, computed, ref, watchEffect } from 'vue'
import { useRouter, useRoute } from 'vue-router'

import TitleBar from './components/TitleBar.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
import DockedSidebar from './components/sidebar/DockedSidebar.vue'
import ModalContainer from './components/ModalContainer.vue'
import { UiToast, AliceLoader } from './components/ui'
import { useChat, ChatApiKey } from './composables/useChat'
import { useEventsWebSocket } from './composables/useEventsWebSocket'
import { useSettingsStore } from './stores/settings'
import { usePluginsStore } from './stores/plugins'
import { waitForBackend } from './services/api'
import { installCoreCommands, installDeskCommands } from './commands'

const chatApi = useChat()
provide(ChatApiKey, chatApi)

// Persistent WebSocket for real-time calendar and backend events.
const eventsWs = useEventsWebSocket()

const settingsStore = useSettingsStore()
const pluginsStore = usePluginsStore()
const router = useRouter()
const route = useRoute()

// Register the core UI commands for the app lifetime (spec §7 registry; the
// agent-facing manifest arrives in Fase 7). The install is idempotent — it
// re-registers the core set — so an HMR re-run of this setup block swaps in
// fresh handler closures instead of throwing or keeping stale ones.
installCoreCommands(router)
installDeskCommands(router)

/**
 * Horizon chrome (centered layout + surface-0 backdrop) is keyed off the
 * ACTIVE ROUTE: it applies only while `/assistant` — the only chat surface —
 * is on screen, never on secondary routes (mail/calendar/settings/…).
 */
const isAssistantRoute = computed(() => route.name === 'assistant')

// Catch setup/render errors in child views (e.g. corrupted injection after HMR)
// and redirect to home instead of crashing the whole app.
onErrorCaptured((err) => {
  if (err instanceof Error && err.message.includes('not provided')) {
    console.warn('[App] Child view setup error caught, redirecting to home:', err.message)
    router.replace({ name: 'home' })
    return false
  }
  return undefined
})

// ── Startup loader ────────────────────────────────────────────────
const startupLoading = ref(true)
const backendReady = ref(false)

const startupMessage = computed(() => {
  if (!backendReady.value) return 'In attesa del backend…'
  switch (chatApi.connectionStatus.value) {
    case 'connecting':
      return 'Connessione al backend…'
    case 'error':
      return 'Errore di connessione…'
    default:
      return 'Caricamento dati…'
  }
})

// Apply data-theme attribute to <html> so CSS variable overrides take effect.
watchEffect(() => {
  document.documentElement.setAttribute('data-theme', settingsStore.settings.ui.theme)
})

// AbortController so we can cancel the health poll if the component unmounts.
let startupAbort: AbortController | null = null

onMounted(async () => {
  startupAbort = new AbortController()

  // 1. Wait for backend to be reachable
  const ready = await waitForBackend(1000, startupAbort.signal)
  if (!ready) return // component was unmounted
  backendReady.value = true

  // 2. Connect WebSockets now that the backend is up
  const { wsManager } = await import('./services/ws')
  wsManager.connect()
  eventsWs.connect()

  // 3. Load all stores in parallel
  await Promise.all([
    settingsStore.initialize(),
    pluginsStore.loadPlugins(),
    settingsStore.resumeOperationTracking()
  ])

  // 4. Guard: component may have unmounted during async ops
  if (startupAbort.signal.aborted) return

  startupLoading.value = false
})

onUnmounted(() => {
  startupAbort?.abort()
})
</script>

<template>
  <div id="alice-app" :class="{ 'alice-app--assistant': isAssistantRoute }">
    <TitleBar />
    <div v-if="settingsStore.isAnyOperationInProgress" class="global-operation-bar">
      <div
        class="global-operation-bar__track"
        role="progressbar"
        aria-label="Operazione modello in corso"
      >
        <div class="global-operation-bar__fill" />
      </div>
      <span class="global-operation-bar__text">{{ settingsStore.operationDescription }}</span>
    </div>
    <div class="app-body">
      <!-- Docked, resizable, collapsible sidebar (hosts AppSidebar inline) -->
      <DockedSidebar />
      <main class="app-content">
        <ErrorBoundary>
          <router-view v-slot="{ Component }">
            <Transition name="view" mode="out-in">
              <component :is="Component" />
            </Transition>
          </router-view>
        </ErrorBoundary>
      </main>
    </div>
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
  position: relative;
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

/* ── Route view transition — fluid cross-fade + slight lift ─────── */
.view-enter-active {
  transition:
    opacity var(--duration-moderate) var(--ease-out-quart),
    transform var(--duration-moderate) var(--ease-out-quart);
  will-change: opacity, transform;
}

.view-leave-active {
  transition:
    opacity var(--duration-fast) ease,
    transform var(--duration-fast) ease;
  will-change: opacity, transform;
}

.view-enter-from {
  opacity: 0;
  transform: translateY(8px) scale(0.995);
}

.view-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.995);
}

@media (prefers-reduced-motion: reduce) {
  .view-enter-active,
  .view-leave-active {
    transition: opacity var(--duration-fast) ease;
  }

  .view-enter-from,
  .view-leave-to {
    transform: none;
  }
}

/* ── Horizon-route (assistant) adjustments ──────────────────────── */
.alice-app--assistant .app-body {
  background: var(--surface-0);
}

.alice-app--assistant .app-content {
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
