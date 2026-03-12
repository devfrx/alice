<script setup lang="ts">
/**
 * VoiceIndicator.vue — Audio level visualization (bars or waveform).
 *
 * Shows animated bars that respond to the current audio input level.
 * Used during recording to give visual feedback that the mic is active.
 */
import { computed } from 'vue'

const props = defineProps<{
  /** Audio input level 0-1. */
  level: number
  /** Current voice state. */
  state: 'idle' | 'recording' | 'processing' | 'speaking'
}>()

const barCount = 5
const bars = computed(() => {
  return Array.from({ length: barCount }, (_, i) => {
    const threshold = (i + 1) / (barCount + 1)
    const height = props.state === 'recording'
      ? Math.max(0.15, Math.min(1, props.level * 1.5 - threshold + 0.5))
      : props.state === 'speaking'
        ? 0.3 + 0.1 * ((i + 1) / barCount)
        : 0.15
    return { height: `${height * 100}%` }
  })
})

const stateLabel = computed(() => {
  switch (props.state) {
    case 'recording': return 'In ascolto...'
    case 'processing': return 'Elaborazione...'
    case 'speaking': return 'Parlando...'
    default: return ''
  }
})

const stateClass = computed(() => `vi--${props.state}`)
</script>

<template>
  <div v-if="state !== 'idle'" class="vi" :class="stateClass" role="status" :aria-label="stateLabel">
    <div class="vi__bars">
      <span v-for="(bar, index) in bars" :key="index" class="vi__bar" :style="{ height: bar.height }" />
    </div>
    <span class="vi__label">{{ stateLabel }}</span>
  </div>
</template>

<style scoped>
.vi {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2-5);
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--surface-hover);
  transition: background var(--transition-fast), color var(--transition-fast);
}

.vi--recording {
  background: var(--listening-dim);
  color: var(--listening);
}

.vi--processing {
  background: var(--thinking-dim);
  color: var(--thinking);
}

.vi--speaking {
  background: var(--speaking-dim);
  color: var(--speaking);
}

.vi__bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 16px;
}

.vi__bar {
  width: 3px;
  min-height: 2px;
  border-radius: 1.5px;
  background: currentColor;
  transition: height 0.1s ease;
}

.vi--speaking .vi__bar {
  animation: speak-pulse 0.6s ease-in-out infinite alternate;
}

.vi--speaking .vi__bar:nth-child(2) {
  animation-delay: 0.1s;
}

.vi--speaking .vi__bar:nth-child(3) {
  animation-delay: 0.2s;
}

.vi--speaking .vi__bar:nth-child(4) {
  animation-delay: 0.3s;
}

.vi--speaking .vi__bar:nth-child(5) {
  animation-delay: 0.4s;
}

@keyframes speak-pulse {
  from {
    height: 30%;
  }

  to {
    height: 70%;
  }
}

.vi__label {
  white-space: nowrap;
  font-weight: var(--weight-medium);
  letter-spacing: 0.02em;
}
</style>
