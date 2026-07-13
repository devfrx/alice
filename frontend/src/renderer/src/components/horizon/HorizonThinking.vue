<!-- components/horizon/HorizonThinking.vue -->
<script setup lang="ts">
/**
 * HorizonThinking — the reasoning marginalia above the line: the last
 * meaningful line of the thinking stream, throttled (~600ms) and cross-faded
 * so tokens never flicker. Real text (aria-live); the dendrites growing from
 * the line toward the text are decorative SVG only.
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import { lastThinkingLine } from '../../composables/horizon/horizonScene'

const props = defineProps<{
  /** Raw accumulated thinking stream (chat store). */
  content: string
}>()

const THROTTLE_MS = 600

const shown = ref(lastThinkingLine(props.content))
let timer: ReturnType<typeof setTimeout> | null = null
let lastFlip = 0

watch(
  () => props.content,
  (content) => {
    const line = lastThinkingLine(content)
    if (line === '' || line === shown.value) return
    const wait = Math.max(0, THROTTLE_MS - (Date.now() - lastFlip))
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      shown.value = lastThinkingLine(props.content)
      lastFlip = Date.now()
    }, wait)
  }
)

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="hz-thinking">
    <Transition name="hz-think" mode="out-in">
      <p :key="shown" class="hz-thinking__line" aria-live="polite">
        sta ragionando — <em>«{{ shown }}»</em>
      </p>
    </Transition>
    <svg class="hz-thinking__dendrites" viewBox="0 0 120 24" aria-hidden="true">
      <path d="M60,24 C58,15 52,12 49,4" />
      <path d="M60,24 C63,16 69,13 73,7" />
      <path d="M60,24 C60,18 57,16 55,13" />
    </svg>
  </div>
</template>

<style scoped>
.hz-thinking {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  margin-bottom: clamp(8px, 1.6vh, 18px);
  max-width: min(70ch, 84%);
}

.hz-thinking__line {
  margin: 0;
  font-family: var(--hz-serif);
  font-style: italic;
  font-weight: 300;
  font-size: clamp(13px, 1.6vmin, 16px);
  color: var(--hz-ink-dim);
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.hz-thinking__line em {
  color: var(--hz-ink-faint);
}

/* Dendrites growing from the line toward the thought. */
.hz-thinking__dendrites {
  width: 120px;
  height: 24px;
}

.hz-thinking__dendrites path {
  fill: none;
  stroke: rgba(var(--hz-line-rgb), 0.4);
  stroke-width: 0.7;
  stroke-dasharray: 40;
  stroke-dashoffset: 40;
  animation: hz-dendrite 2.4s var(--ease-out) forwards;
}

.hz-thinking__dendrites path:nth-child(2) {
  animation-delay: 0.5s;
}

.hz-thinking__dendrites path:nth-child(3) {
  animation-delay: 1s;
}

@keyframes hz-dendrite {
  to {
    stroke-dashoffset: 0;
  }
}

.hz-think-enter-active,
.hz-think-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-think-enter-from,
.hz-think-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .hz-thinking__dendrites path {
    animation: none;
    stroke-dashoffset: 0;
  }

  .hz-think-enter-active,
  .hz-think-leave-active {
    transition: none;
  }
}
</style>
