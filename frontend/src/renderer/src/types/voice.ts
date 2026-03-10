/** Voice-related types for STT, TTS, and audio streaming. */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** Full voice state tracked by the voice store. */
export interface VoiceState {
  /** Whether the microphone is currently recording. */
  isListening: boolean
  /** Whether STT is processing audio. */
  isProcessing: boolean
  /** Whether TTS is playing audio. */
  isSpeaking: boolean
  /** The latest transcript from STT. */
  transcript: string
  /** Microphone input level (0-1). */
  audioLevel: number
  /** Whether voice services are enabled in config. */
  enabled: boolean
  /** Microphone permission status. */
  micPermission: 'granted' | 'denied' | 'prompt'
  /** Voice WebSocket connection status. */
  connected: boolean
  /** Recording duration in seconds. */
  recordingDuration: number
}

// ---------------------------------------------------------------------------
// Audio
// ---------------------------------------------------------------------------

/** A chunk of audio data for streaming. */
export interface AudioChunk {
  /** Raw audio bytes. */
  data: ArrayBuffer
  /** Sample rate in Hz. */
  sampleRate: number
  /** Timestamp in milliseconds. */
  timestamp: number
}

// ---------------------------------------------------------------------------
// STT
// ---------------------------------------------------------------------------

/** Configuration for speech-to-text (matches GET /api/config → stt). */
export interface STTConfig {
  enabled: boolean
  engine: string
  model: string
  language: string | null
  device: string
}

/** Result from STT transcription. */
export interface STTResult {
  /** Transcribed text. */
  text: string
  /** Detected language code. */
  language: string
  /** Confidence score (0.0–1.0, derived from model log-probabilities). */
  confidence: number
  /** Audio duration in seconds. */
  duration_s: number
  /** Whether this is a final result (vs. partial). */
  isFinal?: boolean
}

// ---------------------------------------------------------------------------
// TTS
// ---------------------------------------------------------------------------

/** Configuration for text-to-speech (matches GET /api/config → tts). */
export interface TTSConfig {
  enabled: boolean
  engine: 'piper' | 'xtts' | 'kokoro'
  voice: string
  speed: number
  sample_rate: number
  kokoro_model: string
  kokoro_voices: string
  kokoro_voice: string
  kokoro_language: string
}

// ---------------------------------------------------------------------------
// Voice WebSocket Messages
// ---------------------------------------------------------------------------

/** Client → Server: start recording. */
export interface VoiceStartMessage {
  type: 'voice_start'
  sample_rate?: number
}

/** Client → Server: stop recording. */
export interface VoiceStopMessage {
  type: 'voice_stop'
}

/** Client → Server: request TTS synthesis. */
export interface TTSSpeakMessage {
  type: 'tts_speak'
  text: string
}

/** Client → Server: cancel TTS playback. */
export interface TTSCancelMessage {
  type: 'tts_cancel'
}

/** Server → Client: voice ready status. */
export interface VoiceReadyMessage {
  type: 'voice_ready'
  stt_available: boolean
  tts_available: boolean
  stt_model?: string | null
  stt_engine?: string | null
  tts_engine?: string | null
  sample_rate?: number | null
  activation_mode?: string
  wake_word?: string
  auto_tts_response?: boolean
}

/** Server → Client: recording started acknowledgment. */
export interface RecordingStartedMessage {
  type: 'recording_started'
}

/** Server → Client: recording stopped, possibly empty. */
export interface RecordingStoppedMessage {
  type: 'recording_stopped'
  empty: boolean
}

/** Server → Client: STT is processing. */
export interface STTProcessingMessage {
  type: 'stt_processing'
}

/** Server → Client: transcription result. */
export interface TranscriptMessage {
  type: 'transcript'
  text: string
  language: string
  confidence: number
  duration_s: number
}

/** Server → Client: TTS synthesis started. */
export interface TTSStartMessage {
  type: 'tts_start'
}

/** Server → Client: TTS synthesis complete. */
export interface TTSDoneMessage {
  type: 'tts_done'
}

/** Server → Client: TTS cancelled. */
export interface TTSCancelledMessage {
  type: 'tts_cancelled'
}

/** Server → Client: voice error. */
export interface VoiceErrorMessage {
  type: 'voice_error'
  message: string
}

/** Server → Client: pong response to a ping. */
export interface VoicePongMessage {
  type: 'pong'
}

/** Union of all voice WS messages from server. */
export type VoiceServerMessage =
  | VoiceReadyMessage
  | RecordingStartedMessage
  | RecordingStoppedMessage
  | STTProcessingMessage
  | TranscriptMessage
  | TTSStartMessage
  | TTSDoneMessage
  | TTSCancelledMessage
  | VoiceErrorMessage
  | VoicePongMessage

/** Union of all voice WS messages from client. */
export type VoiceClientMessage =
  | VoiceStartMessage
  | VoiceStopMessage
  | TTSSpeakMessage
  | TTSCancelMessage

// ---------------------------------------------------------------------------
// Voice status (REST)
// ---------------------------------------------------------------------------

/** Response from GET /api/voice/status */
export interface VoiceStatusResponse {
  stt_available: boolean
  tts_available: boolean
  active_connections: number
}
