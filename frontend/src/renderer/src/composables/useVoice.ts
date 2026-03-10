/**
 * useVoice — composable for voice interaction (STT + TTS).
 *
 * Manages microphone capture, binary PCM streaming to the backend,
 * and TTS playback from backend responses.
 *
 * Audio capture uses toggle-to-talk: the client sends `voice_start`,
 * streams raw PCM-16 binary frames, then sends `voice_stop` to
 * trigger server-side STT transcription.
 */

import { computed, onScopeDispose, ref, shallowRef, watch, type ComputedRef, type Ref, type ShallowRef } from 'vue'

import { WebSocketManager } from '../services/ws'
import { useChatStore } from '../stores/chat'
import { useVoiceStore } from '../stores/voice'
import type { VoiceReadyMessage } from '../types/voice'

// ---------------------------------------------------------------------------
// AudioWorklet processor source (inlined as JS to avoid TS loading issues).
// Converts Float32 input → PCM-16 Int16 and posts via MessagePort.
// ---------------------------------------------------------------------------
const PCM_WORKLET_SRC = /* js */ `
class PCMProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input || input.length === 0) return true;
    const pcm = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    this.port.postMessage(pcm.buffer, [pcm.buffer]);
    return true;
  }
}
registerProcessor('pcm-processor', PCMProcessor);
`

/** Create a blob URL from the inline worklet source. */
function createWorkletUrl(): string {
  const blob = new Blob([PCM_WORKLET_SRC], { type: 'application/javascript' })
  return URL.createObjectURL(blob)
}

// ---------------------------------------------------------------------------
// Dedicated WebSocket for voice (separate from the chat WS)
// ---------------------------------------------------------------------------

function getVoiceWsUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.hostname || 'localhost'
  const port = '8000'
  return `${protocol}//${host}:${port}/api/voice/ws/voice`
}

const voiceWs = new WebSocketManager(getVoiceWsUrl())
let handlersRegistered = false

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface AudioDevice {
  deviceId: string
  label: string
}

export interface UseVoiceReturn {
  isListening: ComputedRef<boolean>
  isProcessing: ComputedRef<boolean>
  isSpeaking: ComputedRef<boolean>
  transcript: ComputedRef<string>
  audioLevel: ComputedRef<number>
  voiceAvailable: ComputedRef<boolean>
  micPermission: ComputedRef<'granted' | 'denied' | 'prompt'>
  isConnected: ComputedRef<boolean>
  /** List of available audio input devices. */
  audioDevices: ShallowRef<AudioDevice[]>
  /** Currently selected device ID (empty = system default). */
  selectedDeviceId: Ref<string>
  startListening: () => Promise<void>
  stopListening: () => void
  /** Cancel a stuck STT processing state (user-initiated). */
  cancelProcessing: () => void
  speak: (text: string) => void
  cancelSpeak: () => void
  connect: () => void
  disconnect: () => void
  /** Refresh the list of available audio input devices. */
  refreshDevices: () => Promise<void>
}

// ---------------------------------------------------------------------------
// Composable
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'omnia_selected_mic_id'

