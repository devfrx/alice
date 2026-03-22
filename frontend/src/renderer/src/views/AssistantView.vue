<script setup lang="ts">
/**
 * AssistantView.vue — Living AI consciousness mode.
 *
 * Centers the AL\CE orb as the primary interaction point.
 * Voice-first: the user speaks, the orb reacts, and responds.
 * Shows floating status bubbles for current activity.
 *
 * When CAD models exist in the conversation, a side panel slides in
 * from the right with an interactive 3D viewer + prev/next navigation.
 */
import { computed, defineAsyncComponent, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AliceOrb from '../components/assistant/AliceOrb.vue'
import AmbientBackground from '../components/assistant/AmbientBackground.vue'
import StatusBubbles from '../components/assistant/StatusBubbles.vue'
import AssistantFab from '../components/assistant/AssistantFab.vue'
import AssistantResponse from '../components/assistant/AssistantResponse.vue'
import AssistantTranscript from '../components/assistant/AssistantTranscript.vue'
import ConversationDrawer from '../components/assistant/ConversationDrawer.vue'
import FloatingInputBar from '../components/input/FloatingInputBar.vue'
import ToolConfirmationDialog from '../components/chat/ToolConfirmationDialog.vue'
import MessageEditDialog from '../components/chat/MessageEditDialog.vue'
import { ChatApiKey } from '../composables/useChat'
import { useVoice } from '../composables/useVoice'
import { useChatStore } from '../stores/chat'
import { useVoiceStore } from '../stores/voice'
import type { CadModelPayload, ChartPayload, WhiteboardPayload, ToolCall } from '../types/chat'
import { isWhiteboardPayload } from '../types/chat'
import { api } from '../services/api'

const ImmersiveCADCanvas = defineAsyncComponent(
    () => import('../components/assistant/ImmersiveCADCanvas.vue')
)
const ChartViewer = defineAsyncComponent(
    () => import('../components/chat/ChartViewer.vue')
)
const TldrawCanvas = defineAsyncComponent(
    () => import('../components/whiteboard/TldrawCanvas.vue')
)

const chatStore = useChatStore()
const voiceStore = useVoiceStore()
const chatApi = inject(ChatApiKey)
if (!chatApi) throw new Error('ChatApiKey not provided')
const { sendMessage: send, stopGeneration, editMessage } = chatApi

const {
    startListening, stopListening, cancelProcessing, connect: connectVoice,
    transcript, speak, cancelSpeak,
    audioDevices, selectedDeviceId, refreshDevices,
} = useVoice()

/** Template ref for the floating input bar. */
const floatingBarRef = ref<InstanceType<typeof FloatingInputBar> | null>(null)

/** Whether the conversation history drawer is visible. */
const historyDrawerOpen = ref(false)

/* ── Message editing state ── */
const editingMessageId = ref<string | null>(null)
const editingContent = ref('')

function startEdit(messageId: string): void {
    if (chatStore.isStreamingCurrentConversation) return
    const msg = chatStore.messages.find((m) => m.id === messageId)
    if (!msg || msg.role !== 'user') return
    editingMessageId.value = messageId
    editingContent.value = msg.content
}

function submitEdit(newContent: string): void {
    const msgId = editingMessageId.value
    editingMessageId.value = null
    editingContent.value = ''
    if (msgId) editMessage(msgId, newContent)
}

function cancelEdit(): void {
    editingMessageId.value = null
    editingContent.value = ''
}

function handleVersionSwitch(versionGroupId: string, versionIndex: number): void {
    chatStore.switchVersion(versionGroupId, versionIndex)
}

async function handleBranch(messageId: string): Promise<void> {
    if (chatStore.isStreamingCurrentConversation) return
    await chatStore.branchConversation(messageId)
}

/** Whether the right side panel is visible (user can toggle). */
const sidePanelOpen = ref(false)
/** Active model index for multi-model navigation. */
const cadActiveIndex = ref(0)
/** Active chart index for multi-chart navigation. */
const chartActiveIndex = ref(0)
/** Active whiteboard index for multi-board navigation. */
const whiteboardActiveIndex = ref(0)
/** Which tab is active in the side panel: '3d', 'chart' or 'whiteboard'. */
const sidePanelTab = ref<'3d' | 'chart' | 'whiteboard'>('3d')

/* ── Resizable side panel ── */
const SIDE_PANEL_MIN = 280
const SIDE_PANEL_MAX = 800
const SIDE_PANEL_DEFAULT = 400
const sidePanelWidth = ref(SIDE_PANEL_DEFAULT)
const isDraggingPanel = ref(false)

function onResizeStart(e: MouseEvent): void {
    e.preventDefault()
    isDraggingPanel.value = true
    const startX = e.clientX
    const startW = sidePanelWidth.value

    function onMove(ev: MouseEvent): void {
        const delta = startX - ev.clientX
        sidePanelWidth.value = Math.min(
            SIDE_PANEL_MAX,
            Math.max(SIDE_PANEL_MIN, startW + delta)
        )
    }

    function onUp(): void {
        isDraggingPanel.value = false
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
}

onBeforeUnmount(() => {
    isDraggingPanel.value = false
})

/**
 * Collects ALL CAD model payloads from the conversation messages.
 * Returns them in chronological order (oldest first).
 */
const cadModels = computed((): CadModelPayload[] => {
    const result: CadModelPayload[] = []
    for (const msg of chatStore.messages) {
        if (msg.role !== 'tool') continue
        try {
            const p = JSON.parse(msg.content)
            if (p.model_name && p.export_url) result.push(p as CadModelPayload)
        } catch { /* not JSON */ }
    }
    return result
})

/** Whether any CAD models exist in the conversation. */
const hasCadModels = computed(() => cadModels.value.length > 0)

/** Auto-open the side panel when a new model appears, jump to it. */
watch(() => cadModels.value.length, (newLen, oldLen) => {
    if (newLen > oldLen) {
        sidePanelOpen.value = true
        sidePanelTab.value = '3d'
        cadActiveIndex.value = newLen - 1
    }
})

/** Clamp index if models shrink (conversation change). */
watch(cadModels, (models) => {
    if (cadActiveIndex.value >= models.length) {
        cadActiveIndex.value = Math.max(0, models.length - 1)
    }
})

function closeSidePanel(): void {
    sidePanelOpen.value = false
}

/** Persist whiteboard snapshot changes to backend. */
function saveWhiteboardSnapshot(boardId: string, snapshot: Record<string, unknown>): void {
    api.saveWhiteboardSnapshot(boardId, snapshot).catch(() => {
        /* silent — save is best-effort from the editor */
    })
}

/**
 * Collects ALL chart payloads from the conversation messages.
 * Returns them in chronological order (oldest first).
 */
const chartPayloads = computed((): ChartPayload[] => {
    const result: ChartPayload[] = []
    for (const msg of chatStore.messages) {
        if (msg.role !== 'tool') continue
        try {
            const p = JSON.parse(msg.content)
            if (p.chart_id && p.chart_url && p.chart_type) result.push(p as ChartPayload)
        } catch { /* not JSON */ }
    }
    return result
})

/** Whether any charts exist in the conversation. */
const hasCharts = computed(() => chartPayloads.value.length > 0)

/** The currently active chart for the side panel. */
const activeChart = computed((): ChartPayload | null =>
    chartPayloads.value[chartActiveIndex.value] ?? null
)

/** Auto-open the side panel on chart tab when a new chart appears. */
watch(() => chartPayloads.value.length, (newLen, oldLen) => {
    if (newLen > oldLen) {
        sidePanelOpen.value = true
        sidePanelTab.value = 'chart'
        chartActiveIndex.value = newLen - 1
    }
})

/** Clamp chart index if charts shrink (conversation change). */
watch(chartPayloads, (charts) => {
    if (chartActiveIndex.value >= charts.length) {
        chartActiveIndex.value = Math.max(0, charts.length - 1)
    }
})

/**
 * Collects ALL whiteboard payloads from the conversation messages.
 */
const whiteboardPayloads = computed((): WhiteboardPayload[] => {
    const result: WhiteboardPayload[] = []
    for (const msg of chatStore.messages) {
        if (msg.role !== 'tool') continue
        try {
            const p = JSON.parse(msg.content)
            if (isWhiteboardPayload(p)) result.push(p)
        } catch { /* not JSON */ }
    }
    return result
})

/** Whether any whiteboards exist in the conversation. */
const hasWhiteboards = computed(() => whiteboardPayloads.value.length > 0)

/** The currently active whiteboard for the side panel. */
const activeWhiteboard = computed((): WhiteboardPayload | null =>
    whiteboardPayloads.value[whiteboardActiveIndex.value] ?? null
)

/** Auto-open the side panel on whiteboard tab when a new board appears. */
watch(() => whiteboardPayloads.value.length, (newLen, oldLen) => {
    if (newLen > oldLen) {
        sidePanelOpen.value = true
        sidePanelTab.value = 'whiteboard'
        whiteboardActiveIndex.value = newLen - 1
    }
})

/** Clamp whiteboard index if boards shrink (conversation change). */
watch(whiteboardPayloads, (boards) => {
    if (whiteboardActiveIndex.value >= boards.length) {
        whiteboardActiveIndex.value = Math.max(0, boards.length - 1)
    }
})

/** Pending tool confirmations for ToolConfirmationDialog. */
const pendingConfirmationsList = computed(() =>
    Object.values(chatStore.pendingConfirmations)
)

/** Determine the orb's state based on what AL\CE is doing. */
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

/** Last user message for echo display above AL\CE's response. */
const lastUserQuery = computed(() => {
    const msgs = chatStore.messages
    for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'user' && msgs[i].content?.trim()) {
            return msgs[i].content
        }
    }
    return ''
})

