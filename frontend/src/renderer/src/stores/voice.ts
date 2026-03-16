/**
 * Pinia store for voice state management (STT + TTS).
 *
 * Tracks recording, transcription, and playback states.
 * Used by the useVoice composable and voice components.
 */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

export const useVoiceStore = defineStore('voice', () => {
  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  /** Whether the microphone is currently recording. */
  const isListening = ref(false)

  /** Whether STT is processing audio. */
  const isProcessing = ref(false)

  /** Whether TTS is playing audio. */
  const isSpeaking = ref(false)

  /** The latest transcript from STT. */
  const transcript = ref('')

  /** Microphone input level (0-1). */
  const audioLevel = ref(0)

  /** Whether voice features are enabled in backend config. */
  const enabled = ref(false)

  /** Whether STT is available on the backend. */
  const sttAvailable = ref(false)

  /** Whether TTS is available on the backend. */
  const ttsAvailable = ref(false)

  /** Microphone permission status. */
  const micPermission = ref<'granted' | 'denied' | 'prompt'>('prompt')

  /** Voice WebSocket connection status. */
  const connected = ref(false)

  /** Whether to show confirmation UI before sending transcript. Default: false (auto-send). */
  const confirmTranscript = ref<boolean>(loadConfirmTranscript())

  /** STT model name (e.g. "small", "large-v3"). */
  const sttModel = ref('')

  /** STT engine name (e.g. "faster-whisper"). */
  const sttEngine = ref('')

  /** TTS engine name (e.g. "piper"). */
  const ttsEngine = ref('')

  /** TTS voice name (e.g. "paola", "im_nicola"). */
  const ttsVoice = ref('')

  /** Voice activation mode. */
  const activationMode = ref<'push_to_talk' | 'wake_word' | 'always_on'>('push_to_talk')

  /** Wake word for wake_word activation mode. */
  const wakeWord = ref('omnia')

  /** Whether LLM responses should be read aloud automatically. */
  const autoTtsResponse = ref(true)

  /** Recording duration in seconds. */
  const recordingDuration = ref(0)

  /** Recording start timestamp (ms). */
  let recordingStartTime = 0

  /** Recording duration update timer. */
  let durationTimer: ReturnType<typeof setInterval> | null = null

  /** Whether to include pending chat attachments when sending via voice. Default: true. */
  const sttIncludeAttachments = ref<boolean>(loadSttIncludeAttachments())

  function loadConfirmTranscript(): boolean {
    try {
      return localStorage.getItem('omnia_voice_confirm_transcript') === 'true'
    } catch {
      return false
    }
  }

  function loadSttIncludeAttachments(): boolean {
    try {
      const stored = localStorage.getItem('omnia_stt_include_attachments')
      return stored === null ? true : stored === 'true'
    } catch {
      return true
    }
  }

  watch(confirmTranscript, (val) => {
    localStorage.setItem('omnia_voice_confirm_transcript', String(val))
  })

  watch(sttIncludeAttachments, (val) => {
    localStorage.setItem('omnia_stt_include_attachments', String(val))
  })

  // ---------------------------------------------------------------------------
  // Computed
  // ---------------------------------------------------------------------------

  /** Whether any voice activity is happening. */
  const isActive = computed(() => isListening.value || isProcessing.value || isSpeaking.value)

  /** Current voice state label. */
  const voiceState = computed<'idle' | 'recording' | 'processing' | 'speaking'>(() => {
    if (isListening.value) return 'recording'
    if (isProcessing.value) return 'processing'
    if (isSpeaking.value) return 'speaking'
    return 'idle'
  })

  /** Whether voice services are usable (enabled + at least one service available). */
  const isReady = computed(() => enabled.value && (sttAvailable.value || ttsAvailable.value))

  /** Recording duration formatted as "m:ss" (e.g., "0:05", "1:23"). */
  const formattedDuration = computed(() => {
    const s = recordingDuration.value
    const min = Math.floor(s / 60)
    const sec = Math.floor(s % 60)
    return `${min}:${sec.toString().padStart(2, '0')}`
  })

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  /** Start tracking recording duration. */
  function startRecordingTimer(): void {
    recordingStartTime = Date.now()
    recordingDuration.value = 0
    durationTimer = setInterval(() => {
      recordingDuration.value = (Date.now() - recordingStartTime) / 1000
    }, 100)
  }

  /** Stop tracking recording duration. */
  function stopRecordingTimer(): void {
    if (durationTimer) {
      clearInterval(durationTimer)
      durationTimer = null
    }
  }

  /** Clear the current transcript. */
  function clearTranscript(): void {
    transcript.value = ''
  }

  /** Reset all voice state to initial values. */
  function reset(): void {
    isListening.value = false
    isProcessing.value = false
    isSpeaking.value = false
    transcript.value = ''
    audioLevel.value = 0
    recordingDuration.value = 0
    sttModel.value = ''
    sttEngine.value = ''
    ttsEngine.value = ''
    ttsVoice.value = ''
    stopRecordingTimer()
  }

  return {
    // State
    isListening,
    isProcessing,
    isSpeaking,
    transcript,
    audioLevel,
    enabled,
    sttAvailable,
    ttsAvailable,
    micPermission,
    connected,
    confirmTranscript,
    sttIncludeAttachments,
    recordingDuration,
    sttModel,
    sttEngine,
    ttsEngine,
    ttsVoice,
    activationMode,
    wakeWord,
    autoTtsResponse,

    // Computed
    isActive,
    voiceState,
    isReady,
    formattedDuration,

    // Actions
    startRecordingTimer,
    stopRecordingTimer,
    clearTranscript,
    reset,
  }
})
