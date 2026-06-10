<script setup lang="ts">
/**
 * TaskStrip — Fixed, low-chrome Tasks strip shown above the composer.
 *
 * Surfaces the per-conversation task list (the model-driven `update_plan`
 * todo-list, owned by the {@link useTasksStore}) in three visual states:
 *
 * - EMPTY    — no steps: a thin dashed placeholder ("Nessuna attività
 *              pianificata"). Always rendered, never collapsed to nothing.
 * - COLLAPSED — a single-line "ticker": status dot + the current step label +
 *              a right-aligned `{completed}/{total}` + an expand chevron.
 * - EXPANDED  — a "panel": header ("Attività" + count + collapse chevron), a
 *              thin progress bar, then the full {@link TaskStepList}.
 *
 * Auto-expand state machine
 * -------------------------
 * `isWorking = isStreamingCurrentConversation && (some step in_progress)`.
 * When work begins the strip auto-expands; when streaming ends OR every step is
 * complete it auto-collapses. A manual click (the ticker/header) overrides the
 * automation for the remainder of the turn; the override is dropped at the next
 * turn boundary — either a new `in_progress` step appearing after none, or the
 * `conversationId` changing. Deterministic: refs + watchers only.
 *
 * Mounting is decided by the parent (workspace only); this component does not
 * mount itself anywhere.
 */
import { computed, ref, watch } from 'vue'

import AppIcon from '../ui/AppIcon.vue'
import TaskStepList from './TaskStepList.vue'
import { useTasksStore } from '../../stores/tasks'
import { useChatStore } from '../../stores/chat'

const props = defineProps<{
  /** Conversation whose task list to surface (null when none is active). */
  conversationId: string | null
}>()

const tasksStore = useTasksStore()
const chat = useChatStore()

// ---------------------------------------------------------------------------
// Derived task data
// ---------------------------------------------------------------------------

/** Ordered steps for the active conversation (empty when none / unknown). */
const steps = computed(() =>
  props.conversationId ? tasksStore.tasksFor(props.conversationId) : [],
)

/** Total number of steps. */
const total = computed(() => steps.value.length)

/** Number of completed steps. */
const completed = computed(
  () => steps.value.filter((s) => s.status === 'completed').length,
)

/** True once every step is completed (and at least one exists). */
const allComplete = computed(() => total.value > 0 && completed.value === total.value)

/** True while at least one step is actively in progress. */
const hasInProgress = computed(() => steps.value.some((s) => s.status === 'in_progress'))

/** The step the ticker points at: first in_progress, else first pending, else last. */
const currentStep = computed(() => {
  const list = steps.value
  if (list.length === 0) return null
  return (
    list.find((s) => s.status === 'in_progress') ??
    list.find((s) => s.status === 'pending') ??
    list[list.length - 1]
  )
})

/** Label shown by the collapsed ticker. */
const currentLabel = computed(() => currentStep.value?.step ?? '')

/** True only while the active conversation is streaming AND a step is in progress. */
const isWorking = computed(() => chat.isStreamingCurrentConversation && hasInProgress.value)

/** Progress-bar fill, 0–100. */
const progressPct = computed(() => (total.value ? (completed.value / total.value) * 100 : 0))

/** Status flavour of the collapsed ticker dot. */
const tickerStatus = computed<'working' | 'done' | 'idle'>(() => {
  if (isWorking.value) return 'working'
  if (allComplete.value) return 'done'
  return 'idle'
})

// ---------------------------------------------------------------------------
// Expand / collapse state machine
// ---------------------------------------------------------------------------

/** Whether the strip is expanded into the full panel. */
const expanded = ref(false)

/** Set when the user manually toggles; suppresses auto-collapse for the turn. */
const manualOverride = ref(false)

/** Coarse render state used by the template. */
const viewState = computed<'empty' | 'collapsed' | 'expanded'>(() => {
  if (total.value === 0) return 'empty'
  return expanded.value ? 'expanded' : 'collapsed'
})

/** Manual toggle: flips the panel and pins the choice for the rest of the turn. */
function toggle(): void {
  expanded.value = !expanded.value
  manualOverride.value = true
}

// A new in_progress step appearing after none marks a fresh turn → drop override.
watch(hasInProgress, (now, was) => {
  if (now && !was) manualOverride.value = false
})

// Auto-expand when work starts; auto-collapse when work ends (unless overridden).
watch(isWorking, (working, was) => {
  if (working && !was) expanded.value = true
  else if (!working && was && !manualOverride.value) expanded.value = false
})

