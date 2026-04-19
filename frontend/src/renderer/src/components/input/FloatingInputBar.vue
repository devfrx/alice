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
import { useRouter } from 'vue-router'
import type { AudioDevice } from '../../composables/useVoice'
import AppIcon from '../ui/AppIcon.vue'
import ModelSelector from '../settings/ModelSelector.vue'
import MicrophoneButton from '../voice/MicrophoneButton.vue'
import ContextBar from '../chat/ContextBar.vue'
import { useChatStore } from '../../stores/chat'
import { useSettingsStore } from '../../stores/settings'
import { useUIStore } from '../../stores/ui'
import { useVoiceStore } from '../../stores/voice'
import { useToast } from '../../composables/useToast'

const router = useRouter()
const chatStore = useChatStore()
const settingsStore = useSettingsStore()
const uiStore = useUIStore()
const voiceStore = useVoiceStore()
const toast = useToast()

const supportsVision = computed(() => settingsStore.activeModel?.capabilities.vision ?? false)
const supportsToolUse = computed(() => settingsStore.activeModel?.capabilities.trained_for_tool_use ?? false)
const supportsThinking = computed(() => settingsStore.activeModel?.capabilities.thinking ?? false)

/** Toggle between assistant and hybrid mode. */
function toggleMode(): void {
    const next = uiStore.mode === 'assistant' ? 'hybrid' : 'assistant'
    uiStore.setMode(next)
    router.push({ name: next })
}

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
    if (imageFiles.length < files.length) {
        toast.warning('Solo file immagine sono supportati')
    }
    if (!supportsVision.value && imageFiles.length > 0) {
        toast.warning('Il modello attivo non supporta immagini')
        return
    }
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
                        <AppIcon name="stop-fill" :size="14" />
                    </button>
                </template>

                <!-- Processing state -->
                <template v-else-if="orbState === 'processing'">
                    <div class="fib__spinner" />
                    <span class="fib__state-label fib__state-label--shimmer">{{ stateLabel }}</span>
                    <button class="fib__stop-btn" aria-label="Annulla">
                        <AppIcon name="x" :size="12" :stroke-width="2.5" />
                    </button>
                </template>

                <!-- Thinking / Generating -->
                <template v-else-if="orbState === 'thinking'">
                    <div class="fib__dots">
                        <span /><span /><span />
                    </div>
                    <span class="fib__state-label">{{ stateLabel }}</span>
                    <button class="fib__stop-btn" aria-label="Interrompi generazione">
                        <AppIcon name="stop-fill" :size="14" />
                    </button>
                </template>

                <!-- Speaking -->
                <template v-else-if="orbState === 'speaking'">
                    <div class="fib__sound-wave">
                        <span v-for="i in 4" :key="i" :style="{ animationDelay: `${(i - 1) * 0.15}s` }" />
                    </div>
                    <span class="fib__state-label">{{ stateLabel }}</span>
                    <button class="fib__stop-btn" aria-label="Interrompi">
                        <AppIcon name="stop-fill" :size="14" />
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
                            <AppIcon name="x" :size="10" :stroke-width="2.5" />
                        </button>
                    </div>
                </div>

                <!-- Toolbar (always visible in idle state) -->
                <div class="fib__toolbar">
                    <!-- Status cluster: dot + badges -->
                    <div class="fib__status">
                        <div class="fib__dot" :class="isConnected ? 'dot--ok' : 'dot--err'" />
                        <div v-if="settingsStore.activeModel" class="fib__badges">
                            <span class="fib__badge" :class="{ 'fib__badge--on': supportsVision }" title="Vision">
                                <AppIcon name="eye" :size="11" />
                            </span>
                            <span class="fib__badge" :class="{ 'fib__badge--on': supportsThinking }" title="Thinking">
                                <AppIcon name="lightbulb-simple" :size="11" />
                            </span>
                            <span class="fib__badge" :class="{ 'fib__badge--on': supportsToolUse }" title="Tool Use">
                                <AppIcon name="tool" :size="11" />
                            </span>
                        </div>
                    </div>

                    <!-- Context bar -->
                    <ContextBar :context-info="chatStore.contextInfo"
                        :is-compressing="chatStore.isCompressingContext" />

                    <div class="fib__gap" />

                    <!-- Mode toggle chip -->
                    <button class="fib__mode-toggle" @click="toggleMode">
                        <template v-if="uiStore.mode === 'assistant'">
                            <AppIcon name="message" :size="11" />
                            <span>Ibrida</span>
                        </template>
                        <template v-else>
                            <AppIcon name="orb" :size="11" />
                            <span>Assistente</span>
                        </template>
                    </button>

                    <!-- Divider -->
                    <div v-if="isExpanded" class="fib__divider" />

                    <!-- Model selectors (only when expanded) -->
                    <div v-if="isExpanded" class="fib__selectors">
                        <ModelSelector model-type="embedding" />
                        <ModelSelector model-type="llm" />
                    </div>
                </div>

                <!-- Main row -->
                <div class="fib__body">
                    <!-- Attach button -->
                    <button class="fib__attach" :disabled="disabled || !supportsVision"
                        :aria-label="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
                        :title="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
                        @click="openFilePicker">
                        <AppIcon name="paperclip" :size="16" />
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
                                <AppIcon name="stop" :size="16" />
                            </button>
                            <button v-else key="send" class="fib__send"
                                :disabled="(!text.trim() && pendingFiles.length === 0) || disabled"
                                aria-label="Invia messaggio" @click="submit">
                                <AppIcon name="send" :size="16" />
                            </button>
                        </Transition>
                    </div>
                </div>
            </div>
        </Transition>
    </div>
