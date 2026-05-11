<script setup lang="ts">
/**
 * AgentRunSummary.vue — shared agent-loop status summary.
 *
 * Used by the floating activity panel and by the inline final card so both
 * surfaces expose the same meaningful operational facts: progress, real tool
 * usage, categories, duration, retries/replans, warnings and critic outcome.
 */
import { computed } from 'vue'

import AppIcon from '../ui/AppIcon.vue'
import type { AppIconName } from '../../assets/icons'
import type { ActivityFeed } from '../../composables/useAgentActivity'
import type { AgentRun, AgentRunState } from '../../types/agent'

const props = withDefaults(defineProps<{
  run: AgentRun
  feed: ActivityFeed | null
  compact?: boolean
}>(), {
  compact: false,
})

const CATEGORY_LABELS: Record<string, string> = {
  search: 'ricerca',
  scrape: 'lettura web',
  memory: 'memoria',
  chart: 'grafici',
  code: 'codice',
  image: 'immagini',
  whiteboard: 'lavagna',
  calendar: 'calendario',
  email: 'email',
  note: 'note',
  file: 'file',
  other: 'strumenti',
}

function formatDuration(ms: number | null): string {
  if (ms === null) return props.run.finished_at ? 'durata n.d.' : 'live'
  if (ms < 1000) return '<1s'
  const totalSeconds = Math.round(ms / 1000)
  if (totalSeconds < 60) return `${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`
}

function labelForState(state: AgentRunState): string {
  switch (state) {
    case 'planning': return 'Pianificazione'
    case 'running': return 'In esecuzione'
    case 'asked_user': return 'Attende input'
    case 'done': return 'Completato'
    case 'failed': return 'Fallito'
    case 'cancelled': return 'Annullato'
    default: return 'Agente'
  }
}

const statusLabel = computed(() => labelForState(props.run.state))

const progressLabel = computed(() => {
  if (props.run.total_steps > 0) {
    const current = props.run.state === 'done'
      ? props.run.total_steps
      : Math.min(props.run.current_step + 1, props.run.total_steps)
    return `${current}/${props.run.total_steps}`
  }
  return props.run.mode === 'bypass' ? 'diretta' : 'piano'
})

const toolCounts = computed(() => {
  const activity = props.feed?.toolActivity ?? []
  return {
    total: activity.length,
    done: activity.filter((item) => item.status === 'done').length,
    failed: activity.filter((item) => item.status === 'failed').length,
    running: activity.filter((item) => item.status === 'running').length,
  }
})

const durationText = computed(() => formatDuration(props.feed?.stats.durationMs ?? null))

const categoryChips = computed(() => {
  const categories = props.feed?.stats.toolCallsByCategory ?? {}
  return Object.entries(categories)
    .sort((a, b) => b[1] - a[1])
    .slice(0, props.compact ? 3 : 5)
    .map(([category, count]) => ({
      category,
      count,
      label: CATEGORY_LABELS[category] ?? category,
    }))
})

const latestVerdict = computed(() => {
  const indices = Object.keys(props.run.verdicts).map((key) => Number(key))
  if (!indices.length) return null
  return props.run.verdicts[Math.max(...indices)] ?? null
})

const insightLine = computed(() => {
  if (props.run.pending_question) return props.run.pending_question
  if (props.run.error && props.run.state !== 'done') return props.run.error
  const warning = props.run.warnings[props.run.warnings.length - 1]
  if (warning) return warning.message
  const verdict = latestVerdict.value
  if (verdict?.reason) return verdict.reason
  return props.run.plan?.goal || props.run.goal || ''
})

const metrics = computed<Array<{ icon: AppIconName; value: string; label: string; tone?: string }>>(() => {
  const tools = toolCounts.value
  return [
    { icon: 'branch', value: progressLabel.value, label: 'passi' },
    { icon: 'tool', value: String(tools.total), label: tools.total === 1 ? 'tool' : 'tool' },
    { icon: tools.failed > 0 ? 'circle-x' : 'check', value: `${tools.done}/${tools.total || 0}`, label: 'ok', tone: tools.failed > 0 ? 'danger' : 'success' },
    { icon: 'clock', value: durationText.value, label: 'tempo' },
  ]
})
</script>

