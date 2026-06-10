<script setup lang="ts">
/**
 * HorizonView — the assistant surface: one morphing editorial scene whose
 * axis is the horizon line (AL\CE's presence). Orchestration only: this file
 * wires stores/composables into props for components/horizon/*; it owns no
 * scene markup beyond composition.
 */
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import HorizonPlan from '../components/horizon/HorizonPlan.vue'
import HorizonScene from '../components/horizon/HorizonScene.vue'
import HorizonLine from '../components/horizon/HorizonLine.vue'
import HorizonMasthead from '../components/horizon/HorizonMasthead.vue'
import HorizonQuiet from '../components/horizon/HorizonQuiet.vue'
import HorizonColophon from '../components/horizon/HorizonColophon.vue'
import HorizonComposer from '../components/horizon/HorizonComposer.vue'
import HorizonResponse from '../components/horizon/HorizonResponse.vue'
import { ChatApiKey } from '../composables/useChat'
import { useSentencePacer } from '../composables/horizon/useSentencePacer'
import { useVoice } from '../composables/useVoice'
import { useModal } from '../composables/useModal'
import {
  deriveSceneState,
  deriveLineMode,
  planView,
  type HorizonSceneInputs
} from '../composables/horizon/horizonScene'
import { useChatStore } from '../stores/chat'
import { useVoiceStore } from '../stores/voice'
import { useTasksStore } from '../stores/tasks'
import { useCalendarStore } from '../stores/calendar'
import '../assets/styles/horizon.css'

const chatStore = useChatStore()
const voiceStore = useVoiceStore()
const tasksStore = useTasksStore()
const calendarStore = useCalendarStore()

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
  cancelSpeak
} = useVoice()

const { state: modalState } = useModal()

/* ── ANCHOR: local-state ── */
const composerActive = ref(false)
const stageOpen = ref(false)
const composerRef = ref<InstanceType<typeof HorizonComposer> | null>(null)

const magazine = ref(false)

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

/* ── ANCHOR: derived ── */
const planSteps = computed(() => {
  const id = chatStore.currentConversation?.id
  return id ? tasksStore.tasksFor(id) : []
})

/** Replaced by the artifact extraction in the Stage task. */
const artifactCount = computed(() => 0)

const sceneInputs = computed<HorizonSceneInputs>(() => ({
  isListening: voiceStore.isListening,
  isSttProcessing: voiceStore.isProcessing,
  isSpeaking: voiceStore.isSpeaking,
  isStreaming: chatStore.isStreamingCurrentConversation,
  activeToolCount: chatStore.activeToolExecutions.length,
  planSteps: planSteps.value,
  stageOpen: stageOpen.value,
  artifactCount: artifactCount.value,
  composerActive: composerActive.value
}))

const sceneState = computed(() => deriveSceneState(sceneInputs.value))
const lineMode = computed(() => deriveLineMode(sceneState.value, sceneInputs.value))

const { displayed: pacedStream, reset: resetPacer } = useSentencePacer(
  computed(() => chatStore.currentStreamContent),
  computed(() => chatStore.isStreamingCurrentConversation),
  { immediate: reducedMotion }
)

/** Last completed assistant message (shown in quiet until a new turn). */
const lastResponse = computed(() => {
  const msgs = chatStore.messages
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'assistant' && msgs[i].content.trim()) return msgs[i].content
  }
  return ''
})

/** Last user message, echoed in small caps below the line. */
const lastUserQuery = computed(() => {
  const msgs = chatStore.messages
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'user' && msgs[i].content.trim()) return msgs[i].content
  }
  return ''
})

/** What the response component shows per state. */
const responseText = computed(() => {
  if (sceneState.value === 'responding') {
    // While streaming: only the paced stream (the previous answer must not
    // flash at turn start). Responding via TTS after the stream: the
    // committed message is the source of truth.
    return chatStore.isStreamingCurrentConversation ? pacedStream.value : lastResponse.value
  }
  if (sceneState.value === 'quiet' || sceneState.value === 'presenting') return lastResponse.value
  return ''
})

const showResponse = computed(
  () =>
    responseText.value !== '' &&
    (sceneState.value === 'responding' ||
      sceneState.value === 'presenting' ||
      (sceneState.value === 'quiet' && !composerActive.value))
)

const plan = computed(() => planView(planSteps.value))

/* Ephemeral tool annotation: latest active tool name, faded after 2.5 s. */
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

