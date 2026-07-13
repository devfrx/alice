<script setup lang="ts">
/**
 * ActivityModule — the agent's full activity detail: per-turn tool calls,
 * interactions, token usage (agentRun store) and running background tasks /
 * subagents (backgroundTasks store). Read-only observability surface.
 *
 * ## Param keys (params?: Record<string, unknown>)
 * none — the module always follows the current run.
 */
import { computed } from 'vue'
import { useAgentRunStore } from '../../../stores/agentRun'
import { useBackgroundTasksStore } from '../../../stores/backgroundTasks'
import AppIcon from '../../ui/AppIcon.vue'
import AliceSpinner from '../../ui/AliceSpinner.vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'

defineProps<{
  params?: Record<string, unknown>
}>()

const agentRun = useAgentRunStore()
const backgroundTasks = useBackgroundTasksStore()

const run = computed(() => agentRun.currentRun)

/** Tools + interactions merged in arrival order (both carry `seq`). */
const activities = computed(() => {
  const r = run.value
  if (r === null) return []
  return [
    ...r.tools.map((t) => ({ type: 'tool' as const, seq: t.seq, tool: t })),
    ...r.interactions.map((i) => ({ type: 'interaction' as const, seq: i.seq, interaction: i }))
  ].sort((a, b) => a.seq - b.seq)
})

const isEmpty = computed(() => run.value === null && backgroundTasks.active.length === 0)

/** Italian labels for the interaction `kind` enum (ws schema: WsInteractionRequested.kind). */
const INTERACTION_LABELS: Record<string, string> = {
  tool_confirmation: 'conferma tool',
  ask_user: 'domanda',
  client_tool_call: 'comando app'
}

function interactionLabel(kind: string): string {
  return INTERACTION_LABELS[kind] ?? kind.replace(/_/g, ' ')
}

function argsSummary(args: Record<string, unknown>): string {
  try {
    const s = JSON.stringify(args)
    return s.length > 80 ? `${s.slice(0, 77)}…` : s
  } catch {
    return ''
  }
}
</script>

<template>
  <div class="activity-module">
    <UiEmptyState
      v-if="isEmpty"
      icon="pulse"
      title="Nessuna attività"
      subtitle="I tool e i subagent del turno appariranno qui"
      compact
    />

    <template v-else>
      <div v-if="run" class="activity-module__meta">
        <span v-if="run.maxSteps > 0">passo {{ run.step }}/{{ run.maxSteps }}</span>
        <span v-else-if="run.step > 0">passo {{ run.step }}</span>
        <span>{{ run.toolCalls }} tool</span>
        <span>{{ (run.inputTokens + run.outputTokens).toLocaleString('it-IT') }} token</span>
        <span v-if="run.status === 'finished'" class="activity-module__done">concluso</span>
      </div>

      <ul v-if="activities.length > 0" class="activity-module__list">
        <li v-for="a in activities" :key="`${a.type}-${a.seq}`" class="activity-module__row">
          <template v-if="a.type === 'tool'">
            <AliceSpinner v-if="a.tool.status === 'running'" size="xs" />
            <AppIcon
              v-else
              :name="a.tool.status === 'success' ? 'check' : 'circle-x'"
              :size="12"
              :class="a.tool.status === 'success' ? 'activity-module__ok' : 'activity-module__err'"
            />
            <span class="activity-module__name">{{ a.tool.toolName.replace(/_/g, ' ') }}</span>
            <span class="activity-module__args">{{ argsSummary(a.tool.args) }}</span>
          </template>
          <template v-else>
            <AppIcon name="alert-circle" :size="12" />
            <span class="activity-module__name">{{ interactionLabel(a.interaction.kind) }}</span>
            <span class="activity-module__args">{{
              a.interaction.status === 'pending' ? 'in attesa…' : (a.interaction.outcome ?? '')
            }}</span>
          </template>
        </li>
      </ul>

      <p v-if="run && activities.length === 0" class="activity-module__waiting">
        in attesa del primo tool…
      </p>

      <section v-if="backgroundTasks.active.length > 0" class="activity-module__bg">
        <h3 class="activity-module__bg-title">In background</h3>
        <ul class="activity-module__list">
          <li v-for="t in backgroundTasks.active" :key="t.task_id" class="activity-module__row">
            <AliceSpinner size="xs" />
            <span class="activity-module__name">{{ t.label }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.activity-module {
  height: 100%;
  overflow-y: auto;
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.activity-module__meta {
  display: flex;
  gap: var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.activity-module__done {
  color: var(--state-success);
}

.activity-module__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
}

.activity-module__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  min-width: 0;
}

.activity-module__name {
  color: var(--text-primary);
  flex: 0 1 auto;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-module__args {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-muted);
  flex: 1 1 auto;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.activity-module__waiting {
  margin: 0;
  font-size: var(--text-xs);
  font-style: italic;
  color: var(--text-muted);
}

.activity-module__ok {
  color: var(--state-success);
}

.activity-module__err {
  color: var(--state-danger);
}

.activity-module__bg-title {
  margin: 0 0 var(--space-1-5);
  font-size: var(--text-2xs);
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-muted);
  font-weight: var(--weight-medium);
}
</style>