export function useVoice(): UseVoiceReturn {
  const store = useVoiceStore()
  const chatStore = useChatStore()

  // -- Local state --
  const isConnected = ref(false)
  const voiceAvailable = ref(false)
  const micPermission = ref<'granted' | 'denied' | 'prompt'>('prompt')

  // -- Device selection --
  const audioDevices = shallowRef<AudioDevice[]>([])
  const savedDeviceId = localStorage.getItem(STORAGE_KEY) ?? ''
  const selectedDeviceId = ref(savedDeviceId)

  // Persist mic selection
  watch(selectedDeviceId, (newId) => {
    if (newId) {
      localStorage.setItem(STORAGE_KEY, newId)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  })

  // -- Audio capture resources --
  let mediaStream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let analyserNode: AnalyserNode | null = null
  let workletNode: AudioWorkletNode | null = null
  let levelTimer: ReturnType<typeof setInterval> | null = null
  let workletBlobUrl: string | null = null

  // -- Silence-based auto-stop (continuous modes) --
  const SILENCE_THRESHOLD = 0.04        // normalised level below which we consider silence
  const SPEECH_THRESHOLD = 0.06         // level above which we consider speech started
  const SILENCE_TIMEOUT_MS = 1500       // ms of continuous silence before auto-stop
  let speechDetected = false            // has the user started speaking this recording?
  let silenceSince: number | null = null // timestamp when silence started

  // -- STT processing timeout --
  let sttTimeoutTimer: ReturnType<typeof setTimeout> | null = null
  const STT_TIMEOUT_MS = 135_000 // slightly above backend's 120s limit

  // -- TTS playback resources --
  let playbackCtx: AudioContext | null = null
  let ttsSampleRate = 22050
  const audioQueue: ArrayBuffer[] = []
  let isPlayingQueue = false
  /** True once backend sent tts_done but frontend audio queue hasn't drained yet. */
  let ttsBackendDone = false

  // -----------------------------------------------------------------------
  // WS event handlers
  // -----------------------------------------------------------------------

  const onConnected = (): void => {
    console.log('[OMNIA Voice] WS connected')
    isConnected.value = true
    store.connected = true
  }
  const onDisconnected = (): void => {
    console.log('[OMNIA Voice] WS disconnected')
    isConnected.value = false
    store.connected = false
    if (store.isListening) stopListening()
  }
  // -- Retry timer for when STT is not yet available at connection time --
  let sttRetryTimer: ReturnType<typeof setTimeout> | null = null

  const onVoiceReady = (data: unknown): void => {
    const d = data as VoiceReadyMessage
    console.log('[OMNIA Voice] voice_ready:', d)
    voiceAvailable.value = d.stt_available || d.tts_available
    store.sttAvailable = d.stt_available
    store.ttsAvailable = d.tts_available
    store.enabled = d.stt_available || d.tts_available
    if (d.sample_rate) ttsSampleRate = d.sample_rate
    store.sttModel = d.stt_model ?? ''
    store.sttEngine = d.stt_engine ?? ''
    store.ttsEngine = d.tts_engine ?? ''
    if (d.activation_mode) store.activationMode = d.activation_mode as typeof store.activationMode
    if (d.wake_word !== undefined) store.wakeWord = d.wake_word
    if (d.auto_tts_response !== undefined) store.autoTtsResponse = d.auto_tts_response

    // Clear any pending retry
    if (sttRetryTimer) { clearTimeout(sttRetryTimer); sttRetryTimer = null }

    // Auto-start recording in continuous modes
    if (d.stt_available && (store.activationMode === 'always_on' || store.activationMode === 'wake_word')) {
      scheduleAutoRestart()
    }

    // If STT is not yet available but we're in continuous mode, retry connection
    // after a delay (STT may still be loading after a config save).
    if (!d.stt_available && (store.activationMode === 'always_on' || store.activationMode === 'wake_word')) {
      console.log('[OMNIA Voice] STT not available yet, will retry connection in 5s')
      sttRetryTimer = setTimeout(() => {
        sttRetryTimer = null
        if (!store.sttAvailable && voiceWs.isConnected) {
          console.log('[OMNIA Voice] Reconnecting voice WS to pick up STT service...')
          voiceWs.disconnect()
          setTimeout(() => voiceWs.connect(), 500)
        }
      }, 5000)
    }
  }
  const onTranscript = (data: unknown): void => {
    const d = data as { text: string }
    console.log('[OMNIA Voice] Transcript received:', d.text, '| mode:', store.activationMode)
    clearSttTimeout()

    let text = d.text

    // In wake_word mode, only accept transcripts starting with the wake word
    if (store.activationMode === 'wake_word') {
      const ww = store.wakeWord.toLowerCase().trim()
      const lower = text.toLowerCase().trim()
      // Strip leading punctuation/symbols that STT may prepend (e.g. "..." or "-")
      const cleaned = lower.replace(/^[^a-zA-Z\u00C0-\u024F]+/, '')
      if (!cleaned.startsWith(ww)) {
        console.log(`[OMNIA Voice] Wake word "${ww}" not found in "${cleaned}", discarding`)
        store.isProcessing = false
        scheduleAutoRestart()
        return
      }
      // Strip the wake word prefix from the cleaned text, then recover rest
      const afterWw = cleaned.slice(ww.length).replace(/^[,.:;!?\s]+/, '').trim()
      if (!afterWw) {
        console.log('[OMNIA Voice] Only wake word spoken, no command')
        store.isProcessing = false
        scheduleAutoRestart()
        return
      }
      text = afterWw
      console.log(`[OMNIA Voice] Wake word matched, command: "${text}"`)
    }

    store.transcript = text
    store.isProcessing = false

    // Always schedule restart for continuous modes — the repeating check
    // will wait until LLM streaming and TTS finish before actually starting.
    scheduleAutoRestart()
  }
  const onSttProcessing = (): void => {
    console.log('[OMNIA Voice] STT processing...')
    store.isProcessing = true
    startSttTimeout()
  }
  const onTtsStart = (): void => { store.isSpeaking = true; ttsBackendDone = false }
  const onTtsDone = (): void => {
    ttsBackendDone = true
    audioConvertChain = Promise.resolve()
    // If the audio queue is already empty, finalise immediately.
    // Otherwise playNextChunk will call finalizeTtsPlayback when draining.
    if (!isPlayingQueue) {
      finalizeTtsPlayback()
    }
  }

  /** Reset speaking state and schedule mic restart once all audio has been played. */
  function finalizeTtsPlayback(): void {
    ttsBackendDone = false
    store.isSpeaking = false
    scheduleAutoRestart()
  }

  // Binary audio chunks arrive as Blob in browsers — convert and queue sequentially.
  let audioConvertChain: Promise<void> = Promise.resolve()
  const onBinaryAudio = (data: unknown): void => {
    audioConvertChain = audioConvertChain.then(async () => {
      const buf = data instanceof Blob ? await data.arrayBuffer() : data as ArrayBuffer
      audioQueue.push(buf)
      if (!isPlayingQueue) playNextChunk()
    }).catch((err) => {
      console.error('[OMNIA Voice] Audio convert error:', err)
    })
  }
  const onVoiceError = (data: unknown): void => {
    const d = data as { message: string }
    console.error('[OMNIA Voice] Error:', d.message)
    clearSttTimeout()
    cleanupRecordingResources()
    store.isListening = false
    store.isProcessing = false
    store.audioLevel = 0
    store.stopRecordingTimer()
    // In continuous modes, attempt recovery after an error
    scheduleAutoRestart()
  }
  const onRecordingStopped = (data: unknown): void => {
    const d = data as { empty?: boolean }
    if (d.empty) {
      clearSttTimeout()
      store.isProcessing = false
      // Empty recording — schedule restart for continuous modes
      scheduleAutoRestart()
    }
  }
  const onTtsCancelled = (): void => {
    ttsBackendDone = false
    store.isSpeaking = false
    audioQueue.length = 0
    isPlayingQueue = false
    audioConvertChain = Promise.resolve()
    scheduleAutoRestart()
  }

  // Register handlers (guarded to prevent duplicate registration on singleton)
  if (!handlersRegistered) {
    voiceWs.on('connected', onConnected)
    voiceWs.on('disconnected', onDisconnected)
    voiceWs.on('voice_ready', onVoiceReady)
    voiceWs.on('transcript', onTranscript)
    voiceWs.on('stt_processing', onSttProcessing)
    voiceWs.on('tts_start', onTtsStart)
    voiceWs.on('tts_done', onTtsDone)
    voiceWs.on('binary', onBinaryAudio)
    voiceWs.on('voice_error', onVoiceError)
    voiceWs.on('recording_stopped', onRecordingStopped)
    voiceWs.on('tts_cancelled', onTtsCancelled)
    handlersRegistered = true
  }

  // -----------------------------------------------------------------------
  // STT processing timeout
  // -----------------------------------------------------------------------

  function startSttTimeout(): void {
    clearSttTimeout()
    sttTimeoutTimer = setTimeout(() => {
      console.warn(`[OMNIA Voice] STT processing timed out after ${STT_TIMEOUT_MS / 1000}s`)
      cleanupAudioResources()
      store.isListening = false
      store.isProcessing = false
      store.audioLevel = 0
      store.stopRecordingTimer()
      scheduleAutoRestart()
    }, STT_TIMEOUT_MS)
  }

  function clearSttTimeout(): void {
    if (sttTimeoutTimer) {
      clearTimeout(sttTimeoutTimer)
      sttTimeoutTimer = null
    }
  }

  // -----------------------------------------------------------------------
  // Auto-restart (always_on / wake_word)
  // -----------------------------------------------------------------------

  let autoRestartTimer: ReturnType<typeof setTimeout> | null = null
  const AUTO_RESTART_INTERVAL_MS = 1500
  const AUTO_RESTART_INITIAL_MS = 800

  /**
   * Schedule auto-restart for continuous modes (always_on / wake_word).
   *
   * Uses REPEATING checks: if conditions aren't met yet (e.g. LLM still
   * streaming, TTS still speaking), the timer retries every 1.5 s until
   * recording can actually start.  This prevents the continuous mode from
   * stalling after tool calls, images, or errors.
   */
  function scheduleAutoRestart(): void {
    if (autoRestartTimer) return
    const mode = store.activationMode
    if (mode !== 'always_on' && mode !== 'wake_word') return

    const attempt = async (): Promise<void> => {
      autoRestartTimer = null
      // Bail out if mode changed, WS dropped, or STT gone
      const currentMode = store.activationMode
      if (currentMode !== 'always_on' && currentMode !== 'wake_word') return
      if (!voiceWs.isConnected || !store.sttAvailable) return

      // Still busy — retry later instead of giving up
      if (store.isListening || store.isProcessing || store.isSpeaking || chatStore.isStreaming) {
        autoRestartTimer = setTimeout(attempt, AUTO_RESTART_INTERVAL_MS)
        return
      }
      try {
        await startListening()
      } catch (err) {
        console.warn('[OMNIA Voice] Auto-restart failed:', err)
        // Retry even on failure (e.g. mic permission popup)
        autoRestartTimer = setTimeout(attempt, AUTO_RESTART_INTERVAL_MS)
      }
    }

    autoRestartTimer = setTimeout(attempt, AUTO_RESTART_INITIAL_MS)
  }

  function cancelAutoRestart(): void {
    if (autoRestartTimer) {
      clearTimeout(autoRestartTimer)
      autoRestartTimer = null
    }
  }

  // -----------------------------------------------------------------------
  // Audio resource cleanup (idempotent — safe to call multiple times)
  // -----------------------------------------------------------------------

  function cleanupRecordingResources(): void {
    if (levelTimer) { clearInterval(levelTimer); levelTimer = null }
    if (workletNode) { workletNode.disconnect(); workletNode = null }
    if (analyserNode) { analyserNode.disconnect(); analyserNode = null }
    if (audioContext) { audioContext.close(); audioContext = null }
    if (mediaStream) { mediaStream.getTracks().forEach((t) => t.stop()); mediaStream = null }
  }

  function cleanupPlaybackResources(): void {
    if (playbackCtx) { playbackCtx.close(); playbackCtx = null }
    audioQueue.length = 0
    isPlayingQueue = false
    ttsBackendDone = false
  }

  function cleanupAudioResources(): void {
    cleanupRecordingResources()
    cleanupPlaybackResources()
  }

  // -----------------------------------------------------------------------
  // Cancel a stuck processing state (user-initiated)
  // -----------------------------------------------------------------------

  function cancelProcessing(): void {
    console.log('[OMNIA Voice] Cancelling stuck processing state')
    clearSttTimeout()
    cleanupAudioResources()
    store.isListening = false
    store.isProcessing = false
    store.audioLevel = 0
    store.stopRecordingTimer()
  }

  // -----------------------------------------------------------------------
  // Microphone capture
  // -----------------------------------------------------------------------

  async function startListening(): Promise<void> {
    if (store.isListening) return
    if (!voiceWs.isConnected) {
      console.warn('[OMNIA Voice] Voice WS not connected, cannot start listening')
      return
    }

    console.log('[OMNIA Voice] Starting mic capture...')

    // Refresh devices to validate saved device (fallback handled inside refreshDevices)
    await refreshDevices()

    // Build audio constraints with optional device selection
    const audioConstraints: MediaTrackConstraints = {
      sampleRate: 16000,
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
    }
    if (selectedDeviceId.value) {
      audioConstraints.deviceId = { exact: selectedDeviceId.value }
    }

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints })
      micPermission.value = 'granted'
      store.micPermission = 'granted'
    } catch (err) {
      console.error('[OMNIA Voice] Mic permission denied or error:', err)
      micPermission.value = 'denied'
      store.micPermission = 'denied'
      return
    }

    // Log which device is actually being used
    const track = mediaStream.getAudioTracks()[0]
    const settings = track.getSettings()
    console.log('[OMNIA Voice] Using mic:', track.label, '| deviceId:', settings.deviceId)

    // Refresh device list now that we have permission (labels become available)
    await refreshDevices()

    audioContext = new AudioContext({ sampleRate: 16000 })
    const actualSampleRate = audioContext.sampleRate
    console.log(`[OMNIA Voice] AudioContext sampleRate: requested=16000, actual=${actualSampleRate}`)
    const source = audioContext.createMediaStreamSource(mediaStream)

    // Level analyser
    analyserNode = audioContext.createAnalyser()
    analyserNode.fftSize = 256
    source.connect(analyserNode)
    speechDetected = false
    silenceSince = null
    levelTimer = setInterval(() => {
      if (!analyserNode) return
      const buf = new Uint8Array(analyserNode.frequencyBinCount)
      analyserNode.getByteFrequencyData(buf)
      const level = buf.reduce((a, b) => a + b, 0) / buf.length / 255
      store.audioLevel = level

      // Silence-based auto-stop for continuous modes
      const mode = store.activationMode
      if (mode !== 'always_on' && mode !== 'wake_word') return
      if (!store.isListening) return

      if (level >= SPEECH_THRESHOLD) {
        speechDetected = true
        silenceSince = null
      } else if (speechDetected && level < SILENCE_THRESHOLD) {
        if (silenceSince === null) {
          silenceSince = Date.now()
        } else if (Date.now() - silenceSince >= SILENCE_TIMEOUT_MS) {
          console.log('[OMNIA Voice] Silence detected, auto-stopping recording')
          stopListening()
        }
      }
    }, 100)

    // PCM capture via AudioWorklet (loaded from inline blob URL)
    try {
      if (!workletBlobUrl) workletBlobUrl = createWorkletUrl()
      await audioContext.audioWorklet.addModule(workletBlobUrl)
    } catch (err) {
      console.error('[OMNIA Voice] AudioWorklet addModule failed:', err)
      // Cleanup on failure
      if (levelTimer) { clearInterval(levelTimer); levelTimer = null }
      analyserNode?.disconnect(); analyserNode = null
      audioContext.close(); audioContext = null
      mediaStream.getTracks().forEach((t) => t.stop()); mediaStream = null
      return
    }

    workletNode = new AudioWorkletNode(audioContext, 'pcm-processor')
    workletNode.port.onmessage = (e: MessageEvent<ArrayBuffer>): void => {
      // Backpressure handling is managed in ws.ts via bufferedAmount checks
      voiceWs.sendBinary(e.data)
    }
    source.connect(workletNode)

    // Tell backend to start recording (include actual sample rate)
    voiceWs.send({ type: 'voice_start', sample_rate: actualSampleRate })
    store.isListening = true
    store.startRecordingTimer()
    console.log('[OMNIA Voice] Recording started, streaming PCM to backend')
  }

  function stopListening(): void {
    if (!store.isListening) return
    store.isListening = false
    store.stopRecordingTimer()
    store.audioLevel = 0
    console.log('[OMNIA Voice] Stopping recording, sending voice_stop')

    // Tell backend to stop recording and process STT
    voiceWs.send({ type: 'voice_stop' })

    // Release recording resources (keep playback alive for TTS)
    cleanupRecordingResources()
  }

  // -----------------------------------------------------------------------
  // Device enumeration
  // -----------------------------------------------------------------------

  async function refreshDevices(): Promise<void> {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices()
      audioDevices.value = devices
        .filter((d) => d.kind === 'audioinput')
        .map((d) => ({ deviceId: d.deviceId, label: d.label || `Microfono (${d.deviceId.slice(0, 8)})` }))
      console.log('[OMNIA Voice] Available audio devices:', audioDevices.value)
      if (selectedDeviceId.value && !audioDevices.value.some(d => d.deviceId === selectedDeviceId.value)) {
        console.warn('[OMNIA Voice] Selected mic device disappeared from device list, resetting to default')
        selectedDeviceId.value = ''
      }
    } catch (err) {
      console.error('[OMNIA Voice] Failed to enumerate devices:', err)
    }
  }

  // -----------------------------------------------------------------------
  // TTS playback
  // -----------------------------------------------------------------------

  function speak(text: string): void {
    if (!voiceWs.isConnected) return
    // Set isSpeaking immediately to close the timing gap between calling
    // speak() and receiving the backend's tts_start event.  Without this,
    // scheduleAutoRestart can start recording in that window.
    store.isSpeaking = true
    voiceWs.send({ type: 'tts_speak', text })
  }

  function cancelSpeak(): void {
    voiceWs.send({ type: 'tts_cancel' })
    // Stop the currently playing audio by closing the playback context.
    // This immediately silences any AudioBufferSourceNode in flight.
    if (playbackCtx) {
      playbackCtx.close().catch(() => { /* already closed */ })
      playbackCtx = null
    }
    audioQueue.length = 0
    isPlayingQueue = false
    ttsBackendDone = false
    audioConvertChain = Promise.resolve()
    store.isSpeaking = false
  }

  async function playNextChunk(): Promise<void> {
    if (audioQueue.length === 0) {
      isPlayingQueue = false
      // Backend already signalled tts_done — now the queue is drained.
      if (ttsBackendDone) finalizeTtsPlayback()
      return
    }
    isPlayingQueue = true
    if (!playbackCtx) playbackCtx = new AudioContext({ sampleRate: ttsSampleRate })
    const chunk = audioQueue.shift()!
    try {
      const buf = await playbackCtx.decodeAudioData(chunk.slice(0))
      const src = playbackCtx.createBufferSource()
      src.buffer = buf
      src.connect(playbackCtx.destination)
      src.onended = () => playNextChunk()
      src.start()
    } catch (err) {
      console.warn('[OMNIA Voice] Failed to decode audio chunk:', err)
      setTimeout(() => playNextChunk(), 0)
    }
  }

  // -----------------------------------------------------------------------
  // Connection helpers
  // -----------------------------------------------------------------------

  function connect(): void {
    voiceWs.connect()
    // Enumerate devices on connect (may need mic permission first for labels)
    void refreshDevices()
  }
  function disconnect(): void {
    clearSttTimeout()
    cancelAutoRestart()
    if (sttRetryTimer) { clearTimeout(sttRetryTimer); sttRetryTimer = null }
    stopListening()
    cancelSpeak()
    voiceWs.disconnect()
    cleanupAudioResources()
    if (playbackCtx) { playbackCtx.close(); playbackCtx = null }
    audioQueue.length = 0
    isPlayingQueue = false
    if (workletBlobUrl) { URL.revokeObjectURL(workletBlobUrl); workletBlobUrl = null }
  }

  // -----------------------------------------------------------------------
  // Cleanup
  // -----------------------------------------------------------------------

  onScopeDispose(() => {
    disconnect()
    voiceWs.off('connected', onConnected)
    voiceWs.off('disconnected', onDisconnected)
    voiceWs.off('voice_ready', onVoiceReady)
    voiceWs.off('transcript', onTranscript)
    voiceWs.off('stt_processing', onSttProcessing)
    voiceWs.off('tts_start', onTtsStart)
    voiceWs.off('tts_done', onTtsDone)
    voiceWs.off('binary', onBinaryAudio)
    voiceWs.off('voice_error', onVoiceError)
    voiceWs.off('recording_stopped', onRecordingStopped)
    voiceWs.off('tts_cancelled', onTtsCancelled)
    handlersRegistered = false
  })

  return {
    isListening: computed(() => store.isListening),
    isProcessing: computed(() => store.isProcessing),
    isSpeaking: computed(() => store.isSpeaking),
    transcript: computed(() => store.transcript),
    audioLevel: computed(() => store.audioLevel),
    voiceAvailable: computed(() => voiceAvailable.value),
    micPermission: computed(() => micPermission.value),
    isConnected: computed(() => isConnected.value),
    audioDevices,
    selectedDeviceId,
    startListening,
    stopListening,
    cancelProcessing,
    speak,
    cancelSpeak,
    connect,
    disconnect,
    refreshDevices,
  }
}
