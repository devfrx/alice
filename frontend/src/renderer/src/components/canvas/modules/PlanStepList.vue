<script setup lang="ts">
/**
 * PlanStepList — Pure presentational checklist of plan steps.
 *
 * Renders an ordered list of {@link PlanStep}s with a status-aware leading
 * mark: a check for `completed`, a pulsing dot for `in_progress`, and a plain
 * muted dot for `pending`. Visual language mirrors the inline plan checklist
 * in {@link ToolExecutionIndicator}.
 *
 * Stateless: no store, no fetch. The empty case is rendered as an empty list;
 * the caller decides whether to show this component or an empty state instead.
 */
import AppIcon from '../../ui/AppIcon.vue'
import type { PlanStep } from '../../../types/plan'

defineProps<{
  /** Ordered plan steps to render. */
  steps: PlanStep[]
}>()
</script>

<template>
  <ul class="plan-steps" role="list">
    <li
      v-for="(s, i) in steps"
      :key="i"
      class="plan-steps__item"
      :class="`plan-steps__item--${s.status}`"
    >
      <span class="plan-steps__mark">
        <AppIcon
          v-if="s.status === 'completed'"
          name="check"
          :size="13"
          :stroke-width="2.5"
        />
        <span
          v-else
          class="plan-steps__dot"
          :class="{ 'plan-steps__dot--active': s.status === 'in_progress' }"
        />
      </span>
      <span class="plan-steps__text">{{ s.step }}</span>
    </li>
  </ul>
</template>

<style scoped>
.plan-steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.plan-steps__item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: var(--leading-snug, 1.4);
  color: var(--text-secondary);
}

.plan-steps__mark {
  width: 14px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--success);
}

.plan-steps__dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  border: 1.5px solid var(--text-muted);
  box-sizing: border-box;
}

.plan-steps__dot--active {
  border-color: var(--accent);
  background: var(--accent);
  animation: planDotPulse 1.4s ease-in-out infinite;
}

.plan-steps__item--completed .plan-steps__text {
  color: var(--text-muted);
  text-decoration: line-through;
}

.plan-steps__item--in_progress .plan-steps__text {
  color: var(--text-primary);
  font-weight: var(--weight-medium);
}

@keyframes planDotPulse {
  0%,
  100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .plan-steps__dot--active {
    animation: none;
  }
}
</style>