</template>

<style scoped>
/* ── Root — Floating input pill ──
 * Anchored to the nearest positioned ancestor (e.g. `.assistant-view__main`)
 * so it stays centered in the same column as the orb / conversation,
 * regardless of any side panel that might shrink the main area.
 */
.fib {
    position: absolute;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    z-index: var(--z-dropdown);
    min-width: 320px;
    max-width: 600px;
    width: auto;

    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur-heavy));
    -webkit-backdrop-filter: blur(var(--glass-blur-heavy));
    border: 1px solid var(--glass-border);
    border-radius: 20px;
    padding: var(--space-2) var(--space-3);

    box-shadow:
        var(--shadow-floating),
        inset 0 1px 0 var(--white-subtle);
    transition:
        left 350ms var(--ease-out-expo),
        border-color 300ms var(--ease-smooth),
        box-shadow 300ms var(--ease-smooth),
        padding 250ms var(--ease-out-expo),
        min-width 250ms var(--ease-out-expo),
        max-width 250ms var(--ease-out-expo),
        background 300ms var(--ease-smooth);

    display: grid;
}

.fib:focus-within {
    border-color: var(--glass-border-hover);
    box-shadow:
        var(--shadow-floating),
        0 0 24px var(--accent-glow),
        inset 0 1px 0 var(--white-subtle);
}

/* Expanded input */
.fib--expanded {
    min-width: 420px;
    max-width: min(900px, calc(100vw - 48px));
    background: var(--glass-bg);
    box-shadow:
        var(--shadow-floating),
        var(--shadow-lg),
        inset 0 1px 0 var(--white-subtle);
}

/* Active states pill */
.fib--active {
    min-width: 280px;
    max-width: 400px;
    padding: var(--space-2) var(--space-4);
}

/* Listening — warm glow */
.fib--listening {
    border-color: var(--listening-border);
    box-shadow:
        var(--shadow-floating),
        0 0 20px var(--listening-dim),
        inset 0 1px 0 var(--listening-border);
}

/* Thinking — cream glow */
.fib--thinking {
    border-color: var(--thinking-border);
    box-shadow:
        var(--shadow-floating),
        0 0 20px var(--thinking-dim),
        inset 0 1px 0 var(--accent-faint);
}

/* Speaking — green glow */
.fib--speaking {
    border-color: var(--speaking-border);
    box-shadow:
        var(--shadow-floating),
        0 0 20px var(--speaking-dim),
        inset 0 1px 0 var(--speaking-border);
}

/* Drag over — accent highlight */
.fib--drag {
    border-color: var(--accent-border);
    box-shadow:
        var(--shadow-floating),
        0 0 28px var(--accent-glow),
        inset 0 0 12px var(--accent-faint);
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
    height: 22px;
}

.fib__wave-bar {
    width: 3px;
    border-radius: 3px;
    background: var(--listening);
    animation: wave-bounce 0.7s cubic-bezier(0.45, 0, 0.55, 1) infinite alternate;
    transform-origin: center;
}

.fib__wave-bar:nth-child(1) {
    animation-duration: 0.65s;
}

.fib__wave-bar:nth-child(2) {
    animation-duration: 0.55s;
}

.fib__wave-bar:nth-child(3) {
    animation-duration: 0.7s;
}

