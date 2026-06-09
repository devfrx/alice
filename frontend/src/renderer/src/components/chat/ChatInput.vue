<script setup lang="ts">
/**
 * ChatInput.vue — Auto-growing textarea with send button and image attachments.
 *
 * - Enter sends, Shift+Enter inserts a newline.
 * - Textarea grows up to 5 visible lines then scrolls internally.
 * - A small coloured dot indicates WebSocket connection status.
 * - A paperclip button allows selecting image attachments.
 * - Supports drag-and-drop and clipboard paste (Ctrl+V) for images.
 * - Thumbnails of pending images appear above the input area.
 * - The send button is disabled when the input is empty (and no files) or streaming.
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { AudioDevice } from '../../composables/useVoice'
import ModelSelector from '../settings/ModelSelector.vue'
import ChatToolControls from './ChatToolControls.vue'
import PermissionTierSelector from './PermissionTierSelector.vue'
import MicrophoneButton from '../voice/MicrophoneButton.vue'
import ContextBar from './ContextBar.vue'
import { useChatStore } from '../../stores/chat'
import { useSettingsStore } from '../../stores/settings'
import { useVoiceStore } from '../../stores/voice'
import AppIcon from '../ui/AppIcon.vue'

const router = useRouter()
const route = useRoute()
const settingsStore = useSettingsStore()
const chatStore = useChatStore()
const voiceStore = useVoiceStore()

/** Whether the current view is the Workspace surface. */
const isOnWorkspace = computed(() => route.path.startsWith('/workspace'))

/** Destination view the toggle points to (the OTHER surface). */
const modeTarget = computed(() => (isOnWorkspace.value ? 'assistant' : 'workspace'))

/** Icon for the mode ghost button — reflects the destination view. */
const modeIcon = computed(() => (isOnWorkspace.value ? 'orb' : 'hybrid-panel'))
const modeTitle = computed(() => (isOnWorkspace.value ? "Vai all'assistente" : 'Vai al workspace'))

/** Switch between the two primary surfaces (Workspace ↔ Assistant). */
function toggleMode(): void {
  router.push({ name: modeTarget.value })
}

const supportsVision = computed(() => settingsStore.activeModel?.capabilities.vision ?? false)

const props = defineProps<{
  /** Disable the input (e.g. while streaming). */
  disabled: boolean
  /** WebSocket connection status. */
  isConnected: boolean
  /** Whether the LLM is currently streaming a response. */
  isStreaming: boolean
  /** Available audio input devices. */
  audioDevices?: AudioDevice[]
  /** Currently selected audio device ID. */
  selectedDeviceId?: string
}>()

const emit = defineEmits<{
  /** Fired when the user submits a message (with any pending attachments). */
  send: [content: string, attachments: File[]]
  /** Fired when the user clicks the stop button during streaming. */
  stop: []
  /** Fired when the user starts voice recording. */
  'voice-start': []
  /** Fired when the user stops voice recording. */
  'voice-stop': []
  /** Fired when the user cancels a stuck processing state. */
  'voice-cancel-processing': []
  /** Refresh device list. */
  'refresh-devices': []
  /** Select an audio input device. */
  'select-device': [deviceId: string]
}>()

/** Two-way bound text value. */
const text = ref('')

/** Template ref for the textarea DOM element. */
const textareaRef = ref<HTMLTextAreaElement | null>(null)

/** Template ref for the hidden file input element. */
const fileInputRef = ref<HTMLInputElement | null>(null)

/** Files selected by the user but not yet sent. */
const pendingFiles = ref<File[]>([])

/** Whether the user is dragging files over the input area. */
const isDragOver = ref(false)

/** Counter to handle drag enter/leave on child elements without flicker. */
const dragCounter = ref(0)

/** Thumbnail blob-URLs keyed by their File reference. */
const thumbnailUrls = ref<Map<File, string>>(new Map())

// -----------------------------------------------------------------------
// Auto-resize
// -----------------------------------------------------------------------