/** Whether the conversation is empty (show greeting). */
const isConversationEmpty = computed(() => chatStore.messages.length === 0)

/** Message count for history badge. */
const messageCount = computed(() => chatStore.messages.length)

/** Tool calls from the latest turn (all assistant messages after the last user message). */
const lastToolCalls = computed((): ToolCall[] => {
    const msgs = chatStore.messages
    let lastUserIdx = -1
    for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === 'user') { lastUserIdx = i; break }
    }
    const calls: ToolCall[] = []
    for (let i = lastUserIdx + 1; i < msgs.length; i++) {
        const msg = msgs[i]
        if (msg.role === 'assistant' && msg.tool_calls?.length) {
            calls.push(...msg.tool_calls)
        }
    }
    return calls
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
            // Collect ALL assistant content from the current exchange
            // (intermediate messages with tool_calls + final answer)
            const lastUserIdx = msgs.findLastIndex(m => m.role === 'user')
            const allContent = msgs
                .slice(lastUserIdx + 1)
                .filter(m => m.role === 'assistant' && m.content?.trim())
                .map(m => m.content!.trim())
                .join('\n')
            if (allContent) speak(allContent)
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
    <div class="assistant-view" :class="{
        'assistant-view--panel-open': sidePanelOpen && (hasCadModels || hasCharts || hasWhiteboards),
        'assistant-view--dragging': isDraggingPanel
    }"
        :style="{ '--panel-width': `${sidePanelWidth}px`, '--panel-offset': sidePanelOpen && (hasCadModels || hasCharts || hasWhiteboards) ? `${sidePanelWidth}px` : '0px' }">
        <AmbientBackground :state="orbState" :audio-level="audioLevel" />

        <!-- Main area (orb + content) -->
        <div class="assistant-view__main">
            <div class="assistant-view__center">
                <div class="assistant-view__orb-wrapper">
                    <AliceOrb :state="orbState" :audio-level="audioLevel" @click="handleOrbClick" />
                    <!-- <Transition name="stop-hint-fade">
                        <button v-if="isInterruptible" class="assistant-view__stop-hint" @click.stop="handleOrbClick"
                            aria-label="Interrompi">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                                <rect x="4" y="4" width="16" height="16" rx="2" />
                            </svg>
                            <span>Interrompi</span>
                        </button>
                    </Transition> -->
                </div>

                <div class="assistant-view__content">
                    <!-- Idle greeting when no conversation -->
                    <Transition name="greeting-fade">
                        <div v-if="isConversationEmpty && !streamContent && !thinkingContent && orbState === 'idle'"
                            class="assistant-view__greeting" key="greeting">
                            <p class="assistant-view__greeting-text">Come posso aiutarti?</p>
                            <p class="assistant-view__greeting-hint">Parla o scrivi per iniziare</p>
                        </div>
                    </Transition>

                    <Transition name="response-fade">
                        <AssistantResponse
                            v-if="streamContent || thinkingContent || chatStore.activeToolExecutions.length > 0 || (lastResponse && showLastResponse)"
                            :content="streamContent || (showLastResponse ? lastResponse : '')"
                            :is-streaming="!!streamContent || (!!thinkingContent && !streamContent)"
                            :thinking-content="thinkingContent || ''" :tool-executions="chatStore.activeToolExecutions"
                            :tool-calls="lastToolCalls" :user-query="lastUserQuery" key="response" />
                    </Transition>

                    <Transition name="transcript-fade">
                        <AssistantTranscript v-if="transcript || voiceStore.isListening || voiceStore.isProcessing"
                            :text="transcript" :is-listening="voiceStore.isListening"
                            :is-processing="voiceStore.isProcessing" :audio-level="audioLevel" />
                    </Transition>
                </div>
            </div>

            <!-- <StatusBubbles :state="orbState" /> -->
            <AssistantFab :orb-state="orbState" :message-count="messageCount"
                @toggle-history="historyDrawerOpen = !historyDrawerOpen" />

            <!-- Toggle 3D panel button (visible when models exist and panel is closed) -->
            <Transition name="toggle-fade">
                <button v-if="hasCadModels && (!sidePanelOpen || sidePanelTab !== '3d')"
                    class="assistant-view__3d-toggle" title="Apri pannello 3D"
                    @click="() => { sidePanelOpen = true; sidePanelTab = '3d' }">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
                        stroke-linecap="round" stroke-linejoin="round">
                        <path d="M12 2L2 7l10 5 10-5-10-5z" />
                        <path d="M2 17l10 5 10-5" />
                        <path d="M2 12l10 5 10-5" />
                    </svg>
                    <span v-if="cadModels.length > 1" class="assistant-view__3d-badge">{{ cadModels.length }}</span>
                </button>
            </Transition>

            <!-- Toggle chart panel button (visible when charts exist and panel is closed or on another tab) -->
            <Transition name="toggle-fade">
                <button v-if="hasCharts && (!sidePanelOpen || sidePanelTab !== 'chart')"
                    class="assistant-view__chart-toggle" title="Mostra grafici"
                    @click="() => { sidePanelOpen = true; sidePanelTab = 'chart' }">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
                        stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="20" x2="18" y2="10" />
                        <line x1="12" y1="20" x2="12" y2="4" />
                        <line x1="6" y1="20" x2="6" y2="14" />
                    </svg>
                    <span v-if="chartPayloads.length > 1" class="assistant-view__chart-badge">{{ chartPayloads.length
                        }}</span>
                </button>
            </Transition>

            <!-- Toggle whiteboard panel button -->
            <Transition name="toggle-fade">
                <button v-if="hasWhiteboards && (!sidePanelOpen || sidePanelTab !== 'whiteboard')"
                    class="assistant-view__wb-toggle" title="Mostra lavagne"
                    @click="() => { sidePanelOpen = true; sidePanelTab = 'whiteboard' }">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
                        stroke-linecap="round" stroke-linejoin="round">
                        <rect x="3" y="3" width="18" height="18" rx="2" />
                        <path d="M3 9h18" />
                        <path d="M9 3v18" />
                    </svg>
                    <span v-if="whiteboardPayloads.length > 1" class="assistant-view__wb-badge">{{
                        whiteboardPayloads.length }}</span>
                </button>
            </Transition>

            <FloatingInputBar ref="floatingBarRef" :disabled="chatStore.isStreamingCurrentConversation"
                :is-connected="chatApi.isConnected.value" :is-streaming="chatStore.isStreamingCurrentConversation"
                :audio-devices="audioDevices" :selected-device-id="selectedDeviceId" :orb-state="orbState"
                @send="handleSend" @stop="() => { stopGeneration(); cancelSpeak() }" @voice-start="startListening"
                @voice-stop="stopListening" @voice-cancel-processing="cancelProcessing"
                @refresh-devices="refreshDevices" @select-device="(id) => { selectedDeviceId = id }" />
        </div>

        <!-- Right Side Panel (3D models or charts) -->
        <Transition name="side-panel-slide">
            <div v-if="sidePanelOpen && (hasCadModels || hasCharts || hasWhiteboards)" class="assistant-view__side-panel"
                :style="{ width: `${sidePanelWidth}px` }">
                <!-- Resize drag handle -->
                <div class="side-panel__resize-handle" @mousedown="onResizeStart">
                    <div class="side-panel__resize-grip">
                        <span /><span /><span />
                    </div>
                </div>
                <!-- Tab switcher (when multiple content types exist) -->
                <div v-if="[hasCadModels, hasCharts, hasWhiteboards].filter(Boolean).length > 1" class="side-panel__tabs">
                    <button v-if="hasCadModels" class="side-panel__tab" :class="{ 'side-panel__tab--active': sidePanelTab === '3d' }"
                        @click="sidePanelTab = '3d'">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M12 2L2 7l10 5 10-5-10-5z" />
                            <path d="M2 17l10 5 10-5" />
                            <path d="M2 12l10 5 10-5" />
                        </svg>
                        <span>3D</span>
                        <span v-if="cadModels.length > 1" class="side-panel__tab-badge">{{ cadModels.length }}</span>
                    </button>
                    <button v-if="hasCharts" class="side-panel__tab" :class="{ 'side-panel__tab--active': sidePanelTab === 'chart' }"
                        @click="sidePanelTab = 'chart'">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                            <line x1="18" y1="20" x2="18" y2="10" />
                            <line x1="12" y1="20" x2="12" y2="4" />
                            <line x1="6" y1="20" x2="6" y2="14" />
                        </svg>
                        <span>Grafici</span>
                        <span v-if="chartPayloads.length > 1" class="side-panel__tab-badge">{{ chartPayloads.length
                            }}</span>
                    </button>
                    <button v-if="hasWhiteboards" class="side-panel__tab" :class="{ 'side-panel__tab--active': sidePanelTab === 'whiteboard' }"
                        @click="sidePanelTab = 'whiteboard'">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="3" y="3" width="18" height="18" rx="2" />
                            <path d="M3 9h18" />
                            <path d="M9 3v18" />
                        </svg>
                        <span>Lavagna</span>
                        <span v-if="whiteboardPayloads.length > 1" class="side-panel__tab-badge">{{ whiteboardPayloads.length }}</span>
                    </button>
                    <button class="side-panel__close" aria-label="Chiudi pannello" @click="closeSidePanel">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    </button>
                </div>

                <!-- CAD viewer (visible when on 3D tab or sole content) -->
                <ImmersiveCADCanvas v-if="hasCadModels && (sidePanelTab === '3d' || (!hasCharts && !hasWhiteboards))" :models="cadModels"
                    :active-index="cadActiveIndex" @update:active-index="(i) => { cadActiveIndex = i }"
                    @close="closeSidePanel" />

                <!-- Chart viewer (visible when on chart tab or sole content) -->
                <div v-if="hasCharts && (sidePanelTab === 'chart' || (!hasCadModels && !hasWhiteboards))"
                    class="side-panel__chart-container">
                    <!-- Close button (only when no tab bar is shown) -->
                    <button v-if="[hasCadModels, hasCharts, hasWhiteboards].filter(Boolean).length <= 1" class="side-panel__chart-close" aria-label="Chiudi pannello"
                        @click="closeSidePanel">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    </button>

                    <!-- Chart navigation (when multiple charts) -->
                    <div v-if="chartPayloads.length > 1" class="side-panel__chart-nav">
                        <button class="side-panel__chart-nav-btn" :disabled="chartActiveIndex <= 0"
                            @click="chartActiveIndex = Math.max(0, chartActiveIndex - 1)">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round">
                                <polyline points="15 18 9 12 15 6" />
                            </svg>
                        </button>
                        <span class="side-panel__chart-counter">{{ chartActiveIndex + 1 }} / {{ chartPayloads.length
                            }}</span>
                        <button class="side-panel__chart-nav-btn"
                            :disabled="chartActiveIndex >= chartPayloads.length - 1"
                            @click="chartActiveIndex = Math.min(chartPayloads.length - 1, chartActiveIndex + 1)">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round">
                                <polyline points="9 18 15 12 9 6" />
                            </svg>
                        </button>
                    </div>

                    <ChartViewer v-if="activeChart" :key="activeChart.chart_id" :payload="activeChart" />
                </div>

                <!-- Whiteboard viewer (visible when on whiteboard tab or sole content) -->
                <div v-if="hasWhiteboards && (sidePanelTab === 'whiteboard' || (!hasCadModels && !hasCharts))"
                    class="side-panel__wb-container">
                    <!-- Close button (only when sole content) -->
                    <button v-if="[hasCadModels, hasCharts, hasWhiteboards].filter(Boolean).length <= 1"
                        class="side-panel__wb-close" aria-label="Chiudi pannello"
                        @click="closeSidePanel">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    </button>

                    <!-- Whiteboard navigation (when multiple boards) -->
                    <div v-if="whiteboardPayloads.length > 1" class="side-panel__wb-nav">
                        <button class="side-panel__chart-nav-btn" :disabled="whiteboardActiveIndex <= 0"
                            @click="whiteboardActiveIndex = Math.max(0, whiteboardActiveIndex - 1)">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round">
                                <polyline points="15 18 9 12 15 6" />
                            </svg>
                        </button>
                        <span class="side-panel__chart-counter">{{ whiteboardActiveIndex + 1 }} / {{ whiteboardPayloads.length }}</span>
                        <button class="side-panel__chart-nav-btn"
                            :disabled="whiteboardActiveIndex >= whiteboardPayloads.length - 1"
                            @click="whiteboardActiveIndex = Math.min(whiteboardPayloads.length - 1, whiteboardActiveIndex + 1)">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2" stroke-linecap="round">
                                <polyline points="9 18 15 12 9 6" />
                            </svg>
                        </button>
                    </div>

                    <TldrawCanvas v-if="activeWhiteboard"
                        :key="activeWhiteboard.board_id"
                        :board-id="activeWhiteboard.board_id"
                        @change="(snap) => saveWhiteboardSnapshot(activeWhiteboard?.board_id ?? '', snap)" />
                </div>
            </div>
        </Transition>

        <!-- Conversation history drawer -->
        <ConversationDrawer :open="historyDrawerOpen" :messages="chatStore.messages"
            :is-streaming="chatStore.isStreamingCurrentConversation"
            :branch-disabled="chatStore.isStreamingCurrentConversation" :get-version-count="chatStore.getVersionCount"
            :get-active-version-index="chatStore.getActiveVersionIndex" @close="historyDrawerOpen = false"
            @edit="startEdit" @switch-version="handleVersionSwitch" @branch="handleBranch" />

        <MessageEditDialog v-if="editingMessageId" :original-content="editingContent" @submit="submitEdit"
            @cancel="cancelEdit" />

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
    flex-direction: row;
    background: var(--surface-0);
    overflow: hidden;
}

