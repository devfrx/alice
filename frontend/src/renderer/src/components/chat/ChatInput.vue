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
import { useRouter } from 'vue-router'
import type { AudioDevice } from '../../composables/useVoice'
import ModelSelector from '../settings/ModelSelector.vue'
import MicrophoneButton from '../voice/MicrophoneButton.vue'
import ContextBar from './ContextBar.vue'
import { useChatStore } from '../../stores/chat'
import { useSettingsStore } from '../../stores/settings'
import { useUIStore } from '../../stores/ui'
import { useVoiceStore } from '../../stores/voice'
import AppIcon from '../ui/AppIcon.vue'

const router = useRouter()
const settingsStore = useSettingsStore()
const chatStore = useChatStore()
const uiStore = useUIStore()
const voiceStore = useVoiceStore()

/** Toggle between assistant and hybrid mode. */
function toggleMode(): void {
  const next = uiStore.mode === 'assistant' ? 'hybrid' : 'assistant'
  uiStore.setMode(next)
  router.push({ name: next })
}

const supportsVision = computed(() => settingsStore.activeModel?.capabilities.vision ?? false)
const supportsToolUse = computed(() => settingsStore.activeModel?.capabilities.trained_for_tool_use ?? false)
const supportsThinking = computed(() => settingsStore.activeModel?.capabilities.thinking ?? false)

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
  },
})
</script>

<template>
  <div class="ci" :class="{ 'ci--drag': isDragOver }" @dragenter="handleDragEnter" @dragover="handleDragOver"
    @dragleave="handleDragLeave" @drop="handleDrop">
    <!-- Thumbnail strip (only when files are pending) -->
    <div v-if="pendingFiles.length > 0" class="ci__thumbs">
      <div v-for="file in pendingFiles" :key="file.name + file.size + file.lastModified" class="ci__thumb">
        <img :src="getThumbnail(file)" :alt="file.name" :title="file.name" />
        <button class="ci__thumb-rm" aria-label="Rimuovi allegato" @click="removeFile(file)">
          <AppIcon name="x" :size="10" :stroke-width="2.5" />
        </button>
      </div>
    </div>

    <!-- Layer 1: Toolbar row -->
    <div class="ci__toolbar">
      <!-- Status cluster: connection dot + capability badges -->
      <div class="ci__status">
        <div class="ci__dot" :class="isConnected ? 'dot--ok' : 'dot--err'" />
        <div v-if="settingsStore.activeModel" class="ci__badges">
          <span class="ci__badge" :class="{ 'ci__badge--on': supportsVision }" title="Vision">
            <AppIcon name="eye" :size="16" />
          </span>
          <span class="ci__badge" :class="{ 'ci__badge--on': supportsThinking }" title="Thinking">
            <AppIcon name="lightbulb-simple" :size="16" />
          </span>
          <span class="ci__badge" :class="{ 'ci__badge--on': supportsToolUse }" title="Tool Use">
            <AppIcon name="tool" :size="16" />
          </span>
        </div>
      </div>

      <!-- Context usage bar (grows to fill available space) -->
      <ContextBar :context-info="chatStore.contextInfo" :is-compressing="chatStore.isCompressingContext" />

      <div class="ci__gap" />

      <!-- Mode toggle chip -->
      <button class="ci__mode-toggle" @click="toggleMode">
        <!-- When in assistant → offer hybrid -->
        <template v-if="uiStore.mode === 'assistant'">
          <AppIcon name="message" :size="11" />
          <span>Ibrida</span>
        </template>
        <!-- When in hybrid → offer assistant -->
        <template v-else>
          <AppIcon name="orb" :size="11" />
          <span>Assistente</span>
        </template>
      </button>

      <!-- Divider -->
      <div class="ci__divider" />

      <!-- Model selectors -->
      <div class="ci__selectors">
        <ModelSelector model-type="embedding" />
        <ModelSelector model-type="llm" />
      </div>
    </div>

    <!-- Layer 2: Input row (grows with textarea, border lights up on focus) -->
    <div class="ci__body">
      <!-- Attach (paperclip) button -->
      <button class="ci__attach" :disabled="disabled || !supportsVision"
        :aria-label="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
        :title="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'" @click="openFilePicker">
        <AppIcon name="paperclip" :size="17" />
      </button>

      <!-- Hidden file input -->
      <input ref="fileInputRef" type="file" accept="image/*" multiple class="ci__file-input"
        @change="handleFileSelect" />

      <!-- Auto-growing textarea -->
      <textarea ref="textareaRef" v-model="text" class="ci__textarea" placeholder="Scrivi un messaggio..." rows="1"
        :disabled="disabled" aria-label="Scrivi un messaggio" @keydown="handleKeydown" @input="autoResize"
        @paste="handlePaste" />

      <!-- Microphone button (toggle to talk) -->
      <div class="ci__actions">
        <MicrophoneButton v-if="voiceStore.isReady" :available="voiceStore.sttAvailable"
          :connected="voiceStore.connected" :audio-devices="audioDevices ?? []"
          :selected-device-id="selectedDeviceId ?? ''" @start-recording="$emit('voice-start')"
          @stop-recording="$emit('voice-stop')" @cancel-processing="$emit('voice-cancel-processing')"
          @refresh-devices="$emit('refresh-devices')" @select-device="(id) => $emit('select-device', id)" />

        <!-- Send / Stop toggle with transition -->
        <Transition name="btn-swap" mode="out-in">
          <button v-if="isStreaming" key="stop" class="ci__stop" aria-label="Interrompi generazione"
            @click="emit('stop')">
            <AppIcon name="stop" :size="16" />
          </button>
          <button v-else key="send" class="ci__send" :disabled="(!text.trim() && pendingFiles.length === 0) || disabled"
            aria-label="Invia messaggio" @click="submit">
            <AppIcon name="send" :size="16" />
          </button>
        </Transition>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ============================================================
   Root container — Glass-morphism floating input
   ============================================================ */
