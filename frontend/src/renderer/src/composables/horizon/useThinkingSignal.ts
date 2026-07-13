// composables/horizon/useThinkingSignal.ts
/**
 * useThinkingSignal — bridges the chat store's raw streaming buffers to the
 * scene's "Alice is reasoning right now" boolean. All the edge logic lives in
 * the pure, unit-tested thinkingSignalNext reducer; this wrapper only feeds
 * it store snapshots.
 */
import { ref, watch } from 'vue'
import type { Ref } from 'vue'
import { THINKING_SIGNAL_IDLE, thinkingSignalNext } from './horizonScene'
import type { ThinkingSignalState } from './horizonScene'
import { useChatStore } from '../../stores/chat'

export function useThinkingSignal(): Ref<boolean> {
  const chatStore = useChatStore()
  const active = ref(false)
  let state: ThinkingSignalState = { ...THINKING_SIGNAL_IDLE }

  watch(
    () =>
      [
        chatStore.currentThinkingContent.length,
        chatStore.currentStreamContent.length,
        chatStore.isStreamingCurrentConversation
      ] as const,
    ([thinkingLen, contentLen, isStreaming]) => {
      state = thinkingSignalNext(state, { thinkingLen, contentLen, isStreaming })
      active.value = state.active
    },
    { immediate: true }
  )

  return active
}