/* Main area: takes remaining space, centers the orb column */
.assistant-view__main {
    position: relative;
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    overflow: hidden;
}

.assistant-view__center {
    position: relative;
    z-index: var(--z-raised);
    display: flex;
    flex-direction: column;
    align-items: center;
    flex: 1;
    min-height: 0;
    width: 100%;
    max-width: 680px;
    padding: var(--space-8) var(--space-4) 100px;
    gap: var(--space-4);
}

/* ── 3D / Chart Side Panel ── */
.assistant-view__side-panel {
    position: relative;
    width: var(--panel-width, 400px);
    flex-shrink: 0;
    height: calc(100% - 24px);
    margin: 12px 12px 12px 0;
    z-index: var(--z-raised);
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur-heavy));
    -webkit-backdrop-filter: blur(var(--glass-blur-heavy));
    border: 1px solid var(--glass-border);
    border-radius: 16px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25), 0 0 1px rgba(255, 255, 255, 0.05);
}

/* Prevent text selection while dragging the panel edge */
.assistant-view--dragging,
.assistant-view--dragging * {
    user-select: none !important;
    cursor: col-resize !important;
}

/* ── Resize handle ── */
.side-panel__resize-handle {
    position: absolute;
    top: 8px;
    left: -10px;
    width: 20px;
    height: calc(100% - 16px);
    z-index: 10;
    cursor: col-resize;
    display: flex;
    align-items: center;
    justify-content: center;
}