// All steps done → collapse back to the ticker (unless the user pinned it open).
watch(allComplete, (done) => {
  if (done && !manualOverride.value) expanded.value = false
})

// Conversation switch (and initial mount): reset the override, derive the
// initial open/closed state from whether the new conversation is working, and
// fetch its task snapshot once.
watch(
  () => props.conversationId,
  (id) => {
    manualOverride.value = false
    expanded.value = isWorking.value
    if (id) tasksStore.ensureForConversation(id)
  },
  { immediate: true },
)
</script>

<template>
  <div class="task-strip" :class="`task-strip--${viewState}`">
    <!-- COLLAPSED: ticker (EMPTY renders nothing; the root is hidden) -->
    <button
      v-if="viewState === 'collapsed'"
      type="button"
      class="task-strip__ticker"
      :aria-label="`Espandi attività — ${completed} di ${total} completate`"
      @click="toggle"
    >
      <span
        class="task-strip__dot"
        :class="`task-strip__dot--${tickerStatus}`"
      />
      <span class="task-strip__label">{{ currentLabel }}</span>
      <span class="task-strip__count">{{ completed }}/{{ total }}</span>
      <AppIcon name="chevron-down" :size="14" class="task-strip__chevron" />
    </button>

    <!-- EXPANDED: panel -->
    <div v-else-if="viewState === 'expanded'" class="task-strip__panel">
      <button
        type="button"
        class="task-strip__header"
        aria-label="Comprimi attività"
        @click="toggle"
      >
        <span class="task-strip__title">Attività</span>
        <span class="task-strip__count">{{ completed }}/{{ total }}</span>
        <AppIcon name="chevron-up" :size="14" class="task-strip__chevron" />
      </button>

      <div class="task-strip__progress" role="presentation">
        <span class="task-strip__progress-fill" :style="{ width: `${progressPct}%` }" />
      </div>

      <div class="task-strip__scroll">
        <TaskStepList :steps="steps" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-strip {
  box-sizing: border-box;
  font-family: var(--font-sans);
}

/* No tasks → the strip removes itself from the layout entirely, so the
   composer sits clean with nothing hovering above it. */
.task-strip--empty {
  display: none;
}

/* ----- COLLAPSED ticker ----- */
.task-strip__ticker {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  min-height: 36px;
  padding: 0 var(--space-3);
  margin: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-family: inherit;
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
  transition: background 200ms var(--ease-out-expo);
}

.task-strip__ticker:hover {
  background: var(--surface-2);
}

.task-strip__label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}

.task-strip__count {
  flex: 0 0 auto;
  font-variant-numeric: tabular-nums;
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.task-strip__chevron {
  flex: 0 0 auto;
  color: var(--text-muted);
}

/* status dot */
.task-strip__dot {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  border: 1.5px solid var(--text-muted);
  box-sizing: border-box;
}

.task-strip__dot--working {
  border-color: var(--accent);
  background: var(--accent);
  animation: taskStripPulse 1.4s ease-in-out infinite;
}

.task-strip__dot--done {
  border-color: var(--success);
  background: var(--success);
}

/* ----- EXPANDED panel ----- */
.task-strip__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface-1);
}

/* The step list scrolls internally so a long plan never shoves the composer
   down — the header + progress bar stay pinned above it. */
.task-strip__scroll {
  min-height: 0;
  max-height: min(46vh, 320px);
  overflow-y: auto;
  padding-right: var(--space-1);
}

.task-strip__scroll::-webkit-scrollbar {
  width: 3px;
}

.task-strip__scroll::-webkit-scrollbar-track {
  background: transparent;
}

.task-strip__scroll::-webkit-scrollbar-thumb {
  background: var(--surface-3);
  border-radius: var(--radius-xs);
}

.task-strip__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 0;
  margin: 0;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-family: inherit;
  cursor: pointer;
}

.task-strip__title {
  flex: 1 1 auto;
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  letter-spacing: 0.01em;
}

.task-strip__progress {
  width: 100%;
  height: 3px;
  border-radius: var(--radius-md);
  background: var(--surface-3);
  overflow: hidden;
}

.task-strip__progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--success);
  transition: width 320ms var(--ease-out-expo);
}

@keyframes taskStripPulse {
  0%,
  100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .task-strip__dot--working {
    animation: none;
  }
  .task-strip__ticker,
  .task-strip__progress-fill {
    transition: none;
  }
}
</style>
