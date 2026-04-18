<script setup lang="ts">
/**
 * TitleBar.vue — Custom frameless window title bar for AL\CE.
 *
 * Provides a draggable region with app title and native-style
 * window control buttons (minimize, maximize/restore, close).
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { useVoiceStore } from '../stores/voice'
import { useUIStore } from '../stores/ui'
import { usePluginsStore } from '../stores/plugins'
import WeatherWidget from './plugins/WeatherWidget.vue'
import AliceSpinner from './ui/AliceSpinner.vue'
import AppIcon from './ui/AppIcon.vue'

/** Tracks whether the window is currently maximized */
const isMaximized = ref(false)

const settingsStore = useSettingsStore()
const voiceStore = useVoiceStore()
const uiStore = useUIStore()
const pluginsStore = usePluginsStore()

/** Whether the weather plugin is enabled. */
const weatherEnabled = computed(() =>
  pluginsStore.plugins.some((p) => p.name === 'weather' && p.enabled)
)

/** Display name of the active LLM model, truncated at 30 chars */
const modelDisplayName = computed(() => {
  const model = settingsStore.activeModel
  if (!model) return settingsStore.settings?.llm?.model || 'Nessun modello'
  const name = model.display_name || model.name
  return name.length > 30 ? name.slice(0, 30) + '\u2026' : name
})

/** Whether a model is active (for styling "Nessun modello" differently) */
const hasActiveModel = computed(() => {
  return !!settingsStore.activeModel || !!settingsStore.settings?.llm?.model
})

/** LM Studio connection status */
const connectionStatus = computed<'connected' | 'loading' | 'disconnected'>(() => {
  if (settingsStore.isAnyOperationInProgress) return 'loading'
  if (settingsStore.lmStudioConnected) return 'connected'
  return 'disconnected'
})

const windowControls = window.electron?.windowControls

/** Minimize the application window */
const handleMinimize = (): void => {
  windowControls?.minimize()
}

/** Toggle maximize / restore */
const handleMaximize = (): void => {
  windowControls?.maximize()
}

/** Close the application window */
const handleClose = (): void => {
  windowControls?.close()
}

/** Subscribe to accurate maximize/unmaximize events from the main process. */
let unsubMaximize: (() => void) | undefined

onMounted(() => {
  unsubMaximize = windowControls?.onMaximizeChange((maximized: boolean) => {
    isMaximized.value = maximized
  })
})

onUnmounted(() => {
  unsubMaximize?.()
})
</script>

<template>
  <header class="titlebar">
    <!-- Left zone: hamburger + branding -->
    <div class="titlebar__left">
      <button class="titlebar__menu-btn" aria-label="Apri sidebar" @click="uiStore.toggleSidebar">
        <AppIcon name="menu" :size="14" />
      </button>
      <span class="titlebar__title">AL\CE</span>
    </div>

    <!-- Center zone: draggable + status capsule -->
    <div class="titlebar__center">
      <!-- Status capsule (no-drag for interactive) -->
      <div class="titlebar__capsule">
        <span class="titlebar__status-dot" :class="`titlebar__status-dot--${connectionStatus}`" />
        <span class="titlebar__model-name" :class="{ 'titlebar__model-name--empty': !hasActiveModel }"
          :title="modelDisplayName">
          {{ modelDisplayName }}
        </span>
        <AliceSpinner v-if="connectionStatus === 'loading'" size="xs" />

        <template v-if="voiceStore.sttAvailable && voiceStore.sttEngine">
          <span class="titlebar__capsule-sep" />
          <AppIcon name="stt-indicator" :size="10" class="titlebar__voice-icon" />
          <span class="titlebar__voice-label">{{ voiceStore.sttEngine }}</span>
          <span v-if="voiceStore.sttModel" class="titlebar__voice-detail">{{ voiceStore.sttModel }}</span>
        </template>
      </div>
    </div>

    <!-- Right zone: weather + window controls -->
    <div class="titlebar__right">
      <div v-if="weatherEnabled" class="titlebar__weather">
        <WeatherWidget />
      </div>

      <div class="titlebar__controls">
        <button class="titlebar__btn titlebar__btn--minimize" aria-label="Minimize" @click="handleMinimize">
          <AppIcon name="win-minimize" :size="10" />
        </button>
        <button class="titlebar__btn titlebar__btn--maximize" :aria-label="isMaximized ? 'Restore' : 'Maximize'"
          @click="handleMaximize">
          <AppIcon v-if="!isMaximized" name="win-maximize" :size="10" />
          <AppIcon v-else name="win-restore" :size="10" />
        </button>
        <button class="titlebar__btn titlebar__btn--close" aria-label="Close" @click="handleClose">
          <AppIcon name="win-close" :size="10" />
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.titlebar {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--titlebar-height, 38px);
  min-height: var(--titlebar-height, 38px);
  background: transparent;
  z-index: var(--z-sticky);
  user-select: none;
  -webkit-app-region: drag;
}