/* Hover highlight strip */
.side-panel__resize-handle::before {
    content: '';
    position: absolute;
    top: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 2px;
    height: 100%;
    background: var(--accent);
    opacity: 0;
    border-radius: 1px;
    transition: opacity 200ms var(--ease-smooth);
}

.side-panel__resize-handle:hover::before,
.assistant-view--dragging .side-panel__resize-handle::before {
    opacity: 0.5;
}

/* Grip knob (3 small lines stacked vertically) */
.side-panel__resize-grip {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    padding: 6px 0;
    border-radius: var(--radius-pill);
    background: var(--surface-3);
    border: 1px solid var(--border);
    width: 14px;
    opacity: 0.6;
    transition:
        opacity 200ms var(--ease-smooth),
        transform 200ms var(--ease-out-expo),
        background 200ms var(--ease-smooth),
        border-color 200ms var(--ease-smooth);
    pointer-events: none;
}

.side-panel__resize-handle:hover .side-panel__resize-grip,
.assistant-view--dragging .side-panel__resize-grip {
    opacity: 1;
}

.assistant-view--dragging .side-panel__resize-grip {
    background: var(--surface-4);
    border-color: var(--accent);
}

.side-panel__resize-grip span {
    display: block;
    width: 4px;
    height: 1.5px;
    border-radius: 1px;
    background: var(--text-muted);
    transition: background 200ms var(--ease-smooth);
}

