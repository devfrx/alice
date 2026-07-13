<!-- views/HorizonView.vue -->
<script setup lang="ts">
/**
 * HorizonView — the assistant desk ("atelier"): the ambient scene (greeting,
 * composer, paced response, horizon line) with free-floating module windows
 * (DeskSurface) and the tray (DeskDock) above it. Orchestration only — the
 * heavy wiring lives in useHorizonKeyboard / useHorizonVoiceBridge and the
 * desk store; scene derivation stays in the pure horizonScene brain.
 */
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import HorizonPlan from '../components/horizon/HorizonPlan.vue'
import HorizonScene from '../components/horizon/HorizonScene.vue'
import HorizonLine from '../components/horizon/HorizonLine.vue'
import HorizonMasthead from '../components/horizon/HorizonMasthead.vue'
import HorizonQuiet from '../components/horizon/HorizonQuiet.vue'
import HorizonColophon from '../components/horizon/HorizonColophon.vue'
import HorizonCockpit from '../components/horizon/HorizonCockpit.vue'
import HorizonComposer from '../components/horizon/HorizonComposer.vue'
import HorizonResponse from '../components/horizon/HorizonResponse.vue'
import DeskSurface from '../components/desk/DeskSurface.vue'
import DeskDock from '../components/desk/DeskDock.vue'
import ToolConfirmationDialog from '../components/chat/ToolConfirmationDialog.vue'
import AskUserPrompt from '../components/chat/AskUserPrompt.vue'
import { ChatApiKey } from '../composables/useChat'
import { useSentencePacer } from '../composables/horizon/useSentencePacer'
import { useHorizonKeyboard } from '../composables/horizon/useHorizonKeyboard'
import { useHorizonVoiceBridge } from '../composables/horizon/useHorizonVoiceBridge'
import { useThinkingSignal } from '../composables/horizon/useThinkingSignal'
import { useVoice } from '../composables/useVoice'
import { useModal } from '../composables/useModal'
import {
  deriveSceneState,
  deriveLineMode,
  deriveSkyMode,
  planView,
  type HorizonSceneInputs
} from '../composables/horizon/horizonScene'
import { extractArtifacts } from '../composables/horizon/horizonArtifacts'
import { useGenerationState } from '../composables/useGenerationState'
import { useChatStore } from '../stores/chat'
import { useVoiceStore } from '../stores/voice'
import { useTasksStore } from '../stores/tasks'
import { useCalendarStore } from '../stores/calendar'
import { useDeskStore } from '../stores/desk'
import '../assets/styles/horizon.css'

const chatStore = useChatStore()
const voiceStore = useVoiceStore()
const tasksStore = useTasksStore()
const calendarStore = useCalendarStore()
const desk = useDeskStore()

const chatApi = inject(ChatApiKey, null)
const _noop = (): void => {}
const _asyncNoop = async (): Promise<void> => {}
const send = chatApi?.sendMessage ?? _asyncNoop
const stopGeneration = chatApi?.stopGeneration ?? _noop
const respondToConfirmation = chatApi?.respondToConfirmation ?? _noop
const answerAskUser = chatApi?.answerAskUser ?? _noop
const isConnected = chatApi?.isConnected ?? ref(false)

const {
  startListening,
  stopListening,
  cancelProcessing,
  connect: connectVoice,
  transcript,
  speak,
  cancelSpeak,
  audioDevices,
  selectedDeviceId,
  refreshDevices
} = useVoice()

const { cadGenerationInProgress } = useGenerationState()
const { state: modalState } = useModal()
const isThinking = useThinkingSignal()

/* ── local state ── */
const composerActive = ref(false)
const magazine = ref(false)
const composerRef = ref<InstanceType<typeof HorizonComposer> | null>(null)
const cockpitRef = ref<InstanceType<typeof HorizonCockpit> | null>(null)

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

/* ── derived ── */
const planSteps = computed(() => {
  const id = chatStore.currentConversation?.id
  return id ? tasksStore.tasksFor(id) : []
})

const artifacts = computed(() => extractArtifacts(chatStore.messages))

