<script setup lang="ts">
/**
 * HorizonPlan — the manuscript: the whole plan as a readable vertical list
 * under the line, tethered to it by a dendrite. Steps reveal one by one when
 * the plan is born (staggered via --row), the active step carries a breathing
 * gold node, completed ones are struck through in gold ink. Long plans
 * collapse via the pure manuscriptView (oldest completed → counter row,
 * far future → "+N" tail).
 */
import { computed } from 'vue'
import { manuscriptView } from '../../composables/horizon/horizonScene'
import type { TaskStep } from '../../types/tasks'

const props = defineProps<{
  steps: TaskStep[]
  activeIndex: number
  completed: number
  /** Ephemeral tool-call annotation ('' = hidden). */
  annotation: string
}>()

const items = computed(() => manuscriptView(props.steps, 7, props.activeIndex))
</script>

<template>
  <div class="hz-plan">
    <span class="hz-plan__tether" aria-hidden="true" />
    <TransitionGroup
      tag="ol"
      name="hz-plan-step"
      class="hz-plan__list"
      appear
      appear-active-class="hz-plan-step-appear-active"
    >
      <li
        v-for="(it, row) in items"
        :key="it.kind === 'step' ? `s-${it.index}` : it.kind"
        class="hz-plan__row"
        :class="{
          'hz-plan__row--active': it.kind === 'step' && it.index === activeIndex,
          'hz-plan__row--done': it.kind === 'step' && it.step.status === 'completed',
          'hz-plan__row--meta': it.kind !== 'step'
        }"
        :style="{ '--row': row }"
        :aria-current="it.kind === 'step' && it.index === activeIndex ? 'step' : undefined"
      >
        <template v-if="it.kind === 'step'">
          <span class="hz-plan__marker" aria-hidden="true" />
          <span class="hz-plan__text">{{ it.step.step }}</span>
          <span v-if="it.step.status === 'completed'" class="hz-plan__check" aria-hidden="true">
            ✓
          </span>
        </template>
        <template v-else-if="it.kind === 'collapsed'">{{ it.count }} completati ✓</template>
        <template v-else>+{{ it.count }} passi</template>
      </li>
    </TransitionGroup>
    <p class="hz-plan__counter">{{ completed }} DI {{ steps.length }}</p>
    <Transition name="hz-soft">
      <p v-if="annotation" class="hz-plan__annotation">{{ annotation }}</p>
    </Transition>
  </div>
</template>

<style scoped>
.hz-plan {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  text-align: center;
}

/* Dendrite tethering the manuscript to the scene above. */
.hz-plan__tether {
  width: 1px;
  height: clamp(12px, 2.4vh, 22px);
  background: linear-gradient(rgba(var(--hz-line-rgb), 0.5), transparent);
}

.hz-plan__list {
  position: relative;
  list-style: none;
  margin: clamp(4px, 1vh, 10px) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: clamp(5px, 1vh, 9px);
  max-width: min(64ch, 86%);
}

.hz-plan__row {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: clamp(13px, 1.7vmin, 17px);
  color: var(--hz-ink-faint);
  transition:
    color var(--hz-fade) ease,
    opacity var(--hz-fade) ease,
    font-size var(--hz-fade) ease;
}

.hz-plan__marker {
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  border: 1px solid var(--hz-ink-faint);
  background: transparent;
  align-self: center;
  transition:
    background var(--hz-fade) ease,
    border-color var(--hz-fade) ease;
}

.hz-plan__text {
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.hz-plan__row--active {
  color: var(--hz-ink);
  font-size: clamp(15px, 2vmin, 19px);
}

.hz-plan__row--active .hz-plan__marker {
  border-color: transparent;
  background: var(--hz-gold);
  animation: hz-plan-node 2.4s ease-in-out infinite;
}

.hz-plan__row--done {
  opacity: 0.55;
}

.hz-plan__row--done .hz-plan__text {
  font-style: italic;
  text-decoration: line-through;
  text-decoration-color: rgba(var(--hz-line-rgb), 0.6);
  text-decoration-thickness: 0.5px;
}

.hz-plan__row--done .hz-plan__marker {
  border-color: transparent;
  background: rgba(var(--hz-line-rgb), 0.55);
}

.hz-plan__check {
  flex: none;
  font-family: var(--hz-serif);
  font-size: 0.8em;
  color: var(--hz-gold);
}

.hz-plan__row--meta {
  font-style: italic;
  font-size: clamp(11px, 1.4vmin, 14px);
  color: var(--hz-ink-faint);
}

@keyframes hz-plan-node {
  0%,
  100% {
    box-shadow: 0 0 4px rgba(var(--hz-line-rgb), 0.4);
  }
  50% {
    box-shadow: 0 0 10px rgba(var(--hz-line-rgb), 0.9);
  }
}

/* Staggered reveal on the plan's FIRST appearance only: each row waits for
   the previous one (80ms). Mid-run enters (late-added steps) use the plain
   delay-free fade below. */
.hz-plan-step-appear-active {
  transition:
    opacity 480ms var(--ease-out),
    transform 480ms var(--ease-out);
  transition-delay: calc(var(--row) * 80ms);
}

.hz-plan-step-enter-active {
  transition:
    opacity 480ms var(--ease-out),
    transform 480ms var(--ease-out);
}

.hz-plan-step-leave-active {
  transition: opacity 200ms var(--ease-out);
  position: absolute; /* leaving rows don't push the list around */
  max-width: 100%;
}

.hz-plan-step-move {
  transition:
    transform 320ms var(--ease-out),
    color var(--hz-fade) ease,
    opacity var(--hz-fade) ease;
}

.hz-plan-step-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.hz-plan-step-leave-to {
  opacity: 0;
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

@media (prefers-reduced-motion: reduce) {
  .hz-plan__row--active .hz-plan__marker {
    animation: none;
  }

  .hz-plan-step-appear-active,
  .hz-plan-step-enter-active,
  .hz-plan-step-leave-active,
  .hz-plan-step-move {
    transition: none;
  }
}
</style>
