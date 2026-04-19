<script setup lang="ts">
/**
 * HybridView.vue — Dual-pane AI workspace.
 *
 * A split-screen layout that genuinely differs from AssistantView:
 * - Left pane  (~300 px, resizable): compact conversation thread + input.
 * - Right pane (flex fill): AI workspace — thinking chain surfaced by
 *   default, full response rendered in a large text-first reading area.
 *
 * AssistantView is orb-centric / voice-first.
 * HybridView is workspace-centric / text-first.
 */
import { computed, defineAsyncComponent, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AmbientBackground from '../components/assistant/AmbientBackground.vue'
import ChatInput from '../components/chat/ChatInput.vue'
import MessageBubble from '../components/chat/MessageBubble.vue'
import MessageEditDialog from '../components/chat/MessageEditDialog.vue'
import StreamingIndicator from '../components/chat/StreamingIndicator.vue'
import ToolConfirmationDialog from '../components/chat/ToolConfirmationDialog.vue'
import TranscriptOverlay from '../components/voice/TranscriptOverlay.vue'
import AliceSpinner from '../components/ui/AliceSpinner.vue'
import AppIcon from '../components/ui/AppIcon.vue'
import CADGenerationPlaceholder from '../components/chat/CADGenerationPlaceholder.vue'
import { ChatApiKey } from '../composables/useChat'
import { useVoice } from '../composables/useVoice'
import { useGenerationState } from '../composables/useGenerationState'
import { useArtifactsStore } from '../stores/artifacts'
import { useChatStore } from '../stores/chat'
import { useVoiceStore } from '../stores/voice'
import type { CadModelPayload, ChartPayload, WhiteboardPayload } from '../types/chat'
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
const chatApi = inject(ChatApiKey, null)
const _router = useRouter()
const _route = useRoute()
if (!chatApi) {
    console.error('[HybridView] ChatApiKey injection failed — redirecting to home')
    _router.replace({ name: 'home' })
}
const voiceStore = useVoiceStore()
const artifactsStore = useArtifactsStore()
const { cadGenerationInProgress } = useGenerationState()
const _noop = (): void => { }
const _asyncNoop = async (): Promise<void> => { }
const send = chatApi?.sendMessage ?? _asyncNoop
const isConnected = chatApi?.isConnected ?? ref(false)
const stopGeneration = chatApi?.stopGeneration ?? _noop
const editMessage = chatApi?.editMessage ?? _asyncNoop
const respondToConfirmation = chatApi?.respondToConfirmation ?? _noop
const {
    startListening, stopListening, cancelProcessing, connect: connectVoice,
    transcript, audioDevices, selectedDeviceId, refreshDevices, speak, cancelSpeak,
} = useVoice()

const chatInputRef = ref<InstanceType<typeof ChatInput> | null>(null)
const messagesContainer = ref<HTMLElement | null>(null)
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

const orbState = computed<'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'>(() => {
    if (voiceStore.isSpeaking) return 'speaking'
    if (voiceStore.isListening) return 'listening'
    if (voiceStore.isProcessing) return 'processing'
    if (chatStore.isStreamingCurrentConversation) return 'thinking'
    return 'idle'
})

const pendingConfirmationsList = computed(() => Object.values(chatStore.pendingConfirmations))

// ── Resizable left pane ────────────────────────────────────────────────────
const PANE_MIN = 220
const PANE_MAX = 900
const PANE_DEFAULT = 840
const leftPaneWidth = ref(PANE_DEFAULT)
const isDraggingDivider = ref(false)

function onResizeStart(e: MouseEvent): void {
    e.preventDefault()
    isDraggingDivider.value = true
    const startX = e.clientX
    const startW = leftPaneWidth.value

    function onMove(ev: MouseEvent): void {
        leftPaneWidth.value = Math.min(PANE_MAX, Math.max(PANE_MIN, startW + ev.clientX - startX))
    }

    function onUp(): void {
        isDraggingDivider.value = false
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
}

// ── Workspace tabs: 3D / chart / whiteboard ─────────────────────────────────
type WorkspaceTab = '3d' | 'chart' | 'whiteboard'
const workspaceTab = ref<WorkspaceTab>('3d')

/** Switch away from the current workspace tab to the next available one. */
function dismissWorkspaceTab(): void {
    const current = workspaceTab.value
    if (current === '3d') {
        if (hasCharts.value) { workspaceTab.value = 'chart'; return }
        if (hasWhiteboards.value) { workspaceTab.value = 'whiteboard'; return }
    } else if (current === 'chart') {
        if (hasCadModels.value) { workspaceTab.value = '3d'; return }
        if (hasWhiteboards.value) { workspaceTab.value = 'whiteboard'; return }
    } else {
        if (hasCadModels.value) { workspaceTab.value = '3d'; return }
        if (hasCharts.value) { workspaceTab.value = 'chart'; return }
    }
}

// ── Output payload extraction (ported from AssistantView) ──────────────────
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

const whiteboardPayloads = computed((): WhiteboardPayload[] => {
    const boardMap = new Map<string, WhiteboardPayload>()
    for (const msg of chatStore.messages) {
        if (msg.role !== 'tool') continue
        try {
            const p = JSON.parse(msg.content)
            if (isWhiteboardPayload(p)) boardMap.set(p.board_id, p)
        } catch { /* not JSON */ }
    }
    return Array.from(boardMap.values())
})

const hasCadModels = computed(() => cadModels.value.length > 0)
const hasCharts = computed(() => chartPayloads.value.length > 0)
const hasWhiteboards = computed(() => whiteboardPayloads.value.length > 0)
const hasAnyOutput = computed(() => hasCadModels.value || hasCharts.value || hasWhiteboards.value)

const cadActiveIndex = ref(0)
const chartActiveIndex = ref(0)
const whiteboardActiveIndex = ref(0)

const activeChart = computed((): ChartPayload | null =>
    chartPayloads.value[chartActiveIndex.value] ?? null
)
const activeWhiteboard = computed((): WhiteboardPayload | null =>
    whiteboardPayloads.value[whiteboardActiveIndex.value] ?? null
)

/** Auto-switch to the tab when new output content appears. */
watch(() => cadModels.value.length, (newLen, oldLen) => {
    if (newLen > oldLen) {
        workspaceTab.value = '3d'
        cadActiveIndex.value = newLen - 1
    }
})
watch(() => chartPayloads.value.length, (newLen, oldLen) => {
    if (newLen > oldLen) {
        workspaceTab.value = 'chart'
        chartActiveIndex.value = newLen - 1
    }
})
watch(() => whiteboardPayloads.value.length, (newLen, oldLen) => {
    if (newLen > oldLen) {
        workspaceTab.value = 'whiteboard'
        whiteboardActiveIndex.value = newLen - 1
    }
})

/** Clamp indices on conversation change. */
watch(cadModels, (m) => { if (cadActiveIndex.value >= m.length) cadActiveIndex.value = Math.max(0, m.length - 1) })
watch(chartPayloads, (c) => { if (chartActiveIndex.value >= c.length) chartActiveIndex.value = Math.max(0, c.length - 1) })
watch(whiteboardPayloads, (w) => { if (whiteboardActiveIndex.value >= w.length) whiteboardActiveIndex.value = Math.max(0, w.length - 1) })

/* Auto-focus the 3D tab the moment a CAD generation starts so the user
   sees the placeholder + final model in the workspace. */
watch(cadGenerationInProgress, (info) => {
    if (info) workspaceTab.value = '3d'
})

/* Keep the artifacts store warm for the active conversation so pin state
   on existing CAD viewers reflects the persisted value. */
watch(
    () => chatStore.currentConversation?.id ?? null,
    (id) => {
        if (id) artifactsStore.ensureForConversation(id).catch(() => { /* best-effort */ })
    },
    { immediate: true },
)

function saveWhiteboardSnapshot(boardId: string, snapshot: Record<string, unknown>): void {
    api.saveWhiteboardSnapshot(boardId, snapshot).catch(() => { /* best-effort */ })
}

// ── Scroll helpers ─────────────────────────────────────────────────────────
function scrollConversation(): void {
    nextTick(() => {
        if (messagesContainer.value)
            messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    })
}

watch(() => [chatStore.messages.length, chatStore.currentStreamContent], () => {
    scrollConversation()
})

function handleTranscriptSend(text: string): void {
    voiceStore.clearTranscript()
    const files = voiceStore.sttIncludeAttachments
        ? [...(chatInputRef.value?.pendingFiles ?? [])]
        : undefined
    send(text, undefined, files).then(() => {
        if (files?.length) chatInputRef.value?.clearPendingFiles()
    }).catch(console.error)
}

function handleTranscriptDismiss(): void {
    voiceStore.clearTranscript()
}

async function handleSend(content: string, attachments: File[]): Promise<void> {
    await send(content, undefined, attachments)
}

watch(() => voiceStore.transcript, (text) => {
    if (!text.trim() || voiceStore.confirmTranscript) return
    const toSend = text.trim()
    voiceStore.clearTranscript()
    const files = voiceStore.sttIncludeAttachments
        ? [...(chatInputRef.value?.pendingFiles ?? [])]
        : undefined
    send(toSend, undefined, files).then(() => {
        if (files?.length) chatInputRef.value?.clearPendingFiles()
    }).catch(console.error)
})

watch(() => voiceStore.confirmTranscript, (confirm) => {
    if (!confirm && voiceStore.transcript.trim()) {
        const t = voiceStore.transcript.trim()
        voiceStore.clearTranscript()
        const files = voiceStore.sttIncludeAttachments
            ? [...(chatInputRef.value?.pendingFiles ?? [])]
            : undefined
        send(t, undefined, files).then(() => {
            if (files?.length) chatInputRef.value?.clearPendingFiles()
        }).catch(console.error)
    }
})

// TTS auto-speak on response complete
let wasStreamingHere = false
watch(() => chatStore.isStreamingCurrentConversation, (streaming) => {
    if (streaming) {
        wasStreamingHere = true
    } else if (wasStreamingHere) {
        wasStreamingHere = false
        if (!voiceStore.autoTtsResponse || !voiceStore.ttsAvailable || !voiceStore.connected) return
        const msgs = chatStore.messages
        const lastUserIdx = msgs.findLastIndex(m => m.role === 'user')
        const allContent = msgs
            .slice(lastUserIdx + 1)
            .filter(m => m.role === 'assistant' && m.content?.trim())
            .map(m => m.content!.trim())
            .join('\n')
        if (allContent) speak(allContent)
    }
})

/**
 * If navigated with ``?conv=<uuid>`` (e.g. "open in conversation" from
 * the artifact board), switch the chat store to that conversation.
 * Falls back to creating a fresh one only when no query is given and
 * no conversation is currently selected.
 */
async function applyRouteConversation(): Promise<void> {
    const raw = _route.query.conv
    const requested = Array.isArray(raw) ? raw[0] : raw
    if (typeof requested === 'string' && requested.length > 0) {
        if (chatStore.currentConversation?.id === requested) return
        try {
            if (!chatStore.conversations.length) {
                await chatStore.loadConversations()
            }
            await chatStore.loadConversation(requested)
        } catch (err) {
            console.error('[HybridView] Failed to load conversation', requested, err)
        }
        return
    }
    if (!chatStore.currentConversation) {
        await chatStore.createConversation().catch(console.error)
    }
}

watch(
    () => _route.query.conv,
    () => { applyRouteConversation().catch(console.error) },
)

onMounted(() => {
    connectVoice()
    applyRouteConversation().catch(console.error)
})

onBeforeUnmount(() => {
    isDraggingDivider.value = false
})
</script>

<template>
    <div class="hybrid-view" aria-label="Ibrido" :class="{ 'hybrid-view--dragging': isDraggingDivider }">
        <AmbientBackground :state="orbState" :audio-level="voiceStore.audioLevel" :subtle="true" />

        <!-- ── Left: compact conversation pane ── -->
        <aside class="hybrid-view__left" :style="{ width: leftPaneWidth + 'px' }">
            <div class="hybrid-view__pane-header">
                <span class="hybrid-view__pane-title">Conversazione</span>
                <span class="hybrid-view__state-pill" :class="`state-pill--${orbState}`">
                    <AliceSpinner v-if="orbState !== 'idle'" size="xs" />
                    <span>{{ orbState === 'idle' ? 'Pronto' : orbState === 'thinking' ? 'Elabora…' : orbState ===
                        'listening' ? 'Ascolto' : orbState === 'speaking' ? 'Parla' : 'Processa' }}</span>
                </span>
            </div>

            <div ref="messagesContainer" class="hybrid-view__messages">
                <div v-if="!chatStore.messages.length && !chatStore.isStreamingCurrentConversation"
                    class="hybrid-view__conv-empty">
                    <AppIcon name="message" :size="22" />
                    <span>Inizia a scrivere</span>
                </div>

                <MessageBubble v-for="msg in chatStore.messages" :key="msg.id" :message="msg"
                    :version-count="msg.version_group_id ? chatStore.getVersionCount(msg.version_group_id) : 1"
                    :active-version-index="msg.version_group_id ? chatStore.getActiveVersionIndex(msg.version_group_id) : 0"
                    :edit-disabled="chatStore.isStreamingCurrentConversation"
                    :branch-disabled="chatStore.isStreamingCurrentConversation" @edit="startEdit"
                    @switch-version="handleVersionSwitch" @branch="handleBranch" />

                <div v-if="chatStore.isStreamingCurrentConversation" class="hybrid-view__conv-streaming">
                    <StreamingIndicator :content="chatStore.currentStreamContent"
                        :thinking-content="chatStore.currentThinkingContent" />
                </div>
            </div>

            <div class="hybrid-view__input-zone">
                <TranscriptOverlay :text="transcript" :is-processing="voiceStore.isProcessing"
                    :is-recording="voiceStore.isListening" :audio-level="voiceStore.audioLevel"
                    :duration="voiceStore.formattedDuration" :auto-send="!voiceStore.confirmTranscript"
                    @send="handleTranscriptSend" @dismiss="handleTranscriptDismiss" />
                <ChatInput ref="chatInputRef" :disabled="chatStore.isStreamingCurrentConversation"
                    :is-connected="isConnected" :is-streaming="chatStore.isStreamingCurrentConversation"
                    :audio-devices="audioDevices" :selected-device-id="selectedDeviceId" @send="handleSend"
                    @stop="() => { wasStreamingHere = false; stopGeneration(); cancelSpeak() }"
                    @voice-start="startListening" @voice-stop="stopListening"
                    @voice-cancel-processing="cancelProcessing" @refresh-devices="refreshDevices"
                    @select-device="(id) => { selectedDeviceId = id }" />
            </div>
        </aside>

        <!-- ── Resizable divider ── -->
        <div class="hybrid-view__divider" :class="{ 'hybrid-view__divider--active': isDraggingDivider }"
            @mousedown="onResizeStart" />

        <!-- ── Right: AI workspace ── -->
        <main class="hybrid-view__workspace">
            <div class="hybrid-view__workspace-header">
                <div class="workspace-header__left">
                    <span class="workspace-header__label">Workspace</span>
                </div>

                <!-- Workspace tab bar (artifacts only) -->
                <div v-if="hasAnyOutput" class="workspace-tabs">
                    <button v-if="hasCadModels" class="workspace-tab"
                        :class="{ 'workspace-tab--active': workspaceTab === '3d' }" @click="workspaceTab = '3d'">
                        <AppIcon name="box-3d" :size="13" />
                        <span>3D</span>
                        <span v-if="cadModels.length > 1" class="workspace-tab__badge">{{ cadModels.length }}</span>
                    </button>
                    <button v-if="hasCharts" class="workspace-tab"
                        :class="{ 'workspace-tab--active': workspaceTab === 'chart' }" @click="workspaceTab = 'chart'">
                        <AppIcon name="bar-chart" :size="13" />
                        <span>Grafici</span>
                        <span v-if="chartPayloads.length > 1" class="workspace-tab__badge">{{ chartPayloads.length
                        }}</span>
                    </button>
                    <button v-if="hasWhiteboards" class="workspace-tab"
                        :class="{ 'workspace-tab--active': workspaceTab === 'whiteboard' }"
                        @click="workspaceTab = 'whiteboard'">
                        <AppIcon name="whiteboard-card" :size="13" />
                        <span>Lavagna</span>
                        <span v-if="whiteboardPayloads.length > 1" class="workspace-tab__badge">{{
                            whiteboardPayloads.length }}</span>
                    </button>
                </div>

                <button v-if="chatStore.isStreamingCurrentConversation" class="workspace-header__stop"
                    @click="() => { wasStreamingHere = false; stopGeneration(); cancelSpeak() }">
                    <AppIcon name="stop" :size="12" />
                    Interrompi
                </button>
            </div>

            <!-- ── Empty state (no artifacts yet) ── -->
            <div v-if="!hasAnyOutput" class="hybrid-view__workspace-body">
                <!-- CAD generation in progress with no prior model -->
                <div v-if="cadGenerationInProgress" class="workspace-viewer workspace-viewer--placeholder">
                    <CADGenerationPlaceholder :generation="cadGenerationInProgress" />
                </div>
                <div v-else class="workspace-empty">
                    <div class="workspace-empty__orb">
                        <AppIcon name="orb" :size="40" />
                    </div>
                    <p class="workspace-empty__title">Workspace</p>
                    <p class="workspace-empty__sub">Gli artefatti generati da AL\CE appariranno qui:<br>modelli 3D,
                        grafici, lavagne e altro</p>
                </div>
            </div>

            <!-- ── 3D CAD tab ── -->
            <div v-else-if="workspaceTab === '3d' && hasCadModels" class="workspace-viewer">
                <ImmersiveCADCanvas :models="cadModels" :active-index="cadActiveIndex"
                    @update:active-index="(i) => { cadActiveIndex = i }" @close="dismissWorkspaceTab" />
                <CADGenerationPlaceholder v-if="cadGenerationInProgress" :generation="cadGenerationInProgress" />
            </div>

            <!-- ── Chart tab ── -->
            <div v-else-if="workspaceTab === 'chart' && hasCharts" class="workspace-viewer workspace-viewer--chart">
                <div v-if="chartPayloads.length > 1" class="workspace-viewer__nav">
                    <button class="workspace-viewer__nav-btn" :disabled="chartActiveIndex <= 0"
                        @click="chartActiveIndex = Math.max(0, chartActiveIndex - 1)">
                        <AppIcon name="chevron-left" :size="14" />
                    </button>
                    <span class="workspace-viewer__counter">{{ chartActiveIndex + 1 }} / {{ chartPayloads.length
                    }}</span>
                    <button class="workspace-viewer__nav-btn" :disabled="chartActiveIndex >= chartPayloads.length - 1"
                        @click="chartActiveIndex = Math.min(chartPayloads.length - 1, chartActiveIndex + 1)">
                        <AppIcon name="chevron-right" :size="14" />
                    </button>
                </div>
                <ChartViewer v-if="activeChart" :key="activeChart.chart_id" :payload="activeChart" />
            </div>

            <!-- ── Whiteboard tab ── -->
            <div v-else-if="workspaceTab === 'whiteboard' && hasWhiteboards"
                class="workspace-viewer workspace-viewer--wb">
                <div v-if="whiteboardPayloads.length > 1" class="workspace-viewer__nav">
                    <button class="workspace-viewer__nav-btn" :disabled="whiteboardActiveIndex <= 0"
                        @click="whiteboardActiveIndex = Math.max(0, whiteboardActiveIndex - 1)">
                        <AppIcon name="chevron-left" :size="14" />
                    </button>
                    <span class="workspace-viewer__counter">{{ whiteboardActiveIndex + 1 }} / {{
                        whiteboardPayloads.length }}</span>
                    <button class="workspace-viewer__nav-btn"
                        :disabled="whiteboardActiveIndex >= whiteboardPayloads.length - 1"
                        @click="whiteboardActiveIndex = Math.min(whiteboardPayloads.length - 1, whiteboardActiveIndex + 1)">
                        <AppIcon name="chevron-right" :size="14" />
                    </button>
                </div>
                <TldrawCanvas v-if="activeWhiteboard" :key="activeWhiteboard.board_id"
                    :board-id="activeWhiteboard.board_id"
                    @change="(snap) => saveWhiteboardSnapshot(activeWhiteboard?.board_id ?? '', snap)" />
            </div>
        </main>

        <ToolConfirmationDialog v-if="pendingConfirmationsList.length > 0"
            :key="pendingConfirmationsList[0].executionId" :confirmation="pendingConfirmationsList[0]"
            @respond="respondToConfirmation" />

        <MessageEditDialog v-if="editingMessageId" :original-content="editingContent" @submit="submitEdit"
            @cancel="cancelEdit" />
    </div>
</template>

<style scoped>
/* ── HybridView — Dual-pane workspace layout ── */

.hybrid-view {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: row;
    overflow: hidden;
    background: var(--surface-0);
}

.hybrid-view--dragging {
    cursor: col-resize;
    user-select: none;
}

/* ── Left pane ─────────────────────────────────────────────── */

.hybrid-view__left {
    position: relative;
    z-index: var(--z-raised);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    height: 100%;
    border-right: 1px solid var(--border);
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    min-width: 220px;
    max-width: 900px;
}

.hybrid-view__pane-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px 8px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    gap: var(--space-2);
}

.hybrid-view__pane-title {
    font-size: var(--text-2xs);
    font-weight: var(--weight-semibold);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
}

.hybrid-view__state-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 8px;
    border-radius: var(--radius-sm);
    font-size: var(--text-2xs);
    font-weight: var(--weight-medium);
    color: var(--text-muted);
    background: var(--surface-2);
    border: 1px solid var(--border);
    transition:
        color var(--transition-fast),
        background var(--transition-fast),
        border-color var(--transition-fast);
}

