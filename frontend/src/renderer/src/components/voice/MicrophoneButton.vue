<script setup lang="ts">
/**
 * MicrophoneButton.vue — Toggle microphone control.
 *
 * Click to start recording, click again to stop and send for transcription.
 * Right-click to select a different audio input device.
 * Shows multi-ring audio visualization while recording,
 * conic gradient + bouncing dots when processing STT.
 */
import { ref, computed, onBeforeUnmount } from 'vue'
import type { AudioDevice } from '../../composables/useVoice'
import { useVoiceStore } from '../../stores/voice'

const store = useVoiceStore()

const props = defineProps<{
  /** Whether voice services are available. */
  available: boolean
  /** Whether the voice WS is connected. */
  connected: boolean
  /** Available audio input devices. */
  audioDevices: AudioDevice[]
  /** Currently selected device ID (empty = default). */
  selectedDeviceId: string
}>()

const emit = defineEmits<{
  /** Start recording audio. */
  'start-recording': []
  /** Stop recording audio. */
  'stop-recording': []
  /** Cancel a stuck processing state. */
  'cancel-processing': []
  /** Refresh the device list. */
  'refresh-devices': []
  /** Select an audio input device. */
  'select-device': [deviceId: string]
}>()

const isActive = computed(() => store.isListening)
const isProcessing = computed(() => store.isProcessing)
const level = computed(() => store.audioLevel)

/** Whether the device dropdown is visible. */
const showDeviceMenu = ref(false)

/** Ripple animation trigger. */
const clicking = ref(false)

function onClick(): void {
  if (!props.available || !props.connected) return

  /* ripple feedback */
  clicking.value = true
  requestAnimationFrame(() => {
    setTimeout(() => { clicking.value = false }, 200)
  })

  if (isProcessing.value) {
    emit('cancel-processing')
    return
  }
  if (isActive.value) {
    emit('stop-recording')
  } else {
    emit('start-recording')
  }
}

/** Close the menu if clicking outside the wrapper. */
function onClickOutside(e: MouseEvent): void {
  const wrapper = (e.target as HTMLElement)?.closest('.mic-wrapper')
  if (!wrapper) showDeviceMenu.value = false
}

function onContextMenu(e: MouseEvent): void {
  e.preventDefault()
  emit('refresh-devices')
  if (!showDeviceMenu.value) {
    showDeviceMenu.value = true
    document.addEventListener('click', onClickOutside, { once: true })
  } else {
    showDeviceMenu.value = false
  }
}

/** Cleanup on unmount: remove stale document listener if menu is still open. */
onBeforeUnmount(() => {
  document.removeEventListener('click', onClickOutside)
})

function selectDevice(deviceId: string): void {
  emit('select-device', deviceId)
  showDeviceMenu.value = false
}

/* --- Computed inline styles for the 3 concentric rings --- */
const ringInnerStyle = computed(() => ({
  opacity: 0.6 + level.value * 0.4,
  transform: `scale(${1 + level.value * 0.15})`,
}))
const ringMidStyle = computed(() => ({
  opacity: level.value * 0.8,
  transform: `scale(${1 + level.value * 0.35})`,
}))
const ringOuterStyle = computed(() => ({
  opacity: level.value * 0.5,
  transform: `scale(${1 + level.value * 0.55})`,
}))
</script>

<template>
  <div class="mic-wrapper">
    <button class="mic-btn" :class="{
      'mic-btn--active': isActive,
      'mic-btn--processing': isProcessing,
      'mic-btn--disabled': !available || !connected,
      'mic-btn--click': clicking,
    }" :disabled="!available || !connected"
      :aria-label="isActive ? 'Clicca per inviare' : isProcessing ? 'Clicca per annullare' : 'Clicca per parlare'"
      :title="!available ? 'Servizio vocale non disponibile' : !connected ? 'Non connesso' : isActive ? 'Clicca per fermare' : isProcessing ? 'Clicca per annullare' : 'Clicca per parlare (tasto destro: microfono)'"
      @click.prevent="onClick" @contextmenu="onContextMenu">
      <!-- Multi-ring audio visualization (recording) -->
      <span v-if="isActive" class="mic-ring mic-ring--inner" :style="ringInnerStyle" />
      <span v-if="isActive && level > 0.15" class="mic-ring mic-ring--mid" :style="ringMidStyle" />
      <span v-if="isActive && level > 0.3" class="mic-ring mic-ring--outer" :style="ringOuterStyle" />

      <!-- Processing conic gradient border -->
      <span v-if="isProcessing" class="mic-btn__conic" />

      <!-- Icon: mic or processing dots -->
      <Transition name="icon-morph" mode="out-in">
        <svg v-if="!isProcessing" key="mic" class="mic-btn__icon" :class="{ 'mic-btn__icon--rec': isActive }" width="20"
          height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
          stroke-linejoin="round">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
        <span v-else key="dots" class="mic-btn__dots">
          <span /><span /><span />
        </span>
      </Transition>
    </button>

    <!-- Device selection dropdown (right-click) -->
    <Transition name="menu-fade">
      <div v-if="showDeviceMenu" class="mic-menu">
        <div class="mic-menu__title">Microfono</div>
        <div v-if="audioDevices.length === 0" class="mic-menu__empty">
          Nessun dispositivo trovato
        </div>
        <button v-for="device in audioDevices" :key="device.deviceId" class="mic-menu__item"
          :class="{ 'mic-menu__item--active': device.deviceId === selectedDeviceId }"
          @click="selectDevice(device.deviceId)">
          <span class="mic-menu__check">{{ device.deviceId === selectedDeviceId ? '✓' : '' }}</span>
          {{ device.label }}
        </button>
        <button class="mic-menu__item mic-menu__item--default" @click="selectDevice('')">
          <span class="mic-menu__check">{{ !selectedDeviceId ? '✓' : '' }}</span>
          Predefinito di sistema
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* ── Mic wrapper ── */
.mic-wrapper {
  position: relative;
  display: inline-flex;
  overflow: visible;
}