.side-panel__resize-handle:hover .side-panel__resize-grip span,
.assistant-view--dragging .side-panel__resize-grip span {
    background: var(--accent);
}

/* ── Toggle 3D panel button ── */
.assistant-view__3d-toggle {
    position: absolute;
    right: 16px;
    top: 50%;
    transform: translateY(-50%);
    z-index: var(--z-sticky);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface-2);
    color: var(--text-secondary);
    cursor: pointer;
    transition:
        background 200ms var(--ease-smooth),
        border-color 200ms var(--ease-smooth),
        color 200ms var(--ease-smooth),
        transform 200ms var(--ease-smooth);
}

.assistant-view__3d-toggle:hover {
    background: var(--surface-3);
    border-color: var(--border-hover);
    color: var(--accent);
    transform: translateY(-50%) scale(1.08);
}

.assistant-view__3d-toggle:active {
    transform: translateY(-50%) scale(0.95);
}

.assistant-view__3d-badge {
    position: absolute;
    top: -4px;
    right: -4px;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    border-radius: var(--radius-pill);
    background: var(--accent);
    color: var(--surface-0);
    font-size: 10px;
    font-weight: 600;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
}

/* ── Chart toggle button ── */
.assistant-view__chart-toggle {
    position: absolute;
    right: 16px;
    top: calc(50% + 48px);
    transform: translateY(-50%);
    z-index: var(--z-sticky);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface-2);
    color: var(--text-secondary);
    cursor: pointer;
    transition:
        background 200ms var(--ease-smooth),
        border-color 200ms var(--ease-smooth),
        color 200ms var(--ease-smooth),
        transform 200ms var(--ease-smooth);
}