.state-pill--thinking,
.state-pill--processing {
    color: var(--accent);
    border-color: var(--accent-border);
    background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.state-pill--listening {
    color: var(--listening);
    border-color: var(--listening);
    background: color-mix(in srgb, var(--listening) 8%, transparent);
}

.state-pill--speaking {
    color: var(--speaking);
    border-color: var(--speaking);
    background: color-mix(in srgb, var(--speaking) 8%, transparent);
}

/* Messages */
.hybrid-view__messages {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-2) var(--space-2);
    scroll-behavior: smooth;
}

.hybrid-view__messages::-webkit-scrollbar {
    width: 3px;
}

.hybrid-view__messages::-webkit-scrollbar-track {
    background: transparent;
}

.hybrid-view__messages::-webkit-scrollbar-thumb {
    background: var(--surface-3);
    border-radius: var(--radius-xs);
}

.hybrid-view__conv-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: var(--space-2);
    color: var(--text-muted);
    opacity: 0.5;
    font-size: var(--text-xs);
}

/* Inline streaming in chat pane */
.hybrid-view__conv-streaming {
    padding: var(--space-1) var(--space-2);
}

.hybrid-view__conv-streaming :deep(.bubble-row) {
    justify-content: flex-start;
    margin-bottom: 0;
}

