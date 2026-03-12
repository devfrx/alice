<script setup lang="ts">
/**
 * AssistantView.vue — Living AI consciousness mode.
 *
 * Centers the OMNIA orb as the primary interaction point.
 * Voice-first: the user speaks, the orb reacts, and responds.
 * Shows floating status bubbles for current activity.
 */
import { computed, inject, onMounted, ref, watch } from 'vue'
import OmniaOrb from '../components/assistant/OmniaOrb.vue'
import AmbientBackground from '../components/assistant/AmbientBackground.vue'
import StatusBubbles from '../components/assistant/StatusBubbles.vue'
import QuickActions from '../components/assistant/QuickActions.vue'
import AssistantResponse from '../components/assistant/AssistantResponse.vue'
import AssistantTranscript from '../components/assistant/AssistantTranscript.vue'
import FloatingInputBar from '../components/input/FloatingInputBar.vue'
import ToolConfirmationDialog from '../components/chat/ToolConfirmationDialog.vue'
import { ChatApiKey } from '../composables/useChat'
import { useVoice } from '../composables/useVoice'
import { useChatStore } from '../stores/chat'
import { useVoiceStore } from '../stores/voice'

const chatStore = useChatStore()
const voiceStore = useVoiceStore()
const chatApi = inject(ChatApiKey)!
const { sendMessage: send, stopGeneration } = chatApi

const {
    startListening, stopListening, cancelProcessing, connect: connectVoice,
    transcript, speak, cancelSpeak,
    audioDevices, selectedDeviceId, refreshDevices,
} = useVoice()

/** Template ref for the floating input bar. */
const floatingBarRef = ref<InstanceType<typeof FloatingInputBar> | null>(null)

/** Pending tool confirmations for ToolConfirmationDialog. */
const pendingConfirmationsList = computed(() =>
    Object.values(chatStore.pendingConfirmations)
)

/** Determine the orb's state based on what OMNIA is doing. */
const orbState = computed<'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'>(() => {
    if (voiceStore.isSpeaking) return 'speaking'
    if (voiceStore.isListening) return 'listening'
    if (voiceStore.isProcessing) return 'processing'
    if (chatStore.isStreamingCurrentConversation) return 'thinking'
    return 'idle'
})

const audioLevel = computed(() => voiceStore.audioLevel)

/** Last assistant response for display. */
const lastResponse = computed(() => {
    const msgs = chatStore.messages
    for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'assistant' && msgs[i].content?.trim()) {
            return msgs[i].content
        }
    }
    return ''
})

/** Stream content for real-time display. */
const streamContent = computed(() => chatStore.currentStreamContent)

/** Thinking/reasoning content for display. */
const thinkingContent = computed(() => chatStore.currentThinkingContent)

/** Show the last response when idle or while TTS is speaking (not during new input). */
const showLastResponse = computed(() =>
    orbState.value === 'idle' || orbState.value === 'speaking'
)

/** Whether the orb tap should act as a "stop" action. */
const isInterruptible = computed(() =>
    orbState.value === 'thinking' || orbState.value === 'speaking'
)

/** Send a text message with optional file attachments. */
async function handleSend(content: string, attachments: File[]): Promise<void> {
    await send(content, undefined, attachments)
}

function handleOrbClick(): void {
    if (voiceStore.isSpeaking) {
        cancelSpeak()
    } else if (chatStore.isStreamingCurrentConversation) {
        stopGeneration()
        cancelSpeak()
    } else if (voiceStore.isListening) {
        stopListening()
    } else if (voiceStore.isProcessing) {
        cancelProcessing()
    } else {
        startListening()
    }
}

// Auto-send transcript when confirmation is disabled
watch(
    () => voiceStore.transcript,
    (text) => {
        if (!text.trim()) return
        if (voiceStore.confirmTranscript) return
        const toSend = text.trim()
        voiceStore.clearTranscript()
        send(toSend).catch(console.error)
    }
)

// Flush pending transcript if user toggles confirm → auto-send mid-flight
watch(
    () => voiceStore.confirmTranscript,
    (confirm) => {
        if (!confirm && voiceStore.transcript.trim()) {
            const t = voiceStore.transcript.trim()
            voiceStore.clearTranscript()
            send(t).catch(console.error)
        }
    }
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
    if (!chatStore.currentConversation) {
        chatStore.createConversation().catch(console.error)
    }
})
</script>

