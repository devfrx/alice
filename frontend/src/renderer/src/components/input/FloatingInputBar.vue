<script setup lang="ts">
/**
 * FloatingInputBar.vue — Glassmorphism floating input bar.
 *
 * A state-aware input pill that sits at the bottom-center of the screen.
 * Adapts its appearance based on the current AI state: idle, recording,
 * processing, thinking, generating, speaking.
 * Wraps text input, file attachments, model selector, and voice controls.
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { AudioDevice } from '../../composables/useVoice'
import ModelSelector from '../settings/ModelSelector.vue'
import MicrophoneButton from '../voice/MicrophoneButton.vue'
import { useSettingsStore } from '../../stores/settings'
import { useVoiceStore } from '../../stores/voice'

const settingsStore = useSettingsStore()
const voiceStore = useVoiceStore()

const supportsVision = computed(() => settingsStore.activeModel?.capabilities.vision ?? false)

type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'

const props = defineProps<{
    disabled: boolean
    isConnected: boolean
    isStreaming: boolean
    audioDevices?: AudioDevice[]
    selectedDeviceId?: string
    orbState: OrbState
}>()

const emit = defineEmits<{
    send: [content: string, attachments: File[]]
    stop: []
    'voice-start': []
    'voice-stop': []
    'voice-cancel-processing': []
    'refresh-devices': []
    'select-device': [deviceId: string]
}>()

// --- State ---

const text = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const pendingFiles = ref<File[]>([])
const isDragOver = ref(false)
const dragCounter = ref(0)
const thumbnailUrls = ref<Map<File, string>>(new Map())
const isExpanded = ref(false)
const rootRef = ref<HTMLElement | null>(null)

/** Whether we are in an "active" (non-idle) state that hides the full input. */
const isActive = computed(() => props.orbState !== 'idle')

/** Visual state label for the compact pill. */
const stateLabel = computed<string>(() => {
    switch (props.orbState) {
        case 'listening': return 'In ascolto...'
        case 'processing': return 'Elaborazione...'
        case 'thinking': return props.isStreaming ? 'Sta rispondendo...' : 'Sta pensando...'
        case 'speaking': return 'Sta parlando...'
        default: return ''
    }
})

/** Root class modifiers. */
const barClasses = computed(() => ({
    'fib--expanded': isExpanded.value && !isActive.value,
    'fib--active': isActive.value,
    'fib--listening': props.orbState === 'listening',
    'fib--processing': props.orbState === 'processing',
    'fib--thinking': props.orbState === 'thinking',
    'fib--speaking': props.orbState === 'speaking',
    'fib--drag': isDragOver.value,
}))

// --- Auto-resize ---

function autoResize(): void {
    const el = textareaRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
}

watch(text, () => nextTick(autoResize))

// --- Focus / Expand ---

function handleFocus(): void {
    if (!isActive.value) isExpanded.value = true
}

function handleBlur(event: FocusEvent): void {
    const related = event.relatedTarget as Node | null
    if (related && rootRef.value?.contains(related)) return
    if (!text.value.trim() && pendingFiles.value.length === 0) {
        isExpanded.value = false
    }
}

// --- Keyboard ---

function handleKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault()
        submit()
    }
}

// --- Submit ---

function submit(): void {
    const trimmed = text.value.trim()
    if ((!trimmed && pendingFiles.value.length === 0) || props.disabled) return
    emit('send', trimmed, [...pendingFiles.value])
    text.value = ''
    clearAllFiles()
    isExpanded.value = false
    nextTick(autoResize)
}

// --- File helpers ---

function openFilePicker(): void {
    fileInputRef.value?.click()
}

function handleFileSelect(event: Event): void {
    const input = event.target as HTMLInputElement
    if (input.files) addFiles(Array.from(input.files))
    input.value = ''
}

function addFiles(files: File[]): void {
    const imageFiles = files.filter((f) => f.type.startsWith('image/'))
    if (!supportsVision.value && imageFiles.length > 0) return
    for (const file of imageFiles) {
        pendingFiles.value.push(file)
        const url = URL.createObjectURL(file)
        thumbnailUrls.value.set(file, url)
    }
    if (imageFiles.length > 0) isExpanded.value = true
}