.hybrid-view__conv-streaming :deep(.streaming-bubble) {
    max-width: 100%;
    padding: 0;
}

/* Input zone */
.hybrid-view__input-zone {
    position: relative;
    flex-shrink: 0;
}

/* Override ChatInput to sit flush inside the pane */
.hybrid-view__input-zone :deep(.ci) {
    border-left: none;
    border-right: none;
    border-bottom: none;
}

/* ── Divider ────────────────────────────────────────────────── */

.hybrid-view__divider {
    width: 4px;
    flex-shrink: 0;
    cursor: col-resize;
    z-index: var(--z-raised);
    background: transparent;
    transition: background var(--transition-fast);
}

.hybrid-view__divider:hover,
.hybrid-view__divider--active {
    background: var(--accent-border);
}

/* ── Right workspace pane ───────────────────────────────────── */

.hybrid-view__workspace {
    position: relative;
    z-index: var(--z-base);
    flex: 1;
    display: flex;
    flex-direction: column;
    height: 100%;
    min-width: 0;
    background: var(--surface-0);
}

.hybrid-view__workspace-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 20px 8px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    gap: var(--space-3);
}

.workspace-header__left {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    min-width: 0;
    overflow: hidden;
}

.workspace-header__label {
    font-size: var(--text-2xs);
    font-weight: var(--weight-semibold);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-muted);
    flex-shrink: 0;
}