.assistant-view__chart-toggle:hover {
    background: var(--surface-3);
    border-color: var(--border-hover);
    color: var(--accent);
    transform: translateY(-50%) scale(1.08);
}

.assistant-view__chart-toggle:active {
    transform: translateY(-50%) scale(0.95);
}

.assistant-view__chart-badge {
    position: absolute;
    top: -4px;
    right: -4px;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    border-radius: var(--radius-pill);
    background: var(--accent);
    color: var(--surface-0);
    font-size: 10px;
    font-weight: 600;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
}

/* ── Whiteboard toggle button ── */
.assistant-view__wb-toggle {
    position: absolute;
    right: 16px;
    top: calc(50% + 96px);
    transform: translateY(-50%);
    z-index: var(--z-sticky);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface-2);
    color: var(--text-secondary);
    cursor: pointer;
    transition:
        background 200ms var(--ease-smooth),
        border-color 200ms var(--ease-smooth),
        color 200ms var(--ease-smooth),
        transform 200ms var(--ease-smooth);
}

.assistant-view__wb-toggle:hover {
    background: var(--surface-3);
    border-color: var(--border-hover);
    color: var(--accent);
    transform: translateY(-50%) scale(1.08);
}

.assistant-view__wb-toggle:active {
    transform: translateY(-50%) scale(0.95);
}