.fib__wave-bar:nth-child(4) {
    animation-duration: 0.5s;
}

.fib__wave-bar:nth-child(5) {
    animation-duration: 0.6s;
}

@keyframes wave-bounce {
    0% {
        height: 4px;
        opacity: 0.5;
    }

    50% {
        opacity: 1;
    }

    100% {
        height: 18px;
        opacity: 0.8;
    }
}

/* Spinner (processing) */
.fib__spinner {
    width: 18px;
    height: 18px;
    border: 2px solid transparent;
    border-top-color: var(--accent);
    border-right-color: var(--accent-dim);
    border-radius: var(--radius-full);
    animation: spin 0.9s cubic-bezier(0.4, 0, 0.2, 1) infinite;
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
    width: 5px;
    height: 5px;
    border-radius: var(--radius-full);
    background: var(--accent);
    animation: dot-float 1.6s var(--ease-bounce) infinite;
}

.fib__dots span:nth-child(2) {
    animation-delay: 0.2s;
}

.fib__dots span:nth-child(3) {
    animation-delay: 0.4s;
}

@keyframes dot-float {

    0%,
    100% {
        opacity: 0.3;
        transform: translateY(0) scale(0.8);
    }

    40% {
        opacity: 1;
        transform: translateY(-4px) scale(1.15);
    }

    70% {
        opacity: 0.6;
        transform: translateY(1px) scale(0.95);
    }
}

/* Sound wave (speaking) */
.fib__sound-wave {
    display: flex;
    align-items: center;
    gap: 3px;
    height: 20px;
}

.fib__sound-wave span {
    width: 3px;
    border-radius: 3px;
    background: var(--speaking);
    animation: sound-bar 0.7s cubic-bezier(0.45, 0, 0.55, 1) infinite alternate;
    transform-origin: center;
}

.fib__sound-wave span:nth-child(1) {
    animation-duration: 0.55s;
    height: 4px;
}

.fib__sound-wave span:nth-child(2) {
    animation-duration: 0.7s;
    height: 6px;
}

.fib__sound-wave span:nth-child(3) {
    animation-duration: 0.5s;
    height: 4px;
}

.fib__sound-wave span:nth-child(4) {
    animation-duration: 0.65s;
    height: 5px;
}

