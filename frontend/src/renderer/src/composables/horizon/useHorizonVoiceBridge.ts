// composables/horizon/useHorizonVoiceBridge.ts
/**
 * useHorizonVoiceBridge — voice wiring salvaged from the monolithic
 * HorizonView: STT transcript routing (auto-send vs confirm-in-composer)
 * and TTS auto-speak when a stream completes.
 */
import { watch } from 'vue'
import { useChatStore } from '../../stores/chat'
import { useVoiceStore } from '../../stores/voice'

export interface HorizonVoiceBridgeDeps {
  send: (
    content: string,
    conversationId?: string,
    files?: File[],
    opts?: { source?: 'text' | 'voice' }
  ) => Promise<unknown>
  /** Materialize the composer pre-seeded with the transcript. */
  activateComposer: (seed: string) => void
  speak: (text: string) => void
}

export function useHorizonVoiceBridge(deps: HorizonVoiceBridgeDeps): void {
  const chatStore = useChatStore()
  const voiceStore = useVoiceStore()

  // STT transcript: auto-send by default; with "Conferma trascrizione" on,
  // the transcript lands in the composer instead.
  watch(
    () => voiceStore.transcript,
    (text) => {
      if (!text.trim()) return
      const spoken = text.trim()
      voiceStore.clearTranscript()
      if (voiceStore.confirmTranscript) {
        deps.activateComposer(spoken)
      } else {
        deps.send(spoken, undefined, undefined, { source: 'voice' }).catch(console.error)
      }
    }
  )

  // TTS auto-speak when streaming completes.
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
      if (allContent) deps.speak(allContent)
    }
  )
}
