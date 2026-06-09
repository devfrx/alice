<script setup lang="ts">
/**
 * TaskStepList — Pure presentational checklist of task steps.
 *
 * Renders an ordered list of {@link TaskStep}s with a status-aware leading
 * mark: a `--success` check for `completed` (text struck through), a pulsing
 * `--accent` dot for `in_progress`, and a muted ring for `pending`. The visual
 * language mirrors the inline plan-checklist used in the canvas
 * ({@link PlanStepList}) so the Tasks strip reads consistently across surfaces.
 *
 * Stateless: no store, no fetch. The caller (TaskStrip) decides whether to show
 * this component or an empty state instead; an empty `steps` renders an empty
 * list. Motion respects `prefers-reduced-motion`.
 */
import AppIcon from '../ui/AppIcon.vue'
import type { TaskStep } from '../../types/tasks'

defineProps<{
  /** Ordered task steps to render. */
  steps: TaskStep[]
}>()
</script>

<template>
  <ul class="task-steps" role="list">
    <li
      v-for="(s, i) in steps"
      :key="i"
      class="task-steps__item"
      :class="`task-steps__item--${s.status}`"
    >
      <span class="task-steps__mark">
        <AppIcon
          v-if="s.status === 'completed'"
          name="check"
          :size="13"
          :stroke-width="2.5"
        />
        <span
          v-else
          class="task-steps__dot"
          :class="{ 'task-steps__dot--active': s.status === 'in_progress' }"
        />
      </span>
      <span class="task-steps__text">{{ s.step }}</span>
    </li>
  </ul>
</template>

<style scoped>
.task-steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.task-steps__item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: var(--leading-snug, 1.4);
  color: var(--text-secondary);
}

.task-steps__mark {
  width: 14px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--success);
}

.task-steps__dot {
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  border: 1.5px solid var(--text-muted);
  box-sizing: border-box;
}

.task-steps__dot--active {
  border-color: var(--accent);
  background: var(--accent);
  animation: taskDotPulse 1.4s ease-in-out infinite;
}

.task-steps__item--completed .task-steps__text {
  color: var(--text-muted);
  text-decoration: line-through;
}

.task-steps__item--in_progress .task-steps__text {
  color: var(--text-primary);
  font-weight: var(--weight-medium);
}

@keyframes taskDotPulse {
  0%,
  100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .task-steps__dot--active {
    animation: none;
  }
}
</style>