<template>
  <section class="agent-run-summary" :class="[
    `agent-run-summary--${run.state}`,
    { 'agent-run-summary--compact': compact },
  ]" aria-label="Riepilogo attività agente">
    <div class="agent-run-summary__head">
      <span class="agent-run-summary__signal" aria-hidden="true" />
      <div class="agent-run-summary__title-group">
        <span class="agent-run-summary__eyebrow">Loop agentico</span>
        <span class="agent-run-summary__state">{{ statusLabel }}</span>
      </div>
      <span v-if="toolCounts.running > 0" class="agent-run-summary__live">{{ toolCounts.running }} attivi</span>
    </div>

    <div class="agent-run-summary__metrics">
      <div v-for="metric in metrics" :key="metric.label" class="agent-run-summary__metric"
        :class="metric.tone ? `agent-run-summary__metric--${metric.tone}` : ''">
        <AppIcon :name="metric.icon" :size="12" />
        <span class="agent-run-summary__metric-value">{{ metric.value }}</span>
        <span class="agent-run-summary__metric-label">{{ metric.label }}</span>
      </div>
    </div>

    <div v-if="categoryChips.length || run.replans > 0 || run.retries_total > 0" class="agent-run-summary__chips">
      <span v-for="chip in categoryChips" :key="chip.category" class="agent-run-summary__chip">
        {{ chip.label }} <strong>{{ chip.count }}</strong>
      </span>
      <span v-if="run.replans > 0" class="agent-run-summary__chip agent-run-summary__chip--warn">
        replan <strong>{{ run.replans }}</strong>
      </span>
      <span v-if="run.retries_total > 0" class="agent-run-summary__chip agent-run-summary__chip--warn">
        retry <strong>{{ run.retries_total }}</strong>
      </span>
    </div>

    <p v-if="insightLine" class="agent-run-summary__insight">{{ insightLine }}</p>
  </section>
</template>

<style scoped>
.agent-run-summary {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--surface-2) 72%, transparent), transparent 76%),
    color-mix(in srgb, var(--surface-1) 86%, transparent);
  border-bottom: 1px solid var(--border);
}

.agent-run-summary--compact {
  padding: var(--space-2-5) var(--space-3);
  border-top: 1px solid var(--border);
}

.agent-run-summary__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.agent-run-summary__signal {
  width: 9px;
  height: 9px;
  border-radius: var(--radius-full);
  background: var(--accent);
  box-shadow: 0 0 14px color-mix(in srgb, var(--accent) 58%, transparent);
  flex-shrink: 0;
}

.agent-run-summary--done .agent-run-summary__signal {
  background: var(--success);
  box-shadow: 0 0 12px var(--success-glow);
}

.agent-run-summary--failed .agent-run-summary__signal,
.agent-run-summary--cancelled .agent-run-summary__signal {
  background: var(--danger);
  box-shadow: 0 0 12px var(--danger-glow);
}

.agent-run-summary__title-group {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}

.agent-run-summary__eyebrow {
  color: var(--text-muted);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.agent-run-summary__state {
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  line-height: var(--leading-tight);
}

.agent-run-summary__live {
  padding: 2px var(--space-1-5);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-sm);
  color: var(--accent);
  background: var(--accent-medium);
  font-size: var(--text-2xs);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.agent-run-summary__metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-1-5);
}

.agent-run-summary__metric {
  min-width: 0;
  display: grid;
  grid-template-columns: auto 1fr;
  column-gap: 5px;
  row-gap: 1px;
  align-items: center;
  padding: var(--space-1-5) var(--space-2);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--surface-2) 72%, transparent);
  color: var(--text-secondary);
}

.agent-run-summary__metric-value {
  min-width: 0;
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-run-summary__metric-label {
  grid-column: 2;
  color: var(--text-muted);
  font-size: var(--text-2xs);
  line-height: var(--leading-tight);
}

.agent-run-summary__metric--success {
  color: var(--success);
}

.agent-run-summary__metric--danger {
  color: var(--danger);
}

.agent-run-summary__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.agent-run-summary__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px var(--space-1-5);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface-2) 60%, transparent);
  color: var(--text-secondary);
  font-size: var(--text-2xs);
  line-height: var(--leading-tight);
}

.agent-run-summary__chip strong {
  color: var(--text-primary);
  font-weight: var(--weight-semibold);
}

.agent-run-summary__chip--warn {
  border-color: var(--warning-border);
  color: var(--warning);
}

.agent-run-summary__insight {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--text-xs);
  line-height: var(--leading-snug);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

@container (max-width: 320px) {
  .agent-run-summary__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>