.ci {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  padding: var(--space-3) var(--space-4) var(--space-3);
  margin-inline: var(--space-4);
  box-shadow: var(--shadow-elevated);
  container-type: inline-size;
  container-name: chat-input;
  transition: box-shadow var(--duration-normal) var(--ease-out-expo),
    border-color var(--duration-normal) var(--ease-out-expo);
}

.ci:focus-within {
  border-color: var(--border-hover);
  box-shadow: var(--shadow-elevated), 0 0 0 1px var(--white-subtle);
}

/* ============================================================
   Thumbnail strip — Polished thumbnails
   ============================================================ */
.ci__thumbs {
  display: flex;
  gap: var(--space-2);
  overflow-x: auto;
  padding-bottom: var(--space-1);
  scrollbar-width: none;
}

.ci__thumbs::-webkit-scrollbar {
  display: none;
}

.ci__thumb {
  position: relative;
  flex-shrink: 0;
  width: 56px;
  height: 56px;
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--border-hover);
  box-shadow: var(--shadow-md);
  transition: border-color var(--transition-fast), transform var(--transition-fast);
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
  transition: opacity 120ms ease, background 120ms ease;
}

.ci__thumb:hover .ci__thumb-rm {
  opacity: 1;
}

.ci__thumb-rm:hover {
  background: var(--danger);
  transform: scale(1.1);
}

/* ============================================================
   Toolbar row
   ============================================================ */
.ci__toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 32px;
}

/* Status cluster (dot + badges) */
.ci__status {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  flex-shrink: 0;
}

/* Connection status dot */
.ci__dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
  transition: background var(--transition-normal);
}

.dot--ok {
  background: var(--success);
  box-shadow: 0 0 6px var(--success-glow);
  animation: dot-pulse 3s ease-in-out infinite;
}

@keyframes dot-pulse {

  0%,
  100% {
    box-shadow: 0 0 6px var(--success-glow);
  }

  50% {
    box-shadow: 0 0 12px var(--success-glow), 0 0 4px var(--success);
  }
}

.dot--err {
  background: var(--danger);
  box-shadow: 0 0 6px var(--danger-glow);
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

/* Capability badges */
.ci__badges {
  display: flex;
  align-items: center;
  gap: 3px;
}

.ci__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-sm);
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-muted);
  opacity: 0.35;
  transition:
    color var(--duration-fast) ease,
    border-color var(--duration-fast) ease,
    background var(--duration-fast) ease,
    opacity var(--duration-fast) ease;
}

.ci__badge svg {
  width: 11px;
  height: 11px;
}

.ci__badge--on {
  color: var(--text-secondary);
  border-color: var(--border);
  background: var(--surface-2);
  opacity: 1;
}

/* Mode toggle — labeled chip */
.ci__mode-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 8px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: var(--weight-medium);
  letter-spacing: 0.03em;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition:
    color 150ms ease,
    border-color 150ms ease,
    background 150ms ease,
    box-shadow 150ms ease;
}