const sceneInputs = computed<HorizonSceneInputs>(() => ({
  isListening: voiceStore.isListening,
  isSttProcessing: voiceStore.isProcessing,
  isSpeaking: voiceStore.isSpeaking,
  isStreaming: chatStore.isStreamingCurrentConversation,
  activeToolCount: chatStore.activeToolExecutions.length,
  planSteps: planSteps.value,
  composerActive: composerActive.value,
  isThinking: isThinking.value
}))

const sceneState = computed(() => deriveSceneState(sceneInputs.value))
const lineMode = computed(() => deriveLineMode(sceneState.value, sceneInputs.value))
const skyMode = computed(() => deriveSkyMode(sceneState.value, sceneInputs.value))

const { displayed: pacedStream, reset: resetPacer } = useSentencePacer(
  computed(() => chatStore.currentStreamContent),
  computed(() => chatStore.isStreamingCurrentConversation),
  { immediate: reducedMotion }
)

const lastResponse = computed(() => {
  const msgs = chatStore.messages
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'assistant' && msgs[i].content.trim()) return msgs[i].content
  }
  return ''
})

const lastUserQuery = computed(() => {
  const msgs = chatStore.messages
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'user' && msgs[i].content.trim()) return msgs[i].content
  }
  return ''
})

const responseText = computed(() => {
  if (sceneState.value === 'responding') {
    return chatStore.isStreamingCurrentConversation ? pacedStream.value : lastResponse.value
  }
  if (sceneState.value === 'quiet') return lastResponse.value
  return ''
})

const showResponse = computed(
  () =>
    responseText.value !== '' &&
    (sceneState.value === 'responding' || (sceneState.value === 'quiet' && !composerActive.value))
)

const plan = computed(() => planView(planSteps.value))

const lineLabel = computed(() => {
  if (voiceStore.isListening) return 'ASCOLTO'
  if (voiceStore.isProcessing) return 'ELABORO'
  if (sceneState.value === 'working')
    return planSteps.value.length > 0
      ? `LAVORO ${plan.value.activeIndex + 1} DI ${plan.value.total}`
      : 'LAVORO'
  if (sceneState.value === 'thinking') return 'RAGIONO'
  if (sceneState.value === 'responding') return 'RISPONDO'
  return ''
})

/* Ephemeral tool annotation (ambient sign; full detail = Attività window). */
const toolAnnotation = ref('')
let annotationTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => chatStore.activeToolExecutions.map((t) => t.toolName).join(','),
  () => {
    const tools = chatStore.activeToolExecutions
    const last = tools[tools.length - 1]
    if (!last) return
    toolAnnotation.value = last.toolName.replace(/_/g, ' ')
    if (annotationTimer) clearTimeout(annotationTimer)
    annotationTimer = setTimeout(() => {
      toolAnnotation.value = ''
    }, 2500)
  }
)

const pendingConfirmationsList = computed(() => Object.values(chatStore.pendingConfirmations))
const pendingAskUserList = computed(() => Object.values(chatStore.pendingAskUser))
const sceneDimmed = computed(
  () => pendingConfirmationsList.value.length > 0 || pendingAskUserList.value.length > 0
)

/* ── interactions ── */
/** Clicking empty desk space toggles voice — never windows, dock or overlays. */
function handleSceneClick(event: MouseEvent): void {
  if (sceneDimmed.value) return
  const tgt = event.target as HTMLElement | null
  if (
    tgt?.closest(
      'button, a, input, textarea, [contenteditable], .desk-window, .desk-dock, .hz-response'
    )
  )
    return
  if (voiceStore.isSpeaking) {
    cancelSpeak()
  } else if (chatStore.isStreamingCurrentConversation) {
    stopGeneration()
    cancelSpeak()
  } else if (voiceStore.isListening) {
    stopListening()
  } else if (voiceStore.isProcessing) {
    cancelProcessing()
  } else if (!composerActive.value) {
    startListening()
  }
}

async function handleComposerSend(content: string): Promise<void> {
  const files = cockpitRef.value ? [...cockpitRef.value.pendingFiles] : []
  cockpitRef.value?.clearAllFiles()
  composerActive.value = false
  await send(content, undefined, files.length > 0 ? files : undefined).catch(console.error)
}