.workspace-header__stop {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    padding: 3px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    font-size: var(--text-2xs);
    cursor: pointer;
    flex-shrink: 0;
    transition:
        color var(--transition-fast),
        border-color var(--transition-fast),
        background var(--transition-fast);
}

.workspace-header__stop:hover {
    color: var(--danger);
    border-color: var(--danger);
    background: color-mix(in srgb, var(--danger) 6%, transparent);
}

/* ── Workspace tabs ─────────────────────────────────────────── */

.workspace-tabs {
    display: flex;
    align-items: center;
    gap: 2px;
    flex-shrink: 0;
}

.workspace-tab {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    font-size: var(--text-2xs);
    font-weight: var(--weight-medium);
    cursor: pointer;
    white-space: nowrap;
    transition:
        color var(--transition-fast),
        background var(--transition-fast),
        border-color var(--transition-fast);
}

.workspace-tab:hover {
    color: var(--text-secondary);
    background: var(--surface-2);
}

.workspace-tab--active {
    color: var(--accent);
    border-color: var(--accent-border);
    background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.workspace-tab__badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    border-radius: var(--radius-full);
    background: var(--surface-3);
    color: var(--text-muted);
    font-size: 9px;
    font-weight: var(--weight-semibold);
    line-height: 1;
}

