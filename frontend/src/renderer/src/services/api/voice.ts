/** Voice service endpoints (`/api/voice`, `/api/settings/voice`). */
import { request } from './http'

export const voiceApi = {
  /** Get voice service status (STT/TTS availability). */
  getVoiceStatus: (): Promise<{
    stt_available: boolean
    tts_available: boolean
    active_connections: number
  }> =>
    request<{ stt_available: boolean; tts_available: boolean; active_connections: number }>(
      '/voice/status'
    ),

  /** Probe which TTS/STT engine libraries are installed on the backend. */
  getAvailableVoiceEngines: (): Promise<{
    tts: Record<string, boolean>
    stt: Record<string, boolean>
  }> =>
    request<{ tts: Record<string, boolean>; stt: Record<string, boolean> }>(
      '/settings/voice/available-engines'
    )
}