.assistant-view__wb-badge {
    position: absolute;
    top: -4px;
    right: -4px;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    border-radius: var(--radius-pill);
    background: var(--accent);
    color: var(--surface-0);
    font-size: 10px;
    font-weight: 600;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
}

/* ── Side panel tabs ── */
.side-panel__tabs {
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--glass-border);
    background: transparent;
    border-radius: 16px 16px 0 0;
}

.side-panel__tab {
    display: flex;
    align-items: center;
    gap: 5px;
    padding: 5px 10px;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    transition: background 150ms, color 150ms;
}

.side-panel__tab:hover {
    background: var(--surface-3);
    color: var(--text-primary);
}

.side-panel__tab--active {
    background: var(--surface-3);
    color: var(--accent);
}

.side-panel__tab-badge {
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    border-radius: var(--radius-pill);
    background: var(--accent);
    color: var(--surface-0);
    font-size: 10px;
    font-weight: 600;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
}

.side-panel__close {
    margin-left: auto;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 150ms, color 150ms;
}

.side-panel__close:hover {
    background: var(--danger);
    color: white;
}

/* ── Side panel chart container ── */
.side-panel__chart-container {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    position: relative;
}

/* Match panel corners when ChartViewer is inside the side panel */
.side-panel__chart-container :deep(.chart-viewer) {
    margin: 0;
    border-radius: 0 0 16px 16px;
}

.side-panel__chart-close {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: none;
    border-radius: var(--radius-sm);
    background: var(--surface-3);
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 150ms, color 150ms;
}

.side-panel__chart-close:hover {
    background: var(--danger);
    color: white;
}

.side-panel__chart-nav {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--glass-border);
    background: transparent;
}

.side-panel__chart-nav-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 150ms, color 150ms, border-color 150ms;
}

.side-panel__chart-nav-btn:hover:not(:disabled) {
    background: var(--surface-3);
    border-color: var(--border-hover);
    color: var(--accent);
}

.side-panel__chart-nav-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
}

.side-panel__chart-counter {
    font-size: 0.75rem;
    color: var(--text-secondary);
    font-variant-numeric: tabular-nums;
}

/* ── Side panel whiteboard container ── */
.side-panel__wb-container {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow: hidden;
    position: relative;
}

.side-panel__wb-close {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: none;
    border-radius: var(--radius-sm);
    background: var(--surface-3);
    color: var(--text-secondary);
    cursor: pointer;
    transition: background 150ms, color 150ms;
}

.side-panel__wb-close:hover {
    background: var(--danger);
    color: white;
}

.side-panel__wb-nav {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--glass-border);
    background: transparent;
}

/* ── Side panel slide transition ── */
.side-panel-slide-enter-active {
    transition:
        transform 350ms var(--ease-out-expo),
        opacity 350ms var(--ease-smooth);
}

.side-panel-slide-leave-active {
    transition:
        transform 250ms var(--ease-smooth),
        opacity 200ms ease;
}

.side-panel-slide-enter-from,
.side-panel-slide-leave-to {
    transform: translateX(20px);
    opacity: 0;
}

/* ── Toggle button fade transition ── */
.toggle-fade-enter-active {
    transition: opacity 300ms var(--ease-smooth), transform 300ms var(--ease-out-expo);
}

.toggle-fade-leave-active {
    transition: opacity 150ms ease, transform 150ms ease;
}

.toggle-fade-enter-from {
    opacity: 0;
    transform: translateY(-50%) translateX(8px) scale(0.9);
}

.toggle-fade-leave-to {
    opacity: 0;
    transform: translateY(-50%) translateX(8px) scale(0.9);
}

/* Orb wrapper: no overflow clipping so effects render fully */
.assistant-view__orb-wrapper {
    position: relative;
    flex-shrink: 0;
}

