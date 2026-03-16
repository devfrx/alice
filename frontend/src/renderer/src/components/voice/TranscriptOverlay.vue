<script setup lang="ts">
/**
 * TranscriptOverlay.vue — Live STT transcript display.
 *
 * Shows the current transcript text as a floating overlay
 * when the user is speaking or when STT is processing.
 * Auto-hides after the transcript is consumed.
 */
import { computed } from 'vue'

const props = defineProps<{
  /** The current transcript text from STT. */
  text: string
  /** Whether STT is currently processing. */
  isProcessing: boolean
  /** Whether currently recording. */
  isRecording: boolean
  /** Audio level 0-1 from the microphone. */
  audioLevel: number
  /** Formatted recording duration (e.g. "0:05"). */
  duration: string
  /** If true, transcript is auto-sent (no Invia/Annulla shown). */
  autoSend: boolean
}>()

const emit = defineEmits<{
  /** Fired when user clicks to send the transcript as a message. */
  send: [text: string]
  /** Fired when user dismisses the transcript. */
  dismiss: []
}>()

const barCount = 5
const bars = computed(() => {
  if (!props.isRecording) return Array(barCount).fill('15%')
  return Array.from({ length: barCount }, (_, i) => {
    const threshold = (i + 1) / (barCount + 1)
    const height = Math.max(0.15, Math.min(1, props.audioLevel * 1.5 - threshold + 0.5))
    return `${height * 100}%`
  })
})

const visible = computed(() => {
  return props.isRecording || props.isProcessing || (props.text.length > 0 && !props.autoSend)
})

function handleSend(): void {
  if (props.text.trim()) {
    emit('send', props.text.trim())
  }
}

function handleDismiss(): void {
  emit('dismiss')
}
</script>

<template>
  <Transition name="slide-up">
    <div v-if="visible" class="to" role="status" aria-live="polite">
      <!-- Recording indicator -->
      <div v-if="isRecording && !text" class="to__recording">
        <span class="to__dot" />
        <div class="to__bars">
          <span v-for="(h, i) in bars" :key="i" class="to__bar" :style="{ height: h }" />
        </div>
        <span class="to__label">In ascolto...</span>
        <span class="to__duration">{{ duration }}</span>
      </div>

      <!-- Processing indicator -->
      <div v-else-if="isProcessing && !text" class="to__processing">
        <span class="to__spinner" />
        <span>Trascrizione in corso...</span>
      </div>

      <!-- Transcript text -->
      <div v-else-if="text" class="to__result">
        <p class="to__text">{{ text }}</p>
        <div class="to__actions">
          <button class="to__btn to__btn--send" aria-label="Invia come messaggio" @click="handleSend">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
            Invia
          </button>
          <button class="to__btn to__btn--dismiss" aria-label="Annulla" @click="handleDismiss">
            Annulla
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.to {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin-bottom: 10px;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background: var(--glass-bg);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-md);
  z-index: var(--z-sticky);
}

.to__recording,
.to__processing {
  display: flex;
  align-items: center;
  gap: var(--space-2-5);
  font-size: var(--text-base);
  color: var(--text-secondary);
}

.to__recording {
  color: var(--listening);
}

.to__bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 18px;
}

.to__bar {
  width: 3px;
  min-height: 3px;
  border-radius: 1.5px;
  background: currentColor;
  transition: height 0.08s ease;
}

.to__label {
  flex: 1;
  letter-spacing: 0.02em;
}

.to__duration {
  font-variant-numeric: tabular-nums;
  font-size: var(--text-sm);
  opacity: var(--opacity-soft);
  font-weight: var(--weight-medium);
}

.to__dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--listening);
  animation: dotPulse 1.2s ease-in-out infinite;
}

.to__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--thinking-dim);
  border-top-color: var(--accent);
  border-radius: var(--radius-full);
  animation: spin 0.8s linear infinite;
}

.to__result {
  display: flex;
  flex-direction: column;
  gap: var(--space-2-5);
}

.to__text {
  margin: 0;
  font-size: var(--text-md);
  color: var(--text-primary);
  line-height: var(--leading-relaxed);
  animation: textReveal var(--duration-moderate) ease both;
}

.to__actions {
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
}

.to__btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1-5) var(--space-3);
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition: background var(--transition-fast);
  letter-spacing: 0.02em;
}

.to__btn--send {
  background: var(--accent);
  color: var(--surface-0);
}

.to__btn--send:hover {
  background: var(--accent-hover);
}

.to__btn--dismiss {
  background: var(--surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}

.to__btn--dismiss:hover {
  background: var(--surface-active);
  border-color: var(--border-hover);
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all var(--duration-normal) var(--ease-smooth);
}

.slide-up-enter-from {
  opacity: 0;
  transform: translateY(12px) scale(0.97);
}

.slide-up-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.97);
}

@keyframes dotPulse {

  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.3;
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes textReveal {
  from {
    opacity: 0;
    transform: translateY(4px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {

  .to__dot,
  .to__spinner {
    animation: none;
  }

  .to__text {
    animation: none;
  }
}
</style>