function handleComposerPaste(e: ClipboardEvent): void {
  cockpitRef.value?.handlePaste(e)
}

function activateComposer(seed: string): void {
  composerActive.value = true
  composerRef.value?.seed(seed)
}

/** Materialize the ambient conversation into the chat window (singleton). */
function materializeConversation(): void {
  desk.openWindow('chat')
}

useHorizonKeyboard({
  modalVisible: () => modalState.visible,
  sceneDimmed: () => sceneDimmed.value,
  composerActive,
  isSpeaking: () => voiceStore.isSpeaking,
  isStreaming: () => chatStore.isStreamingCurrentConversation,
  cancelSpeak,
  stopGeneration,
  seedComposer: (ch) => composerRef.value?.seed(ch),
  hasFocusedWindow: () => desk.focusedId !== null,
  blurWindows: () => desk.blurWindows()
})

useHorizonVoiceBridge({ send, activateComposer, speak })

/* ── watchers ── */
// New turn: reset pacing + magazine.
watch(
  () => chatStore.isStreamingCurrentConversation,
  (streaming, was) => {
    if (streaming && !was) {
      resetPacer()
      magazine.value = false
    }
  }
)

// Conversation switch: pacing and layout never leak across conversations.
watch(
  () => chatStore.currentConversation?.id,
  (id) => {
    resetPacer()
    magazine.value = false
    if (id)
      tasksStore.ensureForConversation(id).catch(() => {
        /* timeline stays empty */
      })
  }
)

// A new artifact in a live turn opens its window (auto-open, spec §3.2).
watch(
  () => artifacts.value.length,
  (len, was) => {
    if (len > (was ?? 0) && chatStore.isStreamingCurrentConversation) {
      const a = artifacts.value[len - 1]
      if (a.kind === 'chart' && a.chart) desk.openWindow('chart', { chartPayload: a.chart })
      else if (a.kind === 'whiteboard' && a.board)
        desk.openWindow('whiteboard', { boardId: a.board.board_id })
      else if (a.kind === '3d') desk.openWindow('cad3d')
    }
  }
)

// CAD generation surfaces its window once per generation (stable executionId).
watch(
  () => cadGenerationInProgress.value?.executionId,
  (id, old) => {
    if (id && id !== old) desk.openWindow('cad3d')
  }
)

/* ── lifecycle ── */
onMounted(() => {
  connectVoice()
  chatStore.restoreConversation().catch(console.error)
  calendarStore.startPolling()
  const id = chatStore.currentConversation?.id
  if (id) {
    tasksStore.ensureForConversation(id).catch(() => {
      /* timeline simply stays empty */
    })
  }
})

onBeforeUnmount(() => {
  calendarStore.stopPolling()
  if (annotationTimer) clearTimeout(annotationTimer)
})
</script>