/* ── Base button ── */
.mic-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-hover);
  color: var(--text-secondary);
  cursor: pointer;
  transition: color var(--transition-fast),
    background var(--transition-fast),
    border-color var(--transition-fast);
  outline: none;
  -webkit-app-region: no-drag;
}

.mic-btn:hover:not(:disabled) {
  color: var(--text-primary);
  background: var(--surface-active);
  border-color: var(--border-hover);
}

.mic-btn:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

/* Recording state */
.mic-btn--active {
  color: var(--listening);
  background: var(--listening-dim);
  border-color: var(--listening-border);
}

/* Processing state */
.mic-btn--processing {
  color: var(--accent);
  background: var(--thinking-dim);
  border-color: var(--thinking-border);
  cursor: pointer;
}

/* Disabled */
.mic-btn--disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

/* Click ripple */
.mic-btn--click {
  animation: mic-click 0.2s ease;
}

@keyframes mic-click {
  0% {
    transform: scale(1);
  }

  50% {
    transform: scale(0.9);
  }

  100% {
    transform: scale(1);
  }
}

/* ── Audio visualization rings ── */
.mic-ring {
  position: absolute;
  border-radius: var(--radius-md);
  pointer-events: none;
  transition: transform 0.1s ease-out, opacity 0.1s ease-out;
}

.mic-ring--inner {
  inset: -4px;
  border: 2px solid var(--listening-border);
}

.mic-ring--mid {
  inset: -10px;
  border: 1.5px solid var(--listening-dim);
}

.mic-ring--outer {
  inset: -16px;
  border: 1px solid var(--listening-dim);
}

/* ── Processing conic spinner ── */
.mic-btn__conic {
  position: absolute;
  inset: -3px;
  border-radius: var(--radius-full);
  background: conic-gradient(from 0deg, transparent 50%, var(--accent) 80%, transparent 100%);
  mask: radial-gradient(farthest-side, transparent calc(100% - 2px), black calc(100% - 2px));
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2px), black calc(100% - 2px));
  animation: conic-spin 1s linear infinite;
  pointer-events: none;
  opacity: 0.7;
}

@keyframes conic-spin {
  to {
    transform: rotate(360deg);
  }
}

/* ── Mic icon ── */
.mic-btn__icon {
  position: relative;
  z-index: 1;
  transition: opacity var(--transition-fast);
}

.mic-btn__icon--rec {
  opacity: 1;
}

/* ── Processing dots ── */
.mic-btn__dots {
  display: flex;
  gap: 3px;
  align-items: center;
  justify-content: center;
  position: relative;
  z-index: 1;
}

.mic-btn__dots span {
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--accent);
  animation: dot-bounce 1.2s ease-in-out infinite;
}

.mic-btn__dots span:nth-child(2) {
  animation-delay: 0.2s;
}

.mic-btn__dots span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes dot-bounce {

  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.5;
  }

  40% {
    transform: translateY(-5px);
    opacity: 1;
  }
}

/* ── Icon morph transition ── */
.icon-morph-enter-active,
.icon-morph-leave-active {
  transition: opacity var(--duration-fast) ease, transform var(--duration-fast) ease;
}

.icon-morph-enter-from {
  opacity: 0;
  transform: scale(0.7);
}

.icon-morph-leave-to {
  opacity: 0;
  transform: scale(0.7);
}

/* ── Device selection dropdown ── */
.mic-menu {
  position: absolute;
  bottom: calc(100% + 10px);
  right: 0;
  min-width: 240px;
  max-width: 340px;
  background: var(--glass-bg);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-1) 0;
  box-shadow: var(--shadow-md);
  z-index: 100;
}

.mic-menu__title {
  padding: var(--space-2) var(--space-3) var(--space-1-5);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}

.mic-menu__empty {
  padding: var(--space-2-5) var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-muted);
  font-style: italic;
}

.mic-menu__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-sm);
  cursor: pointer;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background var(--transition-fast);
}

.mic-menu__item:hover {
  background: var(--surface-hover);
}

.mic-menu__item--active {
  color: var(--accent);
}

.mic-menu__item--default {
  border-top: 1px solid var(--border);
  margin-top: 2px;
  padding-top: var(--space-2-5);
}

.mic-menu__check {
  width: 14px;
  text-align: center;
  flex-shrink: 0;
  font-size: var(--text-xs);
}

.menu-fade-enter-active,
.menu-fade-leave-active {
  transition: opacity var(--duration-normal) var(--ease-smooth),
    transform var(--duration-normal) var(--ease-smooth);
}

.menu-fade-enter-from,
.menu-fade-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.97);
}

@media (prefers-reduced-motion: reduce) {

  .mic-btn--active,
  .mic-btn__conic,
  .mic-btn__dots span,
  .mic-btn--click {
    animation: none;
  }
}
</style>
