<script setup lang="ts">
/**
 * AudioPlayback.vue — TTS audio playback manager.
 *
 * Receives audio chunks from WebSocket, queues them,
 * and plays them sequentially using the Web Audio API.
 * Shows a minimal playback control when audio is playing.
 */
import { onBeforeUnmount, ref } from 'vue'
import { useVoiceStore } from '../../stores/voice'

const store = useVoiceStore()

const props = defineProps<{
  /** Sample rate of incoming audio (from backend TTS config). */
  sampleRate: number
}>()

const emit = defineEmits<{
  /** Fired when user cancels playback. */
  cancel: []
}>()

// -- Audio state --
let audioContext: AudioContext | null = null
let currentSource: AudioBufferSourceNode | null = null
const isPlaying = ref(false)
const audioQueue = ref<ArrayBuffer[]>([])

/** Enqueue an audio chunk for playback. */
function enqueueChunk(chunk: ArrayBuffer): void {
  audioQueue.value.push(chunk)
  if (!isPlaying.value) {
    playNext()
  }
}

/** Play the next chunk from the queue. */
async function playNext(): Promise<void> {
  if (audioQueue.value.length === 0) {
    isPlaying.value = false
    store.isSpeaking = false
    return
  }

  if (!audioContext) {
    audioContext = new AudioContext({ sampleRate: props.sampleRate })
  }

  if (audioContext.state === 'suspended') {
    await audioContext.resume()
  }

  isPlaying.value = true
  store.isSpeaking = true
  const chunk = audioQueue.value.shift()!

  try {
    const buffer = await audioContext.decodeAudioData(chunk.slice(0))
    currentSource = audioContext.createBufferSource()
    currentSource.buffer = buffer
    currentSource.connect(audioContext.destination)
    currentSource.onended = () => {
      currentSource = null
      playNext()
    }
    currentSource.start()
  } catch (err) {
    console.error('[AudioPlayback] decode error:', err)
    playNext()
  }
}

/** Stop all playback and clear the queue. */
function cancelPlayback(): void {
  audioQueue.value = []
  if (currentSource) {
    currentSource.stop()
    currentSource = null
  }
  isPlaying.value = false
  store.isSpeaking = false
  emit('cancel')
}

/** Cleanup on unmount. */
onBeforeUnmount(() => {
  cancelPlayback()
  if (audioContext) {
    audioContext.close()
    audioContext = null
  }
})

// Expose for parent
defineExpose({ enqueueChunk, cancelPlayback })
</script>

<template>
  <Transition name="fade">
    <div v-if="isPlaying" class="ap" role="status" aria-label="Riproduzione audio TTS">
      <!-- Speaking icon -->
      <svg class="ap__icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
        <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
        <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
      </svg>
      <span class="ap__label">TTS</span>
      <!-- Cancel button -->
      <button class="ap__cancel" aria-label="Interrompi audio" @click="cancelPlayback">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
          stroke-linecap="round">
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  </Transition>
</template>

<style scoped>
.ap {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-pill);
  background: var(--speaking-dim);
  color: var(--speaking);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
}

.ap__icon {
  flex-shrink: 0;
}

.ap__label {
  letter-spacing: 0.02em;
}

.ap__cancel {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--surface-hover);
  color: inherit;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.ap__cancel:hover {
  background: var(--surface-active);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity var(--transition-fast);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