/* Stop / interrupt pill below the orb — glass */
.assistant-view__stop-hint {
    position: absolute;
    bottom: -40px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 16px;
    border: 1px solid rgba(196, 92, 92, 0.25);
    border-radius: 20px;
    background: var(--glass-bg-light);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    color: var(--danger);
    font-size: var(--text-2xs);
    font-weight: 500;
    letter-spacing: 0.03em;
    white-space: nowrap;
    cursor: pointer;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2), 0 0 10px rgba(196, 92, 92, 0.08);
    transition:
        background 200ms var(--ease-smooth),
        border-color 200ms var(--ease-smooth),
        box-shadow 200ms var(--ease-smooth),
        transform 200ms var(--ease-out-back);
    z-index: var(--z-sticky);
}

.assistant-view__stop-hint:hover {
    background: rgba(196, 92, 92, 0.12);
    border-color: rgba(196, 92, 92, 0.4);
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25), 0 0 16px rgba(196, 92, 92, 0.15);
    transform: translateX(-50%) scale(1.04);
}

.assistant-view__stop-hint:active {
    transform: translateX(-50%) scale(0.96);
}

/* Stop hint transitions */
.stop-hint-fade-enter-active {
    transition:
        opacity 300ms var(--ease-smooth),
        transform 300ms var(--ease-out-expo);
}

.stop-hint-fade-leave-active {
    transition: opacity 150ms ease, transform 150ms ease;
}

.stop-hint-fade-enter-from {
    opacity: 0;
    transform: translateX(-50%) translateY(-8px) scale(0.9);
}

.stop-hint-fade-leave-to {
    opacity: 0;
    transform: translateX(-50%) translateY(-6px) scale(0.95);
}

/*
 * Content area: fills remaining space below the orb.
 * Uses calc-based max-height as a fallback, but flex + min-height: 0
 * on the parent already constrains it naturally.
 */
.assistant-view__content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-4);
    flex: 1;
    min-height: 0;
    width: 100%;
    overflow-y: auto;
    overflow-x: hidden;
    scrollbar-width: thin;
    scrollbar-color: var(--border) transparent;
    /* Mask fade at top and bottom edges for long content */
    mask-image: linear-gradient(to bottom,
            transparent 0%,
            black 12px,
            black calc(100% - 16px),
            transparent 100%);
    -webkit-mask-image: linear-gradient(to bottom,
            transparent 0%,
            black 12px,
            black calc(100% - 16px),
            transparent 100%);
    padding: var(--space-2) 0 var(--space-4);
}

/* ── Greeting (idle, empty conversation) ── */
.assistant-view__greeting {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-4) 0;
}

.assistant-view__greeting-text {
    font-size: var(--text-xl);
    font-weight: 300;
    color: var(--text-primary);
    letter-spacing: 0.02em;
    opacity: 0.85;
    margin: 0;
}

.assistant-view__greeting-hint {
    font-size: var(--text-xs);
    color: var(--text-muted);
    margin: 0;
    letter-spacing: 0.03em;
}

/* Greeting transitions */
.greeting-fade-enter-active {
    transition:
        opacity 600ms var(--ease-smooth),
        transform 600ms var(--ease-out-expo);
}

.greeting-fade-leave-active {
    transition:
        opacity 300ms ease,
        transform 300ms ease;
}

.greeting-fade-enter-from {
    opacity: 0;
    transform: translateY(12px);
}

.greeting-fade-leave-to {
    opacity: 0;
    transform: translateY(-8px) scale(0.97);
}

.assistant-view__content::-webkit-scrollbar {
    width: 3px;
}

.assistant-view__content::-webkit-scrollbar-track {
    background: transparent;
}

.assistant-view__content::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: var(--radius-pill);
}

.assistant-view__content:hover::-webkit-scrollbar-thumb {
    background: var(--border-hover);
}

/* ── Response transition ── */
.response-fade-enter-active {
    transition:
        opacity 400ms var(--ease-smooth),
        transform 400ms var(--ease-out-expo),
        filter 400ms var(--ease-smooth);
}

.response-fade-leave-active {
    transition:
        opacity 250ms ease,
        transform 250ms ease,
        filter 250ms ease;
}

.response-fade-enter-from {
    opacity: 0;
    transform: translateY(16px) scale(0.97);
    filter: blur(4px);
}

.response-fade-leave-to {
    opacity: 0;
    transform: translateY(-8px) scale(0.98);
    filter: blur(2px);
}

/* ── Transcript transition ── */
.transcript-fade-enter-active {
    transition:
        opacity 350ms var(--ease-smooth),
        transform 350ms var(--ease-out-expo),
        filter 350ms var(--ease-smooth);
}

.transcript-fade-leave-active {
    transition:
        opacity 200ms ease,
        transform 200ms ease,
        filter 200ms ease;
}

.transcript-fade-enter-from {
    opacity: 0;
    transform: scale(0.9) translateY(8px);
    filter: blur(4px);
}

.transcript-fade-leave-to {
    opacity: 0;
    transform: scale(0.95);
    filter: blur(2px);
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