function removeFile(file: File): void {
    const url = thumbnailUrls.value.get(file)
    if (url) URL.revokeObjectURL(url)
    thumbnailUrls.value.delete(file)
    pendingFiles.value = pendingFiles.value.filter((f) => f !== file)
}

function clearAllFiles(): void {
    for (const url of thumbnailUrls.value.values()) URL.revokeObjectURL(url)
    thumbnailUrls.value.clear()
    pendingFiles.value = []
}

function getThumbnail(file: File): string {
    return thumbnailUrls.value.get(file) ?? ''
}

// --- Drag & drop ---

function handleDragEnter(event: DragEvent): void {
    event.preventDefault()
    dragCounter.value++
    isDragOver.value = true
}

function handleDragOver(event: DragEvent): void {
    event.preventDefault()
}

function handleDragLeave(): void {
    dragCounter.value--
    if (dragCounter.value === 0) isDragOver.value = false
}

function handleDrop(event: DragEvent): void {
    event.preventDefault()
    dragCounter.value = 0
    isDragOver.value = false
    if (event.dataTransfer?.files) addFiles(Array.from(event.dataTransfer.files))
}

// --- Clipboard paste ---

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

// --- Stop action (for active states) ---

function handleStop(): void {
    if (props.orbState === 'listening') {
        emit('voice-stop')
    } else if (props.orbState === 'processing') {
        emit('voice-cancel-processing')
    } else if (props.orbState === 'thinking') {
        emit('stop')
    } else if (props.orbState === 'speaking') {
        emit('stop')
    }
}

// --- Lifecycle ---

onBeforeUnmount(() => clearAllFiles())

// --- Expose ---

defineExpose({
    pendingFiles,
    clearPendingFiles(): void {
        clearAllFiles()
    },
})
</script>