.workspace-tab--active .workspace-tab__badge {
    background: color-mix(in srgb, var(--accent) 15%, transparent);
    color: var(--accent);
}

/* ── Viewer containers (3D / Chart / Whiteboard) ────────────── */

.workspace-viewer {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
    position: relative;
}

.workspace-viewer--placeholder {
    background: var(--surface-0);
}

.workspace-viewer--chart,
.workspace-viewer--wb {
    padding: var(--space-4);
    gap: var(--space-3);
}

.workspace-viewer__nav {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    flex-shrink: 0;
}

.workspace-viewer__nav-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-full);
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--text-secondary);
    cursor: pointer;
    transition:
        color var(--transition-fast),
        background var(--transition-fast),
        border-color var(--transition-fast);
}

.workspace-viewer__nav-btn:hover:not(:disabled) {
    color: var(--accent);
    border-color: var(--accent-border);
    background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.workspace-viewer__nav-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
}

.workspace-viewer__counter {
    font-size: var(--text-2xs);
    color: var(--text-muted);
    font-weight: var(--weight-medium);
    min-width: 40px;
    text-align: center;
}

/* ChartViewer fills available space */
.workspace-viewer--chart :deep(.chart-viewer) {
    flex: 1;
    min-height: 300px;
}

/* TldrawCanvas fills available space */
.workspace-viewer--wb :deep(.tldraw-wrapper) {
    flex: 1;
    min-height: 300px;
    border-radius: var(--radius-md);
    overflow: hidden;
}

/* Workspace body */
.hybrid-view__workspace-body {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-6) var(--space-8);
    scroll-behavior: smooth;
}

.hybrid-view__workspace-body::-webkit-scrollbar {
    width: 5px;
}

.hybrid-view__workspace-body::-webkit-scrollbar-track {
    background: transparent;
}

.hybrid-view__workspace-body::-webkit-scrollbar-thumb {
    background: var(--surface-3);
    border-radius: var(--radius-xs);
}

/* Empty workspace */
.workspace-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: var(--space-3);
    text-align: center;
}

.workspace-empty__orb {
    color: var(--text-muted);
    opacity: 0.25;
}

.workspace-empty__title {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-secondary);
    margin: 0;
}

.workspace-empty__sub {
    font-size: var(--text-xs);
    color: var(--text-muted);
    margin: 0;
    line-height: 1.6;
    opacity: 0.7;
}

/* ── Reduced motion ─────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
    .typing-dot {
        animation: none;
        opacity: 0.5;
    }
}
</style>
