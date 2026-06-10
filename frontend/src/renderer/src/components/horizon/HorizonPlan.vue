<script setup lang="ts">
/**
 * HorizonPlan — the below-line half of the mission-control: notch labels
 * aligned with the canvas ticks (shared notchPositions), the step counter,
 * and the ephemeral tool annotation. The above-line status sentence is
 * rendered by the view (it lives in the upper zone).
 */
import { computed } from 'vue'
import { notchPositions } from '../../composables/horizon/horizonScene'
import type { TaskStep } from '../../types/tasks'

const props = defineProps<{
  steps: TaskStep[]
  activeIndex: number
  completed: number
  /** Ephemeral tool-call annotation ('' = hidden). */
  annotation: string
}>()

const positions = computed(() => notchPositions(props.steps.length))

/** Short label per notch (first 2 words, ellipsized). */
function shortLabel(step: TaskStep): string {
  const words = step.step.split(/\s+/)
  return words.length <= 2 ? step.step : `${words.slice(0, 2).join(' ')}…`
}
</script>

<template>
  <div class="hz-plan">
    <div class="hz-plan__labels">
      <span
        v-for="(s, i) in steps"
        :key="i"
        class="hz-plan__label"
        :class="{
          'hz-plan__label--active': i === activeIndex,
          'hz-plan__label--done': s.status === 'completed'
        }"
        :style="{ left: `${positions[i] * 100}%` }"
        :title="s.step"
      >
        {{ shortLabel(s) }}
      </span>
    </div>
    <p class="hz-plan__counter">{{ completed }} DI {{ steps.length }}</p>
    <Transition name="hz-soft">
      <p v-if="annotation" class="hz-plan__annotation">{{ annotation }}</p>
    </Transition>
  </div>
</template>

<style scoped>
.hz-plan {
  width: 100%;
  text-align: center;
}

/* Labels share the canvas geometry: same 6% horizontal margin. */
.hz-plan__labels {
  position: relative;
  height: 18px;
  margin: 6px 6% 0;
}

.hz-plan__label {
  position: absolute;
  transform: translateX(-50%);
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
  white-space: nowrap;
  transition: color var(--hz-fade) ease;
}

.hz-plan__label--active {
  color: var(--hz-gold);
}

.hz-plan__label--done {
  opacity: 0.45;
}

.hz-plan__counter {
  margin: var(--space-2) 0 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: var(--hz-ink-faint);
}

.hz-plan__annotation {
  margin: var(--space-1) 0 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.18em;
  color: var(--hz-ink-dim);
}

.hz-soft-enter-active,
.hz-soft-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-soft-enter-from,
.hz-soft-leave-to {
  opacity: 0;
}
</style>