<template>
    <div ref="rootRef" class="fib" :class="barClasses" @dragenter="handleDragEnter" @dragover="handleDragOver"
        @dragleave="handleDragLeave" @drop="handleDrop">
        <!-- Active state overlay (recording, processing, thinking, speaking) -->
        <Transition name="fib-state">
            <div v-if="isActive" class="fib__state" @click="handleStop">
                <!-- Listening state -->
                <template v-if="orbState === 'listening'">
                    <div class="fib__waveform">
                        <span v-for="i in 5" :key="i" class="fib__wave-bar"
                            :style="{ animationDelay: `${(i - 1) * 0.1}s` }" />
                    </div>
                    <span class="fib__state-label">{{ stateLabel }}</span>
                    <span class="fib__duration">{{ voiceStore.formattedDuration }}</span>
                    <button class="fib__stop-btn fib__stop-btn--rec" aria-label="Interrompi registrazione">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                            <rect x="4" y="4" width="16" height="16" rx="2" />
                        </svg>
                    </button>
                </template>

                <!-- Processing state -->
                <template v-else-if="orbState === 'processing'">
                    <div class="fib__spinner" />
                    <span class="fib__state-label fib__state-label--shimmer">{{ stateLabel }}</span>
                    <button class="fib__stop-btn" aria-label="Annulla">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2.5">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    </button>
                </template>

                <!-- Thinking / Generating -->
                <template v-else-if="orbState === 'thinking'">
                    <div class="fib__dots">
                        <span /><span /><span />
                    </div>
                    <span class="fib__state-label">{{ stateLabel }}</span>
                    <button class="fib__stop-btn" aria-label="Interrompi generazione">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                            <rect x="4" y="4" width="16" height="16" rx="2" />
                        </svg>
                    </button>
                </template>

                <!-- Speaking -->
                <template v-else-if="orbState === 'speaking'">
                    <div class="fib__sound-wave">
                        <span v-for="i in 4" :key="i" :style="{ animationDelay: `${(i - 1) * 0.15}s` }" />
                    </div>
                    <span class="fib__state-label">{{ stateLabel }}</span>
                    <button class="fib__stop-btn" aria-label="Interrompi">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                            <rect x="4" y="4" width="16" height="16" rx="2" />
                        </svg>
                    </button>
                </template>
            </div>
        </Transition>

        <!-- Idle / input mode -->
        <Transition name="fib-input">
            <div v-if="!isActive" class="fib__input-area">
                <!-- Thumbnails -->
                <div v-if="pendingFiles.length > 0" class="fib__thumbs">
                    <div v-for="file in pendingFiles" :key="file.name + file.size + file.lastModified"
                        class="fib__thumb">
                        <img :src="getThumbnail(file)" :alt="file.name" :title="file.name" />
                        <button class="fib__thumb-rm" aria-label="Rimuovi allegato" @click="removeFile(file)">
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2.5" stroke-linecap="round">
                                <line x1="18" y1="6" x2="6" y2="18" />
                                <line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                        </button>
                    </div>
                </div>

                <!-- Toolbar (visible when expanded) -->
                <div v-if="isExpanded" class="fib__toolbar">
                    <div class="fib__dot" :class="isConnected ? 'dot--ok' : 'dot--err'" />
                    <div class="fib__gap" />
                    <div class="fib__selectors">
                        <ModelSelector model-type="embedding" />
                        <ModelSelector model-type="llm" />
                    </div>
                </div>

                <!-- Main row -->
                <div class="fib__body">
                    <!-- Attach button -->
                    <button class="fib__attach" :disabled="disabled || !supportsVision"
                        :title="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
                        @click="openFilePicker">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path
                                d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                        </svg>
                    </button>

                    <input ref="fileInputRef" type="file" accept="image/*" multiple class="fib__file-input"
                        @change="handleFileSelect" />

                    <!-- Textarea -->
                    <textarea ref="textareaRef" v-model="text" class="fib__textarea"
                        :placeholder="isExpanded ? 'Scrivi un messaggio...' : 'Scrivi o parla...'" rows="1"
                        :disabled="disabled" aria-label="Scrivi un messaggio" @keydown="handleKeydown"
                        @input="autoResize" @paste="handlePaste" @focus="handleFocus" @blur="handleBlur" />

                    <!-- Voice + Send actions -->
                    <div class="fib__actions">
                        <MicrophoneButton v-if="voiceStore.isReady" :available="voiceStore.sttAvailable"
                            :connected="voiceStore.connected" :audio-devices="audioDevices ?? []"
                            :selected-device-id="selectedDeviceId ?? ''" @start-recording="$emit('voice-start')"
                            @stop-recording="$emit('voice-stop')" @cancel-processing="$emit('voice-cancel-processing')"
                            @refresh-devices="$emit('refresh-devices')"
                            @select-device="(id) => $emit('select-device', id)" />

                        <Transition name="btn-swap" mode="out-in">
                            <button v-if="isStreaming" key="stop" class="fib__stop" aria-label="Interrompi generazione"
                                @click="emit('stop')">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <circle cx="12" cy="12" r="10" />
                                    <rect x="9" y="9" width="6" height="6" rx="1" fill="currentColor" stroke="none" />
                                </svg>
                            </button>
                            <button v-else key="send" class="fib__send"
                                :disabled="(!text.trim() && pendingFiles.length === 0) || disabled"
                                aria-label="Invia messaggio" @click="submit">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                    stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <line x1="22" y1="2" x2="11" y2="13" />
                                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                                </svg>
                            </button>
                        </Transition>
                    </div>
                </div>
            </div>
        </Transition>
    </div>
</template>

<style scoped>
/* ── Root — Floating input pill ── */
.fib {
    position: fixed;
    bottom: 24px;
    left: calc(50% + var(--sidebar-offset, 0px) / 2);
    transform: translateX(-50%);
    z-index: 100;
    min-width: 360px;
    max-width: 600px;
    width: auto;

    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-2) var(--space-3);

    box-shadow: var(--shadow-floating);
    transition:
        border-color var(--duration-normal) var(--ease-smooth),
        box-shadow var(--duration-normal) var(--ease-smooth),
        border-radius var(--duration-normal) var(--ease-smooth),
        padding var(--duration-normal) var(--ease-smooth),
        min-width var(--duration-normal) var(--ease-smooth),
        left var(--duration-normal) var(--ease-smooth);

    display: grid;
}

.fib:focus-within {
    border-color: var(--border-hover);
}

/* Collapsed pill shape */
.fib:not(.fib--expanded):not(.fib--active) {
    border-radius: var(--radius-pill);
    min-width: 320px;
}

