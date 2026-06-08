<script setup lang="ts">
/**
 * AgentActivityCard.vue — Compact per-turn run budget + status panel.
 *
 * Surfaces the *new* canonical turn-event info folded by the `agentRun`
 * store (see stores/agentRun.ts, types/turn.ts): run status, the step
 * budget (step / maxSteps + a thin progress bar), token / tool-call
 * counters, and a compact tool-status *summary* (counts only).
 *
 * It deliberately does NOT re-render the per-tool live timeline — that is
 * owned by ToolExecutionIndicator.vue. The card renders nothing when no
 * turn is in flight (top-level `v-if`).
 */
import { computed } from 'vue'

import { useAgentRunStore } from '../../stores/agentRun'
import { summarizeTools } from '../../utils/turnActivity'
import AliceSpinner from '../ui/AliceSpinner.vue'
import AppIcon from '../ui/AppIcon.vue'

const agentRunStore = useAgentRunStore()

/** The active turn's run view-model, or null when no turn is in flight. */
const run = computed(() => agentRunStore.currentRun)

/** True while the run is still executing. */
const isRunning = computed(() => run.value?.status === 'running')

/** Localised status word for the badge. */
const statusLabel = computed(() => (isRunning.value ? 'In esecuzione' : 'Completato'))

/** Per-status tool counts for the compact summary pills. */
const toolSummary = computed(() => summarizeTools(run.value?.tools ?? []))

/** Step-budget completion as a CSS width string (guards divide-by-zero). */
const progressWidth = computed(() => {
  const r = run.value
  if (!r || r.maxSteps <= 0) return '0%'
  const pct = Math.min(100, Math.round((r.step / r.maxSteps) * 100))
  return `${pct}%`
})
</script>

<template>
  <div v-if="run" class="agent-card" :class="isRunning ? 'agent-card--running' : 'agent-card--finished'" role="group"
    aria-label="Stato del turno">
    <!-- Header: status badge + step budget -->
    <div class="agent-card__head">
      <span class="agent-card__badge">
        <AliceSpinner v-if="isRunning" size="xs" aria-label="In esecuzione" />
        <AppIcon v-else name="check" :size="12" class="agent-card__badge-icon" />
        <span class="agent-card__badge-text">{{ statusLabel }}</span>
      </span>
      <span v-if="!isRunning && run.finishReason" class="agent-card__reason" :title="run.finishReason">
        {{ run.finishReason }}
      </span>
      <span class="agent-card__step" :aria-label="`Passo ${run.step} di ${run.maxSteps}`">
        Passo {{ run.step }} / {{ run.maxSteps }}
      </span>
    </div>

    <!-- Step-budget progress bar (decorative — the text above is the SR source) -->
    <div class="agent-card__bar" aria-hidden="true">
      <div class="agent-card__bar-fill" :style="{ width: progressWidth }" />
    </div>

    <!-- Footer: token / tool-call counters + tool-status summary -->
    <div class="agent-card__meta">
      <span class="agent-card__stats">
        <span class="agent-card__stat" :title="`Token in ingresso: ${run.inputTokens}`"
          :aria-label="`${run.inputTokens} token in ingresso`">
          <span class="agent-card__arrow" aria-hidden="true">↑</span>{{ run.inputTokens }}
        </span>
        <span class="agent-card__stat" :title="`Token in uscita: ${run.outputTokens}`"
          :aria-label="`${run.outputTokens} token in uscita`">
          <span class="agent-card__arrow" aria-hidden="true">↓</span>{{ run.outputTokens }}
        </span>
        <span class="agent-card__stat" :title="`Chiamate a strumenti: ${run.toolCalls}`"
          :aria-label="`${run.toolCalls} chiamate a strumenti`">
          <AppIcon name="tool" :size="11" class="agent-card__stat-icon" />{{ run.toolCalls }}
        </span>
      </span>

      <span v-if="toolSummary.total > 0" class="agent-card__pills" aria-label="Riepilogo strumenti">
        <span v-if="toolSummary.success > 0" class="agent-card__pill agent-card__pill--ok"
          :aria-label="`${toolSummary.success} strumenti completati`">
          <span class="agent-card__pill-dot" aria-hidden="true" />{{ toolSummary.success }}
        </span>
        <span v-if="toolSummary.running > 0" class="agent-card__pill agent-card__pill--run"
          :aria-label="`${toolSummary.running} strumenti in esecuzione`">
          <span class="agent-card__pill-dot" aria-hidden="true" />{{ toolSummary.running }}
        </span>
        <span v-if="toolSummary.error > 0" class="agent-card__pill agent-card__pill--err"
          :aria-label="`${toolSummary.error} strumenti in errore`">
          <span class="agent-card__pill-dot" aria-hidden="true" />{{ toolSummary.error }}
        </span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.agent-card {
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
}

/* Header row */
.agent-card__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.agent-card__badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
}

.agent-card__badge-icon {
  color: var(--success);
}

.agent-card__badge-text {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
}

.agent-card--running .agent-card__badge-text {
  color: var(--accent);
}

.agent-card--finished .agent-card__badge-text {
  color: var(--success);
}

.agent-card__reason {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.agent-card__step {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

/* Progress bar */
.agent-card__bar {
  height: 3px;
  width: 100%;
  background: var(--surface-1);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.agent-card__bar-fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--accent);
  transition: width var(--duration-normal) ease;
}

.agent-card--finished .agent-card__bar-fill {
  background: var(--success);
}

/* Footer row */
.agent-card__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.agent-card__stats {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.agent-card__stat {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-muted);
}

.agent-card__arrow {
  color: var(--text-secondary);
  font-weight: var(--weight-medium);
}

.agent-card__stat-icon {
  color: var(--text-secondary);
}

/* Tool-status summary pills */
.agent-card__pills {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
}

.agent-card__pill {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-secondary);
}

.agent-card__pill-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.agent-card__pill--ok .agent-card__pill-dot {
  background: var(--success);
}

.agent-card__pill--err .agent-card__pill-dot {
  background: var(--danger);
}

.agent-card__pill--run .agent-card__pill-dot {
  background: var(--accent);
  animation: agentCardPulse 1.4s ease-in-out infinite;
}

@keyframes agentCardPulse {

  0%,
  100% {
    opacity: 0.4;
  }

  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {

  .agent-card__bar-fill,
  .agent-card__pill--run .agent-card__pill-dot {
    transition: none;
    animation: none;
  }
}
</style>