@keyframes sound-bar {
    0% {
        height: 4px;
        opacity: 0.5;
    }

    50% {
        opacity: 1;
    }

    100% {
        height: 16px;
        opacity: 0.7;
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
    transition:
        background 200ms var(--ease-smooth),
        color 200ms var(--ease-smooth),
        border-color 200ms var(--ease-smooth),
        transform 200ms var(--ease-out-back),
        box-shadow 200ms var(--ease-smooth);
}

.fib__stop-btn:hover {
    background: var(--surface-3);
    color: var(--text-primary);
    border-color: var(--border-hover);
    transform: scale(1.08);
}

.fib__stop-btn:active {
    transform: scale(0.92);
}

.fib__stop-btn--rec {
    border-color: var(--listening-border);
    color: var(--listening);
}

.fib__stop-btn--rec:hover {
    background: var(--listening-dim);
    border-color: var(--listening-border);
    color: var(--listening);
    box-shadow: 0 0 12px var(--listening-border);
}

/* ── Input area (idle) ── */
.fib__input-area {
    grid-area: 1 / 1;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
}

/* ── Toolbar ── */
.fib__toolbar {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    height: 32px;
    overflow: visible;
    min-width: 0;
}

/* Status cluster (dot + badges) */
.fib__status {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
    flex-shrink: 0;
}

.fib__dot {
    width: 7px;
    height: 7px;
    border-radius: var(--radius-full);
    flex-shrink: 0;
    transition: background 200ms var(--ease-smooth);
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
.fib__badges {
    display: flex;
    align-items: center;
    gap: 3px;
}

.fib__badge {
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

.fib__badge svg {
    width: 11px;
    height: 11px;
}

.fib__badge--on {
    color: var(--text-secondary);
    border-color: var(--border);
    background: var(--surface-2);
    opacity: 1;
}

/* Mode toggle — labeled chip */
.fib__mode-toggle {
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

.fib__mode-toggle:hover {
    color: var(--text-primary);
    border-color: var(--border-hover);
    background: var(--surface-3);
    box-shadow: 0 0 0 1px var(--white-subtle);
}

/* Divider */
.fib__divider {
    width: 1px;
    height: 16px;
    background: var(--border);
    flex-shrink: 0;
    opacity: 0.6;
}

.fib__gap {
    flex: 1;
    min-width: 0;
}

.fib__selectors {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
    flex-shrink: 0;
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
    transition:
        color 200ms var(--ease-smooth),
        background 200ms var(--ease-smooth),
        transform 200ms var(--ease-out-back);
}

.fib__attach:hover:not(:disabled) {
    background: var(--surface-hover);
    color: var(--accent);
    transform: scale(1.08) rotate(-8deg);
}

.fib__attach:active:not(:disabled) {
    transform: scale(0.92);
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
    color: var(--surface-0);
    cursor: pointer;
    transition:
        background 200ms var(--ease-smooth),
        color 200ms var(--ease-smooth),
        opacity 200ms var(--ease-smooth),
        box-shadow 200ms var(--ease-smooth),
        transform 200ms var(--ease-out-back),
        border-color 200ms var(--ease-smooth);
}

.fib__send:hover:not(:disabled) {
    background: var(--accent-hover);
    border-color: var(--accent);
    transform: scale(1.06);
    box-shadow: 0 0 16px var(--accent-glow);
}

.fib__send:active:not(:disabled) {
    transform: scale(0.92);
}

.fib__send:disabled {
    opacity: var(--opacity-disabled);
    cursor: not-allowed;
    background: var(--surface-3);
    color: var(--text-muted);
    border-color: var(--border);
}

.fib__stop {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 34px;
    height: 34px;
    border-radius: var(--radius-md);
    border: 1px solid var(--danger-border);
    background: var(--surface-1);
    color: var(--danger);
    cursor: pointer;
    transition:
        background 200ms var(--ease-smooth),
        transform 200ms var(--ease-out-back),
        box-shadow 200ms var(--ease-smooth);
}

.fib__stop:hover {
    background: var(--surface-hover);
    transform: scale(1.06);
    box-shadow: 0 0 12px var(--danger-glow);
}

.fib__stop:active {
    transform: scale(0.92);
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
    transition:
        opacity 200ms ease,
        transform 200ms var(--ease-out-back),
        color 150ms ease;
    transform: scale(0.7);
}

.fib__thumb:hover .fib__thumb-rm {
    opacity: 1;
    transform: scale(1);
}

.fib__thumb-rm:hover {
    background: var(--surface-hover);
    color: var(--danger);
    transform: scale(1.15);
}

/* ── Transitions ── */
.fib-state-enter-active {
    transition:
        opacity 350ms var(--ease-smooth),
        transform 350ms var(--ease-out-expo),
        filter 350ms var(--ease-smooth);
}

.fib-state-leave-active {
    transition:
        opacity 200ms ease,
        transform 200ms ease,
        filter 200ms ease;
}

.fib-state-enter-from {
    opacity: 0;
    transform: scale(0.9) translateY(4px);
    filter: blur(4px);
}

.fib-state-leave-to {
    opacity: 0;
    transform: scale(0.94);
    filter: blur(2px);
}

.fib-input-enter-active {
    transition:
        opacity 350ms var(--ease-smooth),
        transform 350ms var(--ease-out-expo),
        filter 350ms var(--ease-smooth);
}

.fib-input-leave-active {
    transition:
        opacity 200ms ease,
        transform 200ms ease,
        filter 200ms ease;
}

.fib-input-enter-from {
    opacity: 0;
    transform: translateY(10px) scale(0.97);
    filter: blur(4px);
}

.fib-input-leave-to {
    opacity: 0;
    transform: translateY(6px);
    filter: blur(2px);
}

.btn-swap-enter-active {
    transition:
        opacity 200ms var(--ease-smooth),
        transform 200ms var(--ease-out-back);
}

.btn-swap-leave-active {
    transition:
        opacity 120ms ease,
        transform 120ms ease;
}

.btn-swap-enter-from {
    opacity: 0;
    transform: scale(0.6) rotate(-12deg);
}

.btn-swap-leave-to {
    opacity: 0;
    transform: scale(0.7) rotate(12deg);
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

    .fib-state-enter-active,
    .fib-state-leave-active,
    .fib-input-enter-active,
    .fib-input-leave-active,
    .btn-swap-enter-active,
    .btn-swap-leave-active {
        transition: opacity 100ms ease;
    }

    .fib-state-enter-from,
    .fib-state-leave-to,
    .fib-input-enter-from,
    .fib-input-leave-to,
    .btn-swap-enter-from,
    .btn-swap-leave-to {
        transform: none;
        filter: none;
    }
}
</style>