/* Expanded input */
.fib--expanded {
    border-radius: var(--radius-lg);
    min-width: 420px;
}

/* Active states pill */
.fib--active {
    border-radius: var(--radius-pill);
    min-width: 280px;
    max-width: 400px;
    padding: var(--space-2) var(--space-4);
}

/* Listening */
.fib--listening {
    border-color: var(--listening-border);
}

/* Thinking */
.fib--thinking {
    border-color: var(--thinking-border);
}

/* Speaking */
.fib--speaking {
    border-color: var(--speaking-border);
}

/* Drag over */
.fib--drag {
    border-color: var(--accent-border);
}

/* ── Active state overlay ── */
.fib__state {
    grid-area: 1 / 1;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-1) 0;
    cursor: pointer;
    min-height: 36px;
}

.fib__state-label {
    color: var(--text-secondary);
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    letter-spacing: 0.02em;
    white-space: nowrap;
    flex: 1;
}

.fib__state-label--shimmer {
    background: linear-gradient(90deg,
            var(--text-secondary) 0%,
            var(--accent) 50%,
            var(--text-secondary) 100%);
    background-size: 200% 100%;
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: shimmer 2s linear infinite;
}

@keyframes shimmer {
    0% {
        background-position: 200% 0;
    }

    100% {
        background-position: -200% 0;
    }
}

.fib__duration {
    color: var(--text-muted);
    font-size: var(--text-xs);
    font-variant-numeric: tabular-nums;
}

/* Waveform bars (listening) */
.fib__waveform {
    display: flex;
    align-items: center;
    gap: 3px;
    height: 20px;
}

.fib__wave-bar {
    width: 3px;
    border-radius: 2px;
    background: var(--listening);
    animation: wave-bounce 0.6s ease-in-out infinite alternate;
}

@keyframes wave-bounce {
    0% {
        height: 4px;
    }

    100% {
        height: 16px;
    }
}

/* Spinner (processing) */
.fib__spinner {
    width: 18px;
    height: 18px;
    border: 2px solid var(--accent-dim);
    border-top-color: var(--accent);
    border-radius: var(--radius-full);
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}

/* Pulsing dots (thinking) */
.fib__dots {
    display: flex;
    align-items: center;
    gap: 4px;
}

.fib__dots span {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-full);
    background: var(--accent);
    animation: dot-bounce 1.2s ease-in-out infinite;
}

.fib__dots span:nth-child(2) {
    animation-delay: 0.2s;
}

.fib__dots span:nth-child(3) {
    animation-delay: 0.4s;
}

@keyframes dot-bounce {

    0%,
    80%,
    100% {
        opacity: 0.3;
        transform: scale(0.8);
    }

    40% {
        opacity: 1;
        transform: scale(1.1);
    }
}

/* Sound wave (speaking) */
.fib__sound-wave {
    display: flex;
    align-items: center;
    gap: 3px;
    height: 18px;
}

.fib__sound-wave span {
    width: 3px;
    border-radius: 2px;
    background: var(--speaking);
    animation: sound-bar 0.8s ease-in-out infinite alternate;
}

@keyframes sound-bar {
    0% {
        height: 4px;
    }

    100% {
        height: 14px;
    }
}

/* Stop button within active state */
.fib__stop-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-full);
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--text-secondary);
    cursor: pointer;
    flex-shrink: 0;
    transition: background var(--transition-fast),
        color var(--transition-fast),
        border-color var(--transition-fast);
}

.fib__stop-btn:hover {
    background: var(--surface-3);
    color: var(--text-primary);
    border-color: var(--border-hover);
}

.fib__stop-btn--rec {
    border-color: var(--listening-border);
    color: var(--listening);
}

.fib__stop-btn--rec:hover {
    background: var(--listening-dim);
    border-color: var(--listening-border);
    color: var(--listening);
}

/* ── Input area (idle) ── */
.fib__input-area {
    grid-area: 1 / 1;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
}

/* Toolbar */
.fib__toolbar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    height: 32px;
}

.fib__dot {
    width: 7px;
    height: 7px;
    border-radius: var(--radius-full);
    flex-shrink: 0;
}

.dot--ok {
    background: var(--success);
}

.dot--err {
    background: var(--danger);
}