/* ── Left zone ──────────────────────────────────────────────── */
.titlebar__left {
  display: flex;
  align-items: center;
  height: 100%;
  flex-shrink: 0;
  gap: 2px;
}

.titlebar__menu-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 100%;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
  -webkit-app-region: no-drag;
  transition:
    color 100ms ease,
    background 100ms ease;
}

.titlebar__menu-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.titlebar__menu-btn:active {
  background: var(--surface-active);
}

.titlebar__title {
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: var(--weight-semibold);
  letter-spacing: 0px;
  color: var(--text-muted);
  opacity: 0.6;
  padding-right: var(--space-3);
}

/* ── Center zone ────────────────────────────────────────────── */
.titlebar__center {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  -webkit-app-region: no-drag;
}

.titlebar__capsule {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 12px;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--glass-border);
  transition:
    border-color 200ms ease,
    background 200ms ease,
    box-shadow 200ms ease;
}

.titlebar__capsule:hover {
  border-color: var(--border-hover);
  background: var(--surface-3);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

/* ── Status dot ─────────────────────────────────────────────── */
.titlebar__status-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}

.titlebar__status-dot--connected {
  background: var(--success);
  box-shadow: 0 0 4px var(--success-glow);
}

.titlebar__status-dot--loading {
  background: var(--accent);
  animation: dot-pulse-tb 1.5s ease-in-out infinite;
}

.titlebar__status-dot--disconnected {
  background: var(--danger);
}

@keyframes dot-pulse-tb {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.4;
  }
}

/* ── Model name ─────────────────────────────────────────────── */
.titlebar__model-name {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.3px;
  color: var(--text-secondary);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.titlebar__model-name--empty {
  color: var(--text-muted);
  font-style: italic;
}

/* ── Capsule separator ──────────────────────────────────────── */
.titlebar__capsule-sep {
  width: 1px;
  height: 10px;
  background: var(--border);
  opacity: 0.5;
  flex-shrink: 0;
}

/* ── Voice info (inside capsule) ────────────────────────────── */
.titlebar__voice-icon {
  color: var(--text-muted);
  opacity: 0.6;
  flex-shrink: 0;
}

.titlebar__voice-label {
  font-size: 10px;
  font-weight: 400;
  letter-spacing: 0.2px;
  color: var(--text-muted);
  white-space: nowrap;
}

.titlebar__voice-detail {
  font-size: 10px;
  color: var(--text-muted);
  opacity: 0.5;
  letter-spacing: 0.2px;
  white-space: nowrap;
}

/* ── Right zone ─────────────────────────────────────────────── */
.titlebar__right {
  display: flex;
  align-items: center;
  height: 100%;
  flex-shrink: 0;
}

.titlebar__weather {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  padding: 0 var(--space-2);
  -webkit-app-region: no-drag;
}

/* ── Window controls ────────────────────────────────────────── */
.titlebar__controls {
  display: flex;
  height: 100%;
  -webkit-app-region: no-drag;
}

.titlebar__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 100%;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background 100ms ease,
    color 100ms ease;
}

.titlebar__btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.titlebar__btn:active {
  background: var(--surface-active);
}

.titlebar__btn--close:hover {
  background: var(--danger);
  color: var(--text-primary);
}

.titlebar__btn--close:active {
  background: var(--danger);
  color: var(--text-primary);
  filter: brightness(0.9);
}

.titlebar__btn:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px var(--accent);
}
</style>