<template>
    <div class="assistant-view">
        <AmbientBackground :state="orbState" :audio-level="audioLevel" />

        <div class="assistant-view__center">
            <!-- Orb wrapper: overflow visible so glow effects aren't clipped -->
            <div class="assistant-view__orb-wrapper">
                <OmniaOrb :state="orbState" :audio-level="audioLevel" @click="handleOrbClick" />
                <!-- Floating stop hint during generation or TTS -->
                <Transition name="stop-hint-fade">
                    <button v-if="isInterruptible" class="assistant-view__stop-hint" @click.stop="handleOrbClick"
                        aria-label="Interrompi">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                            <rect x="4" y="4" width="16" height="16" rx="2" />
                        </svg>
                        <span>Interrompi</span>
                    </button>
                </Transition>
            </div>

            <!-- Scrollable content area for responses/transcript -->
            <div class="assistant-view__content">
                <!-- Response area -->
                <Transition name="response-fade">
                    <AssistantResponse v-if="streamContent || thinkingContent || (lastResponse && showLastResponse)"
                        :content="streamContent || (showLastResponse ? lastResponse : '')"
                        :is-streaming="!!streamContent || (!!thinkingContent && !streamContent)"
                        :thinking-content="thinkingContent || ''" key="response" />
                </Transition>

                <!-- Transcript -->
                <Transition name="transcript-fade">
                    <AssistantTranscript v-if="transcript || voiceStore.isListening || voiceStore.isProcessing"
                        :text="transcript" :is-listening="voiceStore.isListening"
                        :is-processing="voiceStore.isProcessing" :audio-level="audioLevel" />
                </Transition>
            </div>
        </div>

        <StatusBubbles :state="orbState" />
        <QuickActions />

        <!-- Tool confirmation dialog -->
        <!-- Floating input bar -->
        <FloatingInputBar ref="floatingBarRef" :disabled="chatStore.isStreamingCurrentConversation"
            :is-connected="chatApi.isConnected.value" :is-streaming="chatStore.isStreamingCurrentConversation"
            :audio-devices="audioDevices" :selected-device-id="selectedDeviceId" :orb-state="orbState"
            @send="handleSend" @stop="() => { stopGeneration(); cancelSpeak() }" @voice-start="startListening"
            @voice-stop="stopListening" @voice-cancel-processing="cancelProcessing" @refresh-devices="refreshDevices"
            @select-device="(id) => { selectedDeviceId = id }" />

        <ToolConfirmationDialog v-if="pendingConfirmationsList.length > 0"
            :key="pendingConfirmationsList[0].executionId" :confirmation="pendingConfirmationsList[0]"
            @respond="chatApi.respondToConfirmation" />
    </div>
</template>

<style scoped>
.assistant-view {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--surface-0);
}

.assistant-view__center {
    position: relative;
    z-index: 2;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-6);
    padding: var(--space-4) 0;
}

/* Orb wrapper: no overflow clipping so effects render fully */
.assistant-view__orb-wrapper {
    position: relative;
    flex-shrink: 0;
}

/* Stop / interrupt pill below the orb */
.assistant-view__stop-hint {
    position: absolute;
    bottom: -36px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 14px;
    border: 1px solid var(--border);
    border-radius: 20px;
    background: var(--surface-2);
    color: var(--accent);
    font-size: var(--text-2xs);
    font-weight: 500;
    white-space: nowrap;
    cursor: pointer;
    transition: background var(--transition-fast), border-color var(--transition-fast);
    z-index: 5;
}

.assistant-view__stop-hint:hover {
    background: var(--surface-3);
    border-color: var(--border-hover);
}

/* Stop hint transitions */
.stop-hint-fade-enter-active {
    transition: opacity 0.25s ease, transform 0.25s ease;
}

.stop-hint-fade-leave-active {
    transition: opacity 0.15s ease, transform 0.15s ease;
}

.stop-hint-fade-enter-from {
    opacity: 0;
    transform: translateX(-50%) translateY(-6px);
}

.stop-hint-fade-leave-to {
    opacity: 0;
    transform: translateX(-50%) translateY(-6px);
}

/* Scrollable area for response + transcript only */
.assistant-view__content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-4);
    max-height: 50vh;
    overflow-y: auto;
    scrollbar-width: none;
    width: 100%;
}

.assistant-view__content::-webkit-scrollbar {
    display: none;
}

/* Transitions */
.response-fade-enter-active,
.response-fade-leave-active {
    transition: opacity 0.3s ease, transform 0.3s ease;
}

.response-fade-enter-from {
    opacity: 0;
    transform: translateY(10px);
}

.response-fade-leave-to {
    opacity: 0;
    transform: translateY(-10px);
}

.transcript-fade-enter-active,
.transcript-fade-leave-active {
    transition: opacity 0.3s ease, transform 0.3s ease;
}

.transcript-fade-enter-from {
    opacity: 0;
    transform: scale(0.95);
}

.transcript-fade-leave-to {
    opacity: 0;
    transform: scale(0.95);
}

@keyframes blink {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.3;
    }
}
</style>
