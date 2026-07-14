<!-- components/desk/DeskDock.vue -->
<script setup lang="ts">
/**
 * DeskDock — the atelier tray: one launcher per available catalog module,
 * open/minimized state dots, the Attività badge (running subagents +
 * background tasks) and the compact plan chip. Every action goes through the
 * desk store — the same implementations the agent's window.* commands call.
 */
import { computed } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import { listModules } from '../../composables/workspace/moduleRegistry'
import { useDeskStore } from '../../stores/desk'
import { useChatStore } from '../../stores/chat'
import { useTasksStore } from '../../stores/tasks'
import { useBackgroundTasksStore } from '../../stores/backgroundTasks'
import { planView } from '../../composables/horizon/horizonScene'

const desk = useDeskStore()
const chatStore = useChatStore()
const tasksStore = useTasksStore()
const backgroundTasks = useBackgroundTasksStore()

const modules = computed(() =>
  listModules().filter(
    (m) => m.available?.({ conversationId: chatStore.currentConversation?.id ?? null }) ?? true
  )
)

const activityCount = computed(() => backgroundTasks.active.length)

const plan = computed(() => {
  const id = chatStore.currentConversation?.id
  return planView(id ? tasksStore.tasksFor(id) : [])
})

function stateOf(moduleId: string): 'open' | 'minimized' | 'none' {
  const s = desk.openByModule[moduleId]
  if (s === undefined) return 'none'
  if (s.open > 0) return 'open'
  if (s.minimized > 0) return 'minimized'
  return 'none'
}
</script>

<template>
  <nav class="desk-dock" aria-label="Vassoio moduli">
    <span v-for="m in modules" :key="m.id" class="desk-dock__slot">
      <UiIconButton
        :label="m.label"
        size="sm"
        variant="ghost"
        :active="stateOf(m.id) === 'open'"
        @click="desk.openWindow(m.id)"
      >
        <AppIcon :name="m.icon" :size="15" />
      </UiIconButton>
      <span
        v-if="stateOf(m.id) !== 'none'"
        class="desk-dock__dot"
        :class="{ 'desk-dock__dot--minimized': stateOf(m.id) === 'minimized' }"
        aria-hidden="true"
      />
      <span
        v-if="m.id === 'activity' && activityCount > 0"
        class="desk-dock__badge"
        role="status"
        :aria-label="`${activityCount} attività in corso`"
      >
        {{ activityCount }}
      </span>
    </span>

    <button
      v-if="plan.total > 0"
      class="desk-dock__plan"
      type="button"
      :aria-label="`Apri il piano (${plan.completed} di ${plan.total} completati)`"
      @click="desk.openWindow('plan')"
    >
      PIANO {{ plan.completed }}/{{ plan.total }}
    </button>
  </nav>
</template>

<style scoped>
.desk-dock {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1-5) var(--space-2);
  background: linear-gradient(180deg, var(--surface-2), var(--surface-1));
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-lg);
  box-shadow:
    var(--hz-shadow-sheet, var(--shadow-floating)),
    inset 0 1px 0 var(--hz-highlight, transparent);
}

.desk-dock__slot {
  position: relative;
  display: inline-flex;
}

.desk-dock__dot {
  position: absolute;
  bottom: -4px;
  left: 50%;
  transform: translateX(-50%);
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--accent);
  animation: desk-dock-breath 3s ease-in-out infinite;
}

.desk-dock__dot--minimized {
  background: var(--border-hover);
  animation: none;
}

.desk-dock__badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 14px;
  height: 14px;
  padding: 0 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  color: var(--text-on-accent);
  background: var(--accent);
  border-radius: var(--radius-pill);
}

.desk-dock__plan {
  margin-left: var(--space-1-5);
  border: none;
  background: transparent;
  padding: 0 var(--space-1);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: 0.14em;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color var(--duration-fast) var(--ease-out);
}

.desk-dock__plan:hover {
  color: var(--text-primary);
}

@keyframes desk-dock-breath {
  0%,
  100% {
    box-shadow: 0 0 3px var(--accent-medium);
  }
  50% {
    box-shadow: 0 0 8px var(--accent-vivid);
  }
}

@media (prefers-reduced-motion: reduce) {
  .desk-dock__dot {
    animation: none;
  }
}
</style>
