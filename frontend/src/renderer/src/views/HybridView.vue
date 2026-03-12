<script setup lang="ts">
/**
 * HybridView.vue — Chat + living AI visualization combined.
 *
 * The chat messages appear below a condensed orb that reacts to state.
 * Best of both worlds: conversational + ambient presence.
 */
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import OmniaOrb from '../components/assistant/OmniaOrb.vue'
import AmbientBackground from '../components/assistant/AmbientBackground.vue'
import ChatInput from '../components/chat/ChatInput.vue'
import MessageBubble from '../components/chat/MessageBubble.vue'
import StreamingIndicator from '../components/chat/StreamingIndicator.vue'
import ToolConfirmationDialog from '../components/chat/ToolConfirmationDialog.vue'
import TranscriptOverlay from '../components/voice/TranscriptOverlay.vue'
import { ChatApiKey } from '../composables/useChat'
import { useVoice } from '../composables/useVoice'
import { useChatStore } from '../stores/chat'
import { useVoiceStore } from '../stores/voice'

const chatStore = useChatStore()
const chatApi = inject(ChatApiKey)!
const voiceStore = useVoiceStore()
const { sendMessage: send, isConnected, stopGeneration } = chatApi
const {
    startListening, stopListening, cancelProcessing, connect: connectVoice,
    transcript, audioDevices, selectedDeviceId, refreshDevices, speak, cancelSpeak,
} = useVoice()

/** Template ref to access ChatInput's pending files for voice sends. */
const chatInputRef = ref<InstanceType<typeof ChatInput> | null>(null)
const messagesContainer = ref<HTMLElement | null>(null)
const showScrollButton = ref(false)

const orbState = computed<'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'>(() => {
    if (voiceStore.isSpeaking) return 'speaking'
    if (voiceStore.isListening) return 'listening'
    if (voiceStore.isProcessing) return 'processing'
    if (chatStore.isStreamingCurrentConversation) return 'thinking'
    return 'idle'
})

const pendingConfirmationsList = computed(() =>
    Object.values(chatStore.pendingConfirmations)
)

function scrollToBottom(force = false): void {
    const el = messagesContainer.value
    if (!el) return
    if (!force) {
        const threshold = 100
        if (el.scrollHeight - el.scrollTop - el.clientHeight > threshold) return
    }
    nextTick(() => { if (el) el.scrollTop = el.scrollHeight })
}

function handleScroll(): void {
    const el = messagesContainer.value
    if (!el) return
    showScrollButton.value = el.scrollHeight - el.scrollTop - el.clientHeight > 200
}

function handleTranscriptSend(text: string): void {
    voiceStore.clearTranscript()
    const files = voiceStore.sttIncludeAttachments
        ? [...(chatInputRef.value?.pendingFiles ?? [])]
        : undefined
    send(text, undefined, files).then(() => {
        if (files?.length) chatInputRef.value?.clearPendingFiles()
        scrollToBottom(true)
    }).catch(console.error)
}

function handleTranscriptDismiss(): void {
    voiceStore.clearTranscript()
}

async function handleSend(content: string, attachments: File[]): Promise<void> {
    await send(content, undefined, attachments)
    scrollToBottom(true)
}

// Auto-send transcript when confirmation is disabled
watch(
    () => voiceStore.transcript,
    (text) => {
        if (!text.trim()) return
        if (voiceStore.confirmTranscript) return
        const toSend = text.trim()
        voiceStore.clearTranscript()
        const files = voiceStore.sttIncludeAttachments
            ? [...(chatInputRef.value?.pendingFiles ?? [])]
            : undefined
        send(toSend, undefined, files).then(() => {
            if (files?.length) chatInputRef.value?.clearPendingFiles()
            scrollToBottom(true)
        }).catch(console.error)
    }
)

// Flush pending transcript if user toggles confirm → auto-send mid-flight
watch(
    () => voiceStore.confirmTranscript,
    (confirm) => {
        if (!confirm && voiceStore.transcript.trim()) {
            const t = voiceStore.transcript.trim()
            voiceStore.clearTranscript()
            const files = voiceStore.sttIncludeAttachments
                ? [...(chatInputRef.value?.pendingFiles ?? [])]
                : undefined
            send(t, undefined, files).then(() => {
                if (files?.length) chatInputRef.value?.clearPendingFiles()
                scrollToBottom(true)
            }).catch(console.error)
        }
    }
)

watch(
    () => [chatStore.messages.length, chatStore.currentStreamContent],
    () => scrollToBottom()
)

// TTS auto-speak when streaming completes
let wasStreamingHere = false
watch(
    () => chatStore.isStreamingCurrentConversation,
    (streaming) => {
        if (streaming) {
            wasStreamingHere = true
        } else if (wasStreamingHere) {
            wasStreamingHere = false
            if (!voiceStore.autoTtsResponse || !voiceStore.ttsAvailable || !voiceStore.connected) return
            const msgs = chatStore.messages
            const lastMsg = msgs[msgs.length - 1]
            if (lastMsg?.role === 'assistant' && lastMsg.content?.trim()) speak(lastMsg.content)
        }
    }
)

