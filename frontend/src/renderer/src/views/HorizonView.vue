<script setup lang="ts">
/**
 * HorizonView — the assistant surface: one morphing editorial scene whose
 * axis is the horizon line (AL\CE's presence). Orchestration only: this file
 * wires stores/composables into props for components/horizon/*; it owns no
 * scene markup beyond composition.
 */
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import HorizonScene from '../components/horizon/HorizonScene.vue'
import HorizonLine from '../components/horizon/HorizonLine.vue'
import HorizonMasthead from '../components/horizon/HorizonMasthead.vue'
import HorizonQuiet from '../components/horizon/HorizonQuiet.vue'
import HorizonColophon from '../components/horizon/HorizonColophon.vue'
import HorizonComposer from '../components/horizon/HorizonComposer.vue'
import { ChatApiKey } from '../composables/useChat'
import { useVoice } from '../composables/useVoice'
import {
  deriveSceneState,
  deriveLineMode,
  type HorizonSceneInputs,
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
  cancelSpeak,
} = useVoice()

/* ── ANCHOR: local-state ── */
const composerActive = ref(false)
const stageOpen = ref(false)
const composerRef = ref<InstanceType<typeof HorizonComposer> | null>(null)

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
  composerActive: composerActive.value,
}))

const sceneState = computed(() => deriveSceneState(sceneInputs.value))
const lineMode = computed(() => deriveLineMode(sceneState.value, sceneInputs.value))

const pendingConfirmationsList = computed(() => Object.values(chatStore.pendingConfirmations))
const pendingAskUserList = computed(() => Object.values(chatStore.pendingAskUser))
const sceneDimmed = computed(
  () => pendingConfirmationsList.value.length > 0 || pendingAskUserList.value.length > 0,
)

/* ── ANCHOR: interactions ── */
/** Clicking empty scene space toggles voice (mirrors the old orb click). */
function handleSceneClick(event: MouseEvent): void {
  // A pending dialog dims the scene (pointer-events: none) and retargets
  // every click to this wrapper — never treat those as voice toggles.
  if (sceneDimmed.value) return
  const tgt = event.target as HTMLElement | null
  if (tgt?.closest('button, a, input, textarea, [contenteditable], .hz-stage, .hz-history')) return
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
  if (e.key === 'Escape') {
    if (voiceStore.isSpeaking) cancelSpeak()
    else if (chatStore.isStreamingCurrentConversation) stopGeneration()
    else if (stageOpen.value) stageOpen.value = false
    else composerActive.value = false
    return
  }
  if (composerActive.value) return
  const tgt = e.target as HTMLElement | null
  if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable))
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
  },
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
})

// Suppress unused-variable warnings for vars wired in later tasks (7, 11).
void respondToConfirmation
void answerAskUser
void speak
</script>

<template>
  <div class="horizon-view" aria-label="Assistente" @click="handleSceneClick">
    <HorizonScene :state="sceneState" :dimmed="sceneDimmed">
      <template #masthead>
        <HorizonMasthead :connected="isConnected" />
      </template>

      <template #upper>
        <!-- ANCHOR: upper-zone -->
        <Transition name="hz-soft">
          <HorizonQuiet v-if="sceneState === 'quiet' && !composerActive" />
        </Transition>
        <HorizonComposer
          ref="composerRef"
          :active="composerActive"
          :listening="voiceStore.isListening"
          :stt-processing="voiceStore.isProcessing"
          :transcript="transcript"
          :disabled="chatStore.isStreamingCurrentConversation"
          @send="handleComposerSend"
          @close="composerActive = false"
        />
      </template>

      <template #line>
        <!-- dimmed → "embers" when the chat socket is down (spec §3.6) -->
        <HorizonLine :mode="lineMode" :audio-level="voiceStore.audioLevel" :dimmed="!isConnected" />
      </template>

      <template #lower>
        <!-- ANCHOR: lower-zone -->
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
</style>