/**
 * Resize the textarea to fit its content (up to ~5 lines ≈ 120px).
 * Called after every input and explicit resets.
 */
function autoResize(): void {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 120)}px`
}

/** Watch for external clears (parent resets v-model). */
watch(text, () => nextTick(autoResize))

// -----------------------------------------------------------------------
// Keyboard
// -----------------------------------------------------------------------

/**
 * Handle the Enter key: send the message unless Shift is held.
 * Shift+Enter falls through to the default behaviour (new line).
 */
function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
}

// -----------------------------------------------------------------------
// Submit
// -----------------------------------------------------------------------

/** Validate and emit the trimmed text together with pending attachments. */
function submit(): void {
  const trimmed = text.value.trim()
  if ((!trimmed && pendingFiles.value.length === 0) || props.disabled) return
  emit('send', trimmed, [...pendingFiles.value])
  text.value = ''
  clearAllFiles()
  nextTick(autoResize)
}

// -----------------------------------------------------------------------
// File attachment helpers
// -----------------------------------------------------------------------

/** Open the native file picker. */
function openFilePicker(): void {
  fileInputRef.value?.click()
}

/** Handle files selected via the hidden `<input type="file">`. */
function handleFileSelect(event: Event): void {
  const input = event.target as HTMLInputElement
  if (input.files) {
    addFiles(Array.from(input.files))
  }
  // Reset so the same file can be selected again
  input.value = ''
}

/** Add image files to the pending list and generate thumbnails. */
function addFiles(files: File[]): void {
  const imageFiles = files.filter((f) => f.type.startsWith('image/'))
  if (!supportsVision.value && imageFiles.length > 0) return
  for (const file of imageFiles) {
    pendingFiles.value.push(file)
    const url = URL.createObjectURL(file)
    thumbnailUrls.value.set(file, url)
  }
}

/** Remove a single pending file and revoke its thumbnail URL. */
function removeFile(file: File): void {
  const url = thumbnailUrls.value.get(file)
  if (url) URL.revokeObjectURL(url)
  thumbnailUrls.value.delete(file)
  pendingFiles.value = pendingFiles.value.filter((f) => f !== file)
}

/** Clear all pending files and revoke every thumbnail URL. */
function clearAllFiles(): void {
  for (const url of thumbnailUrls.value.values()) {
    URL.revokeObjectURL(url)
  }
  thumbnailUrls.value.clear()
  pendingFiles.value = []
}

/** Get the blob thumbnail URL for a given file. */
function getThumbnail(file: File): string {
  return thumbnailUrls.value.get(file) ?? ''
}

// -----------------------------------------------------------------------
// Drag-and-drop
// -----------------------------------------------------------------------

/** @internal */
function handleDragEnter(event: DragEvent): void {
  event.preventDefault()
  dragCounter.value++
  isDragOver.value = true
}

/** @internal */
function handleDragOver(event: DragEvent): void {
  event.preventDefault()
}

/** @internal */
function handleDragLeave(): void {
  dragCounter.value--
  if (dragCounter.value === 0) isDragOver.value = false
}

/** @internal */
function handleDrop(event: DragEvent): void {
  event.preventDefault()
  dragCounter.value = 0
  isDragOver.value = false
  if (event.dataTransfer?.files) {
    addFiles(Array.from(event.dataTransfer.files))
  }
}

// -----------------------------------------------------------------------
// Lifecycle — revoke blob URLs on unmount
// -----------------------------------------------------------------------

onBeforeUnmount(() => clearAllFiles())

// -----------------------------------------------------------------------
// Clipboard paste
// -----------------------------------------------------------------------

/** Intercept paste events and extract image data from the clipboard. */
function handlePaste(event: ClipboardEvent): void {
  const items = event.clipboardData?.items
  if (!items) return
  const imageFiles: File[] = []
  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) imageFiles.push(file)
    }
  }
  if (imageFiles.length > 0) {
    event.preventDefault()
    addFiles(imageFiles)
  }
}

// -----------------------------------------------------------------------
// Expose for parent (voice sends need access to pending files)
// -----------------------------------------------------------------------

defineExpose({
  pendingFiles,
  clearPendingFiles(): void {
    clearAllFiles()
  }
})
</script>

<template>
  <div
    class="ci"
    :class="{ 'ci--drag': isDragOver }"
    @dragenter="handleDragEnter"
    @dragover="handleDragOver"
    @dragleave="handleDragLeave"
    @drop="handleDrop"
  >
    <!-- Thumbnail strip (only when files are pending) -->
    <div v-if="pendingFiles.length > 0" class="ci__thumbs">
      <div
        v-for="file in pendingFiles"
        :key="file.name + file.size + file.lastModified"
        class="ci__thumb"
      >
        <img :src="getThumbnail(file)" :alt="file.name" :title="file.name" />
        <button class="ci__thumb-rm" aria-label="Rimuovi allegato" @click="removeFile(file)">
          <AppIcon name="x" :size="10" :stroke-width="2.5" />
        </button>
      </div>
    </div>

    <!-- Textarea: top of the field card, transparent & borderless -->
    <!-- Hidden file input (no layout impact) -->
    <input
      ref="fileInputRef"
      type="file"
      accept="image/*"
      multiple
      class="ci__file-input"
      @change="handleFileSelect"
    />

    <textarea
      ref="textareaRef"
      v-model="text"
      class="ci__textarea"
      placeholder="Scrivi un messaggio..."
      rows="1"
      :disabled="disabled"
      aria-label="Scrivi un messaggio"
      @keydown="handleKeydown"
      @input="autoResize"
      @paste="handlePaste"
    />

    <!-- Bottom control row: left config group / right actions group -->
    <div class="ci__controls">
      <div class="ci__controls-left">
        <button
          class="ci__ghost"
          :disabled="disabled || !supportsVision"
          :aria-label="
            supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'
          "
          :title="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
          @click="openFilePicker"
        >
          <AppIcon name="paperclip" :size="14" />
        </button>

        <div class="ci__divider" />

        <span class="ci__glabel">Modelli</span>
        <div class="ci__seg ci__seg--models">
          <ModelSelector model-type="llm" />
          <ModelSelector model-type="embedding" class="ci__embedding" />
        </div>

        <span class="ci__glabel ci__glabel--agent">Agente</span>
        <div class="ci__seg ci__seg--agent">
          <ChatToolControls />
          <PermissionTierSelector />
        </div>
      </div>

      <div class="ci__controls-right">
        <ContextBar
          :context-info="chatStore.contextInfo"
          :is-compressing="chatStore.isCompressingContext"
        />

        <button
          class="ci__ghost ci__mode"
          :aria-label="modeTitle"
          :title="modeTitle"
          @click="toggleMode"
        >
          <AppIcon :name="modeIcon" :size="13" />
        </button>

        <div
          class="ci__dot"
          :class="isConnected ? 'dot--ok' : 'dot--err'"
          :title="isConnected ? 'Connesso' : 'Non connesso'"
        />

        <MicrophoneButton
          v-if="voiceStore.isReady"
          :available="voiceStore.sttAvailable"
          :connected="voiceStore.connected"
          :audio-devices="audioDevices ?? []"
          :selected-device-id="selectedDeviceId ?? ''"
          @start-recording="$emit('voice-start')"
          @stop-recording="$emit('voice-stop')"
          @cancel-processing="$emit('voice-cancel-processing')"
          @refresh-devices="$emit('refresh-devices')"
          @select-device="(id) => $emit('select-device', id)"
        />

        <Transition name="btn-swap" mode="out-in">
          <button
            v-if="isStreaming"
            key="stop"
            class="ci__stop"
            aria-label="Interrompi generazione"
            @click="emit('stop')"
          >
            <AppIcon name="stop" :size="14" />
          </button>
          <button
            v-else
            key="send"
            class="ci__send"
            :disabled="(!text.trim() && pendingFiles.length === 0) || disabled"
            aria-label="Invia messaggio"
            @click="submit"
          >
            <AppIcon name="send" :size="14" />
          </button>
        </Transition>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ============================================================
   Root container — Claude-style single rounded field card
   Blends onto the chat background; border lights on focus-within.
   ============================================================ */
.ci {
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-3) var(--space-2);
  margin-inline: var(--space-4);
  box-shadow: var(--shadow-elevated);
  container-type: inline-size;
  container-name: chat-input;
  transition:
    box-shadow var(--duration-normal) var(--ease-out-expo),
    border-color var(--duration-normal) var(--ease-out-expo);
}

.ci:focus-within {
  border-color: var(--accent-border);
  box-shadow:
    var(--shadow-elevated),
    0 0 0 1px var(--accent-border);
}

/* Drag-over: accent glow on the entire field */
.ci--drag {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-glow);
}

/* ============================================================
   Thumbnail strip
   ============================================================ */
.ci__thumbs {
  display: flex;
  gap: var(--space-2);
  overflow-x: auto;
  padding-bottom: var(--space-2);
  scrollbar-width: none;
}

.ci__thumbs::-webkit-scrollbar {
  display: none;
}

.ci__thumb {
  position: relative;
  flex-shrink: 0;
  width: 52px;
  height: 52px;
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--border-hover);
  box-shadow: var(--shadow-md);
  transition:
    border-color var(--transition-fast),
    transform var(--transition-fast);
}

.ci__thumb:hover {
  border-color: var(--border-hover);
  transform: translateY(-1px);
}

.ci__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.ci__thumb-rm {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 18px;
  height: 18px;
  border-radius: var(--radius-full);
  background: var(--surface-4);
  border: 1px solid var(--border);
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
  opacity: 0;
  transition:
    opacity 120ms ease,
    background 120ms ease;
}

.ci__thumb:hover .ci__thumb-rm {
  opacity: 1;
}

.ci__thumb-rm:hover {
  background: var(--danger);
  transform: scale(1.1);
}

/* ============================================================
   Hidden file input
   ============================================================ */
.ci__file-input {
  display: none;
}

/* ============================================================
   Textarea — transparent & borderless, grows with content
   ============================================================ */
.ci__textarea {
  width: 100%;
  min-height: 28px;
  max-height: 120px;
  padding: 0 var(--space-1);
  margin-bottom: var(--space-2);
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  resize: none;
  outline: none !important;
  box-shadow: none !important;
  letter-spacing: 0.01em;
  display: block;
}

.ci__textarea::placeholder {
  color: var(--text-muted);
  opacity: 0.75;
}

.ci__textarea:disabled {
  opacity: var(--opacity-muted);
  cursor: not-allowed;
}

/* ============================================================
   Bottom control row
   ============================================================ */
.ci__controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-height: 28px;
}

/* Left cluster: attach + divider + config chips */
.ci__controls-left {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

/* Right cluster: context + dot + mic + send/stop */
.ci__controls-right {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  flex-shrink: 0;
}

/* ============================================================
   Connection status dot
   ============================================================ */
.ci__dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
  transition: background var(--transition-normal);
}

.dot--ok {
  background: var(--success);
  box-shadow: 0 0 5px var(--success-glow);
  animation: dot-pulse 3s ease-in-out infinite;
}

@keyframes dot-pulse {
  0%,
  100% {
    box-shadow: 0 0 5px var(--success-glow);
  }
  50% {
    box-shadow:
      0 0 10px var(--success-glow),
      0 0 3px var(--success);
  }
}

.dot--err {
  background: var(--danger);
  box-shadow: 0 0 5px var(--danger-glow);
  animation: dot-blink 2s ease-in-out infinite;
}

@keyframes dot-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

/* ============================================================
   Vertical divider
   ============================================================ */
.ci__divider {
  width: 1px;
  height: 14px;
  background: var(--border);
  flex-shrink: 0;
  opacity: 0.6;
}

/* ============================================================
   Ghost icon utilities (attach, mode)
   ============================================================ */
.ci__ghost {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    color var(--duration-fast) ease,
    background var(--duration-fast) ease;
}
.ci__ghost:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}
.ci__ghost:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

/* ============================================================
   Group micro-label
   ============================================================ */
.ci__glabel {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
  flex-shrink: 0;
  user-select: none;
}
.ci__glabel--agent {
  margin-left: var(--space-1);
}

/* ============================================================
   Segmented group container — children read as one unit
   ============================================================ */
.ci__seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  flex-shrink: 0;
  min-width: 0;
}

/* Make the child chips bare inside a segment (hero = the llm model gets a subtle ring) */
.ci__seg :deep(.ms__trigger),
.ci__seg :deep(.ctc__chip),
.ci__seg :deep(.tier-chip) {
  background: transparent;
  border-color: transparent;
  height: 24px;
}
.ci__seg :deep(.ms__trigger:hover),
.ci__seg :deep(.ctc__chip:hover:not(:disabled)),
.ci__seg :deep(.tier-chip:hover:not(:disabled)) {
  background: var(--surface-3);
}
/* LLM model is the hero — keep a faint ring */
.ci__seg--models :deep(.ms__trigger:not(.ms__trigger--embedding)) {
  border-color: var(--border-hover, var(--border));
  background: var(--surface-3);
}

.ci__mode {
  color: var(--text-secondary);
}

/* ============================================================
   Send button — accent-filled circle/rounded-square
   ============================================================ */
.ci__send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-md);
  border: none;
  background: var(--accent);
  color: var(--text-on-accent);
  cursor: pointer;
  transition:
    background var(--duration-fast) ease,
    opacity var(--duration-fast) ease,
    box-shadow var(--duration-fast) ease,
    transform var(--duration-fast) ease;
}

.ci__send:hover:not(:disabled) {
  background: var(--accent-hover);
  box-shadow: 0 2px 8px var(--accent-glow);
  transform: translateY(-1px);
}

.ci__send:active:not(:disabled) {
  transform: translateY(0);
}

.ci__send:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

/* ============================================================
   Stop button — danger ring pulse
   ============================================================ */
.ci__stop {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-md);
  border: 1px solid var(--danger-strong);
  background: var(--surface-2);
  color: var(--danger);
  cursor: pointer;
  animation: stop-ring 1.5s ease-out infinite;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.ci__stop:hover {
  background: var(--danger-light);
  color: var(--danger);
}

@keyframes stop-ring {
  0% {
    box-shadow: 0 0 0 0 var(--danger-glow);
  }
  70% {
    box-shadow: 0 0 0 5px transparent;
  }
  100% {
    box-shadow: 0 0 0 0 transparent;
  }
}

/* ============================================================
   Button swap transition (send <-> stop)
   ============================================================ */
.btn-swap-enter-active,
.btn-swap-leave-active {
  transition:
    opacity 0.12s ease,
    transform 0.12s ease;
}

.btn-swap-enter-from {
  opacity: 0;
  transform: scale(0.75);
}

.btn-swap-leave-to {
  opacity: 0;
  transform: scale(0.75);
}

/* ============================================================
   Reduced motion
   ============================================================ */
@media (prefers-reduced-motion: reduce) {
  .ci,
  .ci__send,
  .ci__thumb {
    transition: none;
  }

  .ci__stop {
    animation: none;
  }
}

/* ============================================================
   Responsive: narrow containers
   ============================================================ */

/* Medium: drop labels, embedding text, mode ghost, status dot */
@container chat-input (max-width: 620px) {
  .ci__glabel {
    display: none;
  }
  .ci__mode {
    display: none;
  }
  .ci__dot {
    display: none;
  }
  .ci__embedding :deep(.ms__label) {
    display: none;
  }
}

/* Narrow: drop embedding entirely; model -> short; agente icons-only */
@container chat-input (max-width: 440px) {
  .ci__embedding {
    display: none;
  }
  .ci__seg--agent :deep(.ctc__chip-label),
  .ci__seg--agent :deep(.tier-chip__label) {
    display: none;
  }
  .ci__controls-left {
    gap: var(--space-1);
  }
}
</style>