onMounted(() => {
    connectVoice()
    if (!chatStore.currentConversation) chatStore.createConversation().catch(console.error)
    messagesContainer.value?.addEventListener('scroll', handleScroll)
})
onUnmounted(() => {
    messagesContainer.value?.removeEventListener('scroll', handleScroll)
})
</script>

<template>
    <div class="hybrid-view">
        <AmbientBackground :state="orbState" :audio-level="voiceStore.audioLevel" :subtle="true" />

        <!-- Floating orb (compact, top area) -->
        <div class="hybrid-view__orb-area">
            <OmniaOrb :state="orbState" :audio-level="voiceStore.audioLevel" :compact="true" />
        </div>

        <!-- Chat area -->
        <div class="hybrid-view__chat">
            <div ref="messagesContainer" class="hybrid-view__messages">
                <div v-if="chatStore.messages.length === 0 && !chatStore.isStreamingCurrentConversation"
                    class="hybrid-view__empty">
                    <p class="hybrid-view__empty-text">Scrivi o parla per iniziare</p>
                </div>

                <MessageBubble v-for="msg in chatStore.messages" :key="msg.id" :message="msg" />

                <StreamingIndicator v-if="chatStore.isStreamingCurrentConversation"
                    :content="chatStore.currentStreamContent" :thinking-content="chatStore.currentThinkingContent" />

                <Transition name="scroll-btn">
                    <button v-if="showScrollButton" class="hybrid-view__scroll-btn" @click="scrollToBottom(true)">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2">
                            <polyline points="6 9 12 15 18 9" />
                        </svg>
                    </button>
                </Transition>
            </div>

            <div class="hybrid-view__input-wrapper">
                <TranscriptOverlay :text="transcript" :is-processing="voiceStore.isProcessing"
                    :is-recording="voiceStore.isListening" :audio-level="voiceStore.audioLevel"
                    :duration="voiceStore.formattedDuration" :auto-send="!voiceStore.confirmTranscript"
                    @send="handleTranscriptSend" @dismiss="handleTranscriptDismiss" />
                <ChatInput ref="chatInputRef" :disabled="chatStore.isStreamingCurrentConversation"
                    :is-connected="isConnected" :is-streaming="chatStore.isStreamingCurrentConversation"
                    :audio-devices="audioDevices" :selected-device-id="selectedDeviceId" @send="handleSend"
                    @stop="() => { stopGeneration(); cancelSpeak() }" @voice-start="startListening"
                    @voice-stop="stopListening" @voice-cancel-processing="cancelProcessing"
                    @refresh-devices="refreshDevices" @select-device="(id) => { selectedDeviceId = id }" />
            </div>
        </div>

        <ToolConfirmationDialog v-if="pendingConfirmationsList.length > 0"
            :key="pendingConfirmationsList[0].executionId" :confirmation="pendingConfirmationsList[0]"
            @respond="chatApi.respondToConfirmation" />
    </div>
</template>

<style scoped>
.hybrid-view {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--surface-0);
}

.hybrid-view__orb-area {
    position: relative;
    z-index: 2;
    display: flex;
    justify-content: center;
    padding: var(--space-3) 0;
    flex-shrink: 0;
}

.hybrid-view__chat {
    position: relative;
    z-index: 2;
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.hybrid-view__messages {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-4) var(--space-6);
    scroll-behavior: smooth;
}

.hybrid-view__messages::-webkit-scrollbar {
    width: 5px;
}

.hybrid-view__messages::-webkit-scrollbar-track {
    background: transparent;
}

.hybrid-view__messages::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 3px;
}

.hybrid-view__messages::-webkit-scrollbar-thumb:hover {
    background: var(--border-hover);
}

.hybrid-view__empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: var(--space-2);
}

.hybrid-view__empty-text {
    font-size: var(--text-sm);
    color: var(--text-muted);
    letter-spacing: var(--tracking-wide);
}

.hybrid-view__input-wrapper {
    position: relative;
    flex-shrink: 0;
}

.hybrid-view__scroll-btn {
    position: sticky;
    bottom: var(--space-3);
    left: 50%;
    transform: translateX(-50%);
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
    transition:
        background var(--transition-fast),
        color var(--transition-fast);
}

.hybrid-view__scroll-btn:hover {
    background: var(--surface-3);
    color: var(--text-primary);
}

.scroll-btn-enter-active,
.scroll-btn-leave-active {
    transition: opacity 0.2s, transform 0.2s;
}

.scroll-btn-enter-from,
.scroll-btn-leave-to {
    opacity: 0;
    transform: translateX(-50%) translateY(8px);
}
</style>