<template>
  <div class="horizon-view" aria-label="Assistente" @click="handleSceneClick">
    <HorizonScene :state="sceneState" :sky="skyMode" :magazine="magazine" :dimmed="sceneDimmed">
      <template #masthead>
        <HorizonMasthead :connected="isConnected" />
      </template>

      <template #upper>
        <Transition name="hz-soft">
          <HorizonQuiet v-if="sceneState === 'quiet' && !composerActive && !lastResponse" />
        </Transition>
        <HorizonComposer
          ref="composerRef"
          :active="composerActive"
          :listening="voiceStore.isListening"
          :stt-processing="voiceStore.isProcessing"
          :transcript="transcript"
          :disabled="chatStore.isStreamingCurrentConversation"
          @send="handleComposerSend"
          @paste="handleComposerPaste"
        />
        <Transition name="hz-soft">
          <HorizonCockpit
            v-if="composerActive"
            ref="cockpitRef"
            :is-streaming="chatStore.isStreamingCurrentConversation"
            :audio-devices="audioDevices"
            :selected-device-id="selectedDeviceId"
            @send="composerRef?.submit()"
            @stop="stopGeneration"
            @voice-start="startListening"
            @voice-stop="stopListening"
            @voice-cancel-processing="cancelProcessing"
            @refresh-devices="refreshDevices"
            @select-device="(id) => (selectedDeviceId = id)"
          />
        </Transition>
        <HorizonResponse
          v-if="showResponse && !magazine"
          v-model:magazine="magazine"
          :text="responseText"
          :user-query="lastUserQuery"
          :compact="false"
        />
        <p v-if="sceneState === 'working' && plan.statusSentence" class="horizon-view__status">
          <em>{{ plan.statusSentence }}</em>
        </p>
      </template>

      <template #line>
        <HorizonLine
          :mode="lineMode"
          :audio-level="voiceStore.audioLevel"
          :notch-count="sceneState === 'working' ? planSteps.length : 0"
          :active-index="plan.activeIndex"
          :completed-count="plan.completed"
          :dimmed="!isConnected"
          :label="lineLabel"
          :impulses="sceneState === 'thinking' || sceneState === 'working'"
        />
      </template>

      <template #lower>
        <HorizonPlan
          v-if="sceneState === 'working' && planSteps.length > 0"
          :steps="planSteps"
          :active-index="plan.activeIndex"
          :completed="plan.completed"
          :annotation="toolAnnotation"
        />
        <HorizonResponse
          v-if="showResponse && magazine"
          v-model:magazine="magazine"
          :text="responseText"
          :user-query="lastUserQuery"
          :compact="false"
        />
        <p v-if="sceneState === 'responding' && lastUserQuery" class="horizon-view__echo">
          {{ lastUserQuery }}
        </p>
        <HorizonColophon :next-event="calendarStore.nextEvent" :connected="isConnected" />
      </template>
    </HorizonScene>

    <!-- The windows layer + tray (the desk) -->
    <DeskSurface />
    <DeskDock />

    <nav class="horizon-view__corner" aria-label="Navigazione">
      <button class="horizon-view__affordance" type="button" @click="materializeConversation">
        CONVERSAZIONE
      </button>
      <RouterLink class="horizon-view__affordance" :to="{ name: 'workspace' }">
        WORKSPACE
      </RouterLink>
    </nav>

    <ToolConfirmationDialog
      v-if="pendingConfirmationsList.length > 0"
      :key="pendingConfirmationsList[0].executionId"
      :confirmation="pendingConfirmationsList[0]"
      @respond="respondToConfirmation"
    />

    <!-- ask_user sits ABOVE the dimmed scene (pointer-events gate). -->
    <div v-if="pendingAskUserList.length > 0" class="horizon-view__ask">
      <AskUserPrompt
        v-for="r in pendingAskUserList"
        :key="r.executionId"
        :request="r"
        @answer="answerAskUser"
      />
    </div>
  </div>
</template>

<style scoped>
.horizon-view {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.horizon-view__ask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-5);
  overflow-y: auto;
  z-index: var(--z-overlay);
}

.horizon-view__ask > * {
  width: min(640px, 92%);
}

.hz-soft-enter-active,
.hz-soft-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-soft-enter-from,
.hz-soft-leave-to {
  opacity: 0;
}

.horizon-view__echo {
  margin: var(--space-3) 0 0;
  font-family: var(--font-sans);
  font-size: 10px;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
  max-width: 70%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.horizon-view__status {
  margin: 0 0 clamp(20px, 4vh, 48px);
  max-width: min(60ch, 80%);
  font-family: var(--hz-serif);
  font-style: italic;
  font-weight: 300;
  font-size: clamp(17px, 2.4vmin, 24px);
  color: var(--hz-ink);
  text-align: center;
}

.horizon-view__corner {
  position: absolute;
  right: clamp(16px, 3vw, 32px);
  bottom: clamp(14px, 3vh, 28px);
  display: flex;
  gap: var(--space-4);
  z-index: var(--z-sticky);
}

.horizon-view__affordance {
  border: none;
  background: transparent;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: var(--hz-ink-faint);
  text-decoration: none;
  cursor: pointer;
  transition: color var(--hz-fade) ease;
}

.horizon-view__affordance:hover {
  color: var(--hz-ink);
}
</style>