/* ── ANCHOR: interactions ── */
/** Clicking empty scene space toggles voice (mirrors the old orb click). */
function handleSceneClick(event: MouseEvent): void {
  // A pending dialog dims the scene (pointer-events: none) and retargets
  // every click to this wrapper — never treat those as voice toggles.
  if (sceneDimmed.value) return
  const tgt = event.target as HTMLElement | null
  if (
    tgt?.closest(
      'button, a, input, textarea, [contenteditable], .hz-stage, .hz-history, .hz-response'
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

/** Sends typed text; collapses the composer. */
async function handleComposerSend(content: string): Promise<void> {
  composerActive.value = false
  await send(content).catch(console.error)
}

/**
 * Global key capture: Esc walks the interrupt chain; any printable first
 * character materializes the composer (Jarvis entry — no visible input box).
 */
function onGlobalKeydown(e: KeyboardEvent): void {
  if (e.isComposing) return
  // A global modal owns the keyboard — never steal keystrokes or walk the chain.
  if (modalState.visible) return
  if (e.key === 'Escape') {
    if (voiceStore.isSpeaking) cancelSpeak()
    else if (chatStore.isStreamingCurrentConversation) stopGeneration()
    else if (stageOpen.value) stageOpen.value = false
    else composerActive.value = false
    return
  }
  if (composerActive.value) return
  const tgt = e.target as HTMLElement | null
  if (tgt?.closest('input, textarea, select, button, [contenteditable="true"], [role="dialog"]'))
    return
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault()
    composerActive.value = true
    composerRef.value?.seed(e.key)
  }
}

/* ── ANCHOR: voice-wiring ── */
// Auto-send the STT transcript when confirmation is disabled.
watch(
  () => voiceStore.transcript,
  (text) => {
    if (!text.trim() || voiceStore.confirmTranscript) return
    const toSend = text.trim()
    voiceStore.clearTranscript()
    send(toSend).catch(console.error)
  }
)

// New turn: reset pacing + magazine when a fresh stream starts.
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

// TTS auto-speak when streaming completes (lifted from the legacy view).
let wasStreamingHere = false
watch(
  () => chatStore.isStreamingCurrentConversation,
  (streaming) => {
    if (streaming) {
      wasStreamingHere = true
      return
    }
    if (!wasStreamingHere) return
    wasStreamingHere = false
    if (!voiceStore.autoTtsResponse || !voiceStore.ttsAvailable || !voiceStore.connected) return
    const msgs = chatStore.messages
    let lastUserIdx = -1
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'user') {
        lastUserIdx = i
        break
      }
    }
    const allContent = msgs
      .slice(lastUserIdx + 1)
      .filter((m) => m.role === 'assistant' && m.content.trim())
      .map((m) => m.content.trim())
      .join('\n')
    if (allContent) speak(allContent)
  }
)

/* ── ANCHOR: lifecycle ── */
onMounted(() => {
  connectVoice()
  chatStore.restoreConversation().catch(console.error)
  // Polling (not a one-shot refresh): the quiet scene is an ambient,
  // always-on surface — the colophon's next event must not go stale.
  calendarStore.startPolling()
  const id = chatStore.currentConversation?.id
  if (id) {
    tasksStore.ensureForConversation(id).catch(() => {
      /* timeline simply stays empty */
    })
  }
  window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  calendarStore.stopPolling()
  window.removeEventListener('keydown', onGlobalKeydown)
  if (annotationTimer) clearTimeout(annotationTimer)
})

// Suppress unused-variable warnings for vars wired in later tasks (11).
void respondToConfirmation
void answerAskUser
</script>

<template>
  <div class="horizon-view" aria-label="Assistente" @click="handleSceneClick">
    <HorizonScene :state="sceneState" :magazine="magazine" :dimmed="sceneDimmed">
      <template #masthead>
        <HorizonMasthead :connected="isConnected" />
      </template>

      <template #upper>
        <!-- ANCHOR: upper-zone -->
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
        />
        <HorizonResponse
          v-if="showResponse && !magazine"
          v-model:magazine="magazine"
          :text="responseText"
          :user-query="lastUserQuery"
          :compact="sceneState === 'presenting'"
        />
        <p v-if="sceneState === 'working' && plan.statusSentence" class="horizon-view__status">
          <em>{{ plan.statusSentence }}</em>
        </p>
      </template>

      <template #line>
        <!-- dimmed → "embers" when the chat socket is down (spec §3.6) -->
        <HorizonLine
          :mode="lineMode"
          :audio-level="voiceStore.audioLevel"
          :notch-count="sceneState === 'working' ? planSteps.length : 0"
          :active-index="plan.activeIndex"
          :dimmed="!isConnected"
        />
      </template>

      <template #lower>
        <!-- ANCHOR: lower-zone -->
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
          :compact="sceneState === 'presenting'"
        />
        <p v-if="sceneState === 'responding' && lastUserQuery" class="horizon-view__echo">
          {{ lastUserQuery }}
        </p>
        <HorizonColophon
          v-if="sceneState !== 'presenting'"
          :next-event="calendarStore.nextEvent"
          :connected="isConnected"
        />
      </template>
    </HorizonScene>

    <!-- ANCHOR: overlays -->
  </div>
</template>

<style scoped>
.horizon-view {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

/* Shared soft fade for scene content swaps. */
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
</style>