.ci__mode-toggle:hover {
  color: var(--text-primary);
  border-color: var(--border-hover);
  background: var(--surface-3);
  box-shadow: 0 0 0 1px var(--white-subtle);
}

/* Divider */
.ci__divider {
  width: 1px;
  height: 16px;
  background: var(--border);
  flex-shrink: 0;
  opacity: 0.6;
}

/* Flex spacer */
.ci__gap {
  flex: 1;
  min-width: 0;
}

/* Selectors wrapper */
.ci__selectors {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
}

/* ============================================================
   Input body (Layer 2 — border container, grows with textarea)
   ============================================================ */
.ci__body {
  display: flex;
  align-items: flex-end;
  gap: var(--space-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface-inset);
  padding: 4px var(--space-1-5);
  transition:
    border-color var(--duration-normal) var(--ease-out-expo),
    box-shadow var(--duration-normal) var(--ease-out-expo),
    background var(--duration-normal) var(--ease-out-expo);
}

.ci__body:focus-within {
  border-color: var(--border);
  background: var(--surface-0);
  box-shadow: 0 0 0 1px var(--white-subtle);
}

/* Drag-over: subtle glow on the input border */
.ci--drag .ci__body {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-glow);
}

/* Hidden file input */
.ci__file-input {
  display: none;
}

/* Attach button */
.ci__attach {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 120ms ease, background 120ms ease;
}

.ci__attach:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--accent);
}

.ci__attach:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

/* Textarea — Warmer, inviting feel */
.ci__textarea {
  flex: 1;
  min-width: 0;
  min-height: 36px;
  max-height: 120px;
  padding: 8px 6px;
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  resize: none;
  outline: none !important;
  box-shadow: none !important;
  letter-spacing: 0.01em;
}

.ci__textarea::placeholder {
  color: var(--text-muted);
  opacity: 0.7;
  letter-spacing: 0.02em;
}

.ci__textarea:disabled {
  opacity: var(--opacity-muted);
  cursor: not-allowed;
}

.ci__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
}

/* Send button — Neutral accent on hover */
.ci__send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--accent);
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background 120ms ease,
    color 120ms ease,
    opacity 120ms ease,
    box-shadow 120ms ease;
}

.ci__send:hover:not(:disabled) {
  background: var(--surface-2);
  color: var(--text-primary);
}

.ci__send:not(:disabled) {
  animation: none;
}

.ci__send:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
  animation: none;
}

@keyframes sendReady {

  0%,
  100% {
    box-shadow: 0 0 0 0 transparent;
  }

  50% {
    box-shadow: 0 0 8px var(--white-light);
  }
}

/* Stop button (pulsing danger ring) */
.ci__stop {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  border: 1px solid var(--danger-strong);
  background: var(--accent);
  color: var(--danger);
  cursor: pointer;
  animation: stop-ring 1.5s ease-out infinite;
  transition: background var(--transition-fast);
}

.ci__stop:hover {
  background: var(--surface-2);
}

@keyframes stop-ring {
  0% {
    box-shadow: 0 0 0 0 var(--danger-glow);
  }

  70% {
    box-shadow: 0 0 0 6px transparent;
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
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.btn-swap-enter-from {
  opacity: 0;
  transform: scale(0.8);
}

.btn-swap-leave-to {
  opacity: 0;
  transform: scale(0.8);
}

/* ============================================================
   Reduced motion
   ============================================================ */
@media (prefers-reduced-motion: reduce) {
  .ci {
    transition: none;
  }

  .ci__send:not(:disabled) {
    animation: none;
  }

  .ci__thumb {
    transition: none;
  }
}

/* ============================================================
   Responsive: compact layout for narrow containers (Hybrid left pane)
   ============================================================ */
@container chat-input (max-width: 380px) {
  .ci {
    padding: var(--space-2) var(--space-2) var(--space-2);
    margin-inline: var(--space-2);
  }

  .ci__toolbar {
    gap: var(--space-1);
  }

  .ci__badges {
    display: none;
  }

  .ci__selectors {
    display: none;
  }

  .ci__divider {
    display: none;
  }

  .ci__mode-toggle span {
    display: none;
  }

  .ci__mode-toggle {
    padding: 0 6px;
    width: 24px;
    height: 24px;
    justify-content: center;
  }
}

@container chat-input (max-width: 280px) {
  .ci__mode-toggle {
    display: none;
  }
}
</style>
