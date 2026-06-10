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
import HorizonStage from '../components/horizon/HorizonStage.vue'
import { RouterLink } from 'vue-router'
import HorizonHistory from '../components/horizon/HorizonHistory.vue'
import ToolConfirmationDialog from '../components/chat/ToolConfirmationDialog.vue'
import AskUserPrompt from '../components/chat/AskUserPrompt.vue'
import MessageEditDialog from '../components/chat/MessageEditDialog.vue'
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
import { extractArtifacts } from '../composables/horizon/horizonArtifacts'
import { useGenerationState } from '../composables/useGenerationState'
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
const editMessage = chatApi?.editMessage ?? _asyncNoop
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

const { cadGenerationInProgress } = useGenerationState()

const { state: modalState, openCustom } = useModal()

/* ── ANCHOR: local-state ── */
const composerActive = ref(false)
const historyOpen = ref(false)
const stageOpen = ref(false)
const stageIndex = ref(0)
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

const artifacts = computed(() => extractArtifacts(chatStore.messages))
const artifactCount = computed(
  () => artifacts.value.length + (cadGenerationInProgress.value ? 1 : 0)
)

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
async function startEdit(messageId: string): Promise<void> {
  if (chatStore.isStreamingCurrentConversation) return
  const msg = chatStore.messages.find((m) => m.id === messageId)
  if (!msg || msg.role !== 'user') return
  await openCustom({
    component: MessageEditDialog,
    props: {
      originalContent: msg.content,
      onSubmit: async (newContent: string) => {
        await editMessage(messageId, newContent)
      }
    },
    width: '560px'
  })
}

function handleVersionSwitch(versionGroupId: string, versionIndex: number): void {
  chatStore.switchVersion(versionGroupId, versionIndex)
}

async function handleBranch(messageId: string): Promise<void> {
  if (chatStore.isStreamingCurrentConversation) return
  await chatStore.branchConversation(messageId)
}

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
  // A pending confirmation / ask_user owns the keyboard too: Esc must mean
  // "reject the tool", never "abort the whole turn" (mirrors the click guard).
  if (sceneDimmed.value) return
  if (e.key === 'Escape') {
    if (voiceStore.isSpeaking) cancelSpeak()
    else if (chatStore.isStreamingCurrentConversation) stopGeneration()
    else if (stageOpen.value) stageOpen.value = false
    else if (historyOpen.value) historyOpen.value = false
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

// Conversation switch: pacing, layout and stage never leak across conversations.
watch(
  () => chatStore.currentConversation?.id,
  (id) => {
    resetPacer()
    magazine.value = false
    stageOpen.value = false
    stageIndex.value = 0
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

// Auto-open the stage when a new artifact ARRIVES in a live turn (spec §3.5).
// The streaming gate keeps restored conversations (messages loading async on
// mount) and conversation switches from phantom-opening the stage.
watch(
  () => artifacts.value.length,
  (len, was) => {
    if (len > (was ?? 0) && chatStore.isStreamingCurrentConversation) {
      stageOpen.value = true
      stageIndex.value = len - 1
      // A long answer in the same turn must not squeeze the stage to half
      // height: the stage owns the lower zone, prose stays compact above.
      magazine.value = false
    } else if (stageIndex.value >= len) {
      stageIndex.value = Math.max(0, len - 1)
    }
  }
)

// CAD generation surfaces the stage once per generation. Watch the stable
// executionId: the progress computed returns a fresh object every tick, and
// re-opening on each tick would defeat the user's Esc/✕ mid-generation.
watch(
  () => cadGenerationInProgress.value?.executionId,
  (id, old) => {
    if (id && id !== old) stageOpen.value = true
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
        <HorizonStage
          v-if="sceneState === 'presenting'"
          v-model:active-index="stageIndex"
          :artifacts="artifacts"
          :cad-generation="cadGenerationInProgress"
          @close="stageOpen = false"
        />
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
        <AskUserPrompt
          v-for="r in pendingAskUserList"
          :key="r.executionId"
          :request="r"
          @answer="answerAskUser"
        />
        <HorizonColophon
          v-if="sceneState !== 'presenting'"
          :next-event="calendarStore.nextEvent"
          :connected="isConnected"
        />
      </template>
    </HorizonScene>

    <!-- ANCHOR: overlays -->
    <nav class="horizon-view__corner" aria-label="Navigazione">
      <button class="horizon-view__affordance" @click="historyOpen = !historyOpen">STORIA</button>
      <RouterLink class="horizon-view__affordance" :to="{ name: 'workspace' }">
        WORKSPACE
      </RouterLink>
    </nav>

    <HorizonHistory
      :open="historyOpen"
      :messages="chatStore.messages"
      :is-streaming="chatStore.isStreamingCurrentConversation"
      :branch-disabled="chatStore.isStreamingCurrentConversation"
      :get-version-count="chatStore.getVersionCount"
      :get-active-version-index="chatStore.getActiveVersionIndex"
      @close="historyOpen = false"
      @edit="startEdit"
      @switch-version="handleVersionSwitch"
      @branch="handleBranch"
    />

    <ToolConfirmationDialog
      v-if="pendingConfirmationsList.length > 0"
      :key="pendingConfirmationsList[0].executionId"
      :confirmation="pendingConfirmationsList[0]"
      @respond="respondToConfirmation"
    />
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