.fib__gap {
    flex: 1;
}

.fib__selectors {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
}

/* Body row */
.fib__body {
    display: flex;
    align-items: flex-end;
    gap: var(--space-1);
}

/* Attach button */
.fib__attach {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 34px;
    height: 34px;
    border-radius: var(--radius-md);
    border: none;
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    transition: color var(--transition-fast), background var(--transition-fast);
}

.fib__attach:hover:not(:disabled) {
    background: var(--surface-hover);
    color: var(--accent);
}

.fib__attach:disabled {
    opacity: var(--opacity-disabled);
    cursor: not-allowed;
}

.fib__file-input {
    display: none;
}

/* Textarea */
.fib__textarea {
    flex: 1;
    min-width: 0;
    min-height: 34px;
    max-height: 120px;
    padding: 7px 6px;
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

.fib__textarea::placeholder {
    color: var(--text-muted);
    letter-spacing: 0.02em;
}

.fib__textarea:disabled {
    opacity: var(--opacity-muted);
    cursor: not-allowed;
}

/* Actions (mic + send/stop) */
.fib__actions {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
}

.fib__send {
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

.fib__send:hover:not(:disabled) {
    background: var(--surface-2);
    color: var(--text-primary);
    ;
}

.fib__send:not(:disabled) {
    animation: none;
}

.fib__send:disabled {
    opacity: var(--opacity-disabled);
    cursor: not-allowed;
    animation: none;
}

.fib__stop {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 34px;
    height: 34px;
    border-radius: var(--radius-md);
    border: 1px solid var(--danger);
    background: var(--surface-1);
    color: var(--danger);
    cursor: pointer;
    transition: background var(--transition-fast);
}

.fib__stop:hover {
    background: var(--surface-hover);
}

/* ── Thumbnails ── */
.fib__thumbs {
    display: flex;
    gap: var(--space-2);
    overflow-x: auto;
    padding-bottom: var(--space-1);
    scrollbar-width: none;
}

.fib__thumbs::-webkit-scrollbar {
    display: none;
}

.fib__thumb {
    position: relative;
    flex-shrink: 0;
    width: 48px;
    height: 48px;
    border-radius: var(--radius-md);
    overflow: hidden;
    border: 1px solid var(--border);
}

.fib__thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}

.fib__thumb-rm {
    position: absolute;
    top: 2px;
    right: 2px;
    width: 16px;
    height: 16px;
    border-radius: var(--radius-full);
    background: var(--surface-0);
    border: 1px solid var(--border);
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    padding: 0;
    opacity: 0;
    transition: opacity var(--transition-fast);
}

.fib__thumb:hover .fib__thumb-rm {
    opacity: 1;
}

.fib__thumb-rm:hover {
    background: var(--surface-hover);
    color: var(--danger);
}

/* ── Transitions ── */
.fib-state-enter-active,
.fib-state-leave-active {
    transition: opacity var(--duration-normal) ease, transform var(--duration-normal) ease;
}

.fib-state-enter-from {
    opacity: 0;
    transform: scale(0.95);
}

.fib-state-leave-to {
    opacity: 0;
    transform: scale(0.95);
}

.fib-input-enter-active,
.fib-input-leave-active {
    transition: opacity var(--duration-normal) ease, transform var(--duration-normal) ease;
}

.fib-input-enter-from {
    opacity: 0;
    transform: translateY(8px);
}

.fib-input-leave-to {
    opacity: 0;
    transform: translateY(8px);
}

.btn-swap-enter-active,
.btn-swap-leave-active {
    transition: opacity var(--duration-fast) ease, transform var(--duration-fast) ease;
}

.btn-swap-enter-from {
    opacity: 0;
    transform: scale(0.8);
}

.btn-swap-leave-to {
    opacity: 0;
    transform: scale(0.8);
}

/* ── Reduced motion ── */
@media (prefers-reduced-motion: reduce) {

    .fib,
    .fib__stop-btn,
    .fib__send,
    .fib__stop,
    .fib__attach {
        transition: none;
    }

    .fib--listening,
    .fib--thinking {
        animation: none;
    }

    .fib__wave-bar,
    .fib__dots span,
    .fib__sound-wave span,
    .fib__spinner {
        animation: none;
    }
}
</style>
