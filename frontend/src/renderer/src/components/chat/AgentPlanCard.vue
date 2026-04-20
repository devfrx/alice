<script setup lang="ts">
/**
 * AgentPlanCard.vue — Inline collapsible card showing what the agent
 * is actually doing for a single assistant message.
 *
 * Surfaces:
 *   • a compact header with the run state, retry/replan counters and
 *     the total number of tool calls observed so far;
 *   • the optional run goal as a plain italic sentence;
 *   • the *real* tool-call timeline derived from the conversation
 *     messages via `useAgentActivity`;
 *   • a secondary collapsible plan checklist when the planner emitted
 *     more than one step (a one-step plan is implicit and is not
 *     shown twice).
 *
 * Visual idiom: neutral surface + 3-px accent stripe on the left edge
 * coloured by run state (running / done / failed / asked_user).  All
 * colours come from the shared design tokens; nothing is hard-coded.
 */

import { computed, ref, toRef, watch } from 'vue'

import AppIcon from '../ui/AppIcon.vue'
import { useAgentActivity } from '../../composables/useAgentActivity'
import type { AgentRun, AgentRunState } from '../../types/agent'

const props = defineProps<{
  /** The agent run to render. */
  run: AgentRun
}>()

// ---------------------------------------------------------------------------
// Activity feed (real tool calls + plan steps)
// ---------------------------------------------------------------------------

const runRef = toRef(props, 'run')
const feed = useAgentActivity(runRef)

const toolActivity = computed(() => feed.value?.toolActivity ?? [])
const planSteps = computed(() => feed.value?.planSteps ?? [])
const stats = computed(() => feed.value?.stats ?? null)
const showPlanSection = computed(() => planSteps.value.length > 1)

// ---------------------------------------------------------------------------
// Expansion state
// ---------------------------------------------------------------------------

const userToggled = ref<boolean>(false)
const collapsed = ref<boolean>(_defaultCollapsed(props.run.state))
const planOpen = ref<boolean>(false)

watch(
  () => props.run.state,
  (state) => {
    if (userToggled.value) return
    collapsed.value = _defaultCollapsed(state)
  },
)

watch(() => props.run.id, () => {
  planOpen.value = false
})

function _defaultCollapsed(state: AgentRunState): boolean {
  return state === 'done' || state === 'failed' || state === 'cancelled'
}

function toggle(): void {
  collapsed.value = !collapsed.value
  userToggled.value = true
}

function togglePlan(): void {
  planOpen.value = !planOpen.value
}

// ---------------------------------------------------------------------------
// Header label
// ---------------------------------------------------------------------------

const headerLabel = computed<string>(() => {
  const state = props.run.state
  switch (state) {
    case 'planning':
      return 'Pianificazione…'
    case 'running':
      if (props.run.total_steps > 1) {
        const cur = Math.min(props.run.current_step + 1, props.run.total_steps)
        return `Passo ${cur} di ${props.run.total_steps}`
      }
      return 'In esecuzione'
    case 'done':
      return 'Completato'
    case 'failed':
      return 'Fallito'
    case 'cancelled':
      return 'Annullato'
    case 'asked_user':
      return 'In attesa di una tua risposta'
    default:
      return 'Agente'
  }
})

const stateClass = computed<string>(() => `agent-plan--${props.run.state}`)
</script>

<template>
  <section class="agent-plan" :class="stateClass" aria-label="Attività dell'agente">
    <button class="agent-plan__head" type="button" :aria-expanded="!collapsed" @click="toggle">
      <span class="agent-plan__badge">Agente</span>
      <span class="agent-plan__title">{{ headerLabel }}</span>

      <span v-if="stats && stats.toolCallsTotal > 0" class="agent-plan__chip"
        :title="`${stats.toolCallsTotal} chiamata${stats.toolCallsTotal === 1 ? '' : 'e'} a strumenti`">
        <AppIcon name="bar-chart" :size="10" :stroke-width="1.75" />
        {{ stats.toolCallsTotal }}
      </span>
      <span v-if="run.replans > 0" class="agent-plan__chip" :title="`Ripianificazioni: ${run.replans}`">
        <AppIcon name="refresh-cw" :size="10" :stroke-width="1.75" />
        {{ run.replans }}
      </span>
      <span v-if="run.retries_total > 0" class="agent-plan__chip agent-plan__chip--warn"
        :title="`Retry totali: ${run.retries_total}`">
        <AppIcon name="refresh-cw" :size="10" :stroke-width="1.75" />
        {{ run.retries_total }}
      </span>

      <AppIcon name="chevron-down" :size="12" :stroke-width="1.75" class="agent-plan__chevron"
        :class="{ 'agent-plan__chevron--open': !collapsed }" />
    </button>

    <div class="agent-plan__body" :class="{ 'agent-plan__body--collapsed': collapsed }">
      <div class="agent-plan__body-inner">
        <p v-if="run.plan?.goal" class="agent-plan__goal">{{ run.plan.goal }}</p>

        <ol v-if="toolActivity.length" class="agent-plan__activity">
          <li v-for="item in toolActivity" :key="item.callId" class="agent-plan__activity-item"
            :class="`agent-plan__activity-item--${item.status}`">
            <span class="agent-plan__dot" :aria-label="item.status">
              <AppIcon v-if="item.status === 'done'" name="check" :size="10" :stroke-width="2.5" />
              <AppIcon v-else-if="item.status === 'failed'" name="x" :size="10" :stroke-width="2.5" />
              <span v-else-if="item.status === 'running'" class="agent-plan__pulse" aria-hidden="true" />
              <span v-else class="agent-plan__bullet" aria-hidden="true" />
            </span>

            <div class="agent-plan__activity-text">
              <span class="agent-plan__activity-label">{{ item.toolLabel }}</span>
              <span v-if="item.argsSummary" class="agent-plan__activity-args">
                {{ item.argsSummary }}
              </span>
              <span v-if="item.resultPreview" class="agent-plan__activity-result"
                :class="{ 'agent-plan__activity-result--err': item.resultIsError }">
                {{ item.resultPreview }}
              </span>
            </div>
          </li>
        </ol>

        <p v-else-if="run.state === 'planning'" class="agent-plan__empty">In attesa del piano…</p>
        <p v-else-if="run.state === 'running'" class="agent-plan__empty">Sto preparando la prima chiamata…</p>

        <!-- Secondary plan section: only when planner emitted >1 step -->
        <div v-if="showPlanSection" class="agent-plan__plan">
          <button type="button" class="agent-plan__plan-head" :aria-expanded="planOpen" @click="togglePlan">
            <AppIcon name="chevron-down" :size="10" :stroke-width="1.75" class="agent-plan__plan-chevron"
              :class="{ 'agent-plan__plan-chevron--open': planOpen }" />
            <span>Piano in {{ planSteps.length }} passi</span>
          </button>
          <ol v-if="planOpen" class="agent-plan__plan-list">
            <li v-for="step in planSteps" :key="step.index" class="agent-plan__plan-item"
              :class="`agent-plan__plan-item--${step.status}`">
              <span class="agent-plan__plan-num">{{ step.index + 1 }}</span>
              <span class="agent-plan__plan-desc">{{ step.description }}</span>
              <span v-if="step.verdict" class="agent-plan__plan-verdict">
                {{ step.verdict.reason }}
              </span>
            </li>
          </ol>
        </div>

        <div v-if="run.pending_question" class="agent-plan__ask">
          <strong>Domanda:</strong> {{ run.pending_question }}
        </div>
        <div v-if="run.error && run.state !== 'done'" class="agent-plan__error">{{ run.error }}</div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* ── Container ─────────────────────────────────────────── */
.agent-plan {
  position: relative;
  margin: var(--space-2) 0 var(--space-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  color: var(--text-primary);
  font-size: var(--text-sm);
  overflow: hidden;
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast);
}

.agent-plan:hover {
  border-color: var(--border-hover);
}

/* Status stripe (3px on the left edge) */
.agent-plan::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 3px;
  background: var(--surface-3);
  transition: background var(--transition-normal);
}

.agent-plan--planning::before,
.agent-plan--running::before,
.agent-plan--asked_user::before {
  background: var(--accent);
}

.agent-plan--done::before {
  background: var(--success);
}

.agent-plan--failed::before,
.agent-plan--cancelled::before {
  background: var(--danger);
}

/* ── Header ────────────────────────────────────────────── */
.agent-plan__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3) var(--space-2) calc(var(--space-3) + 3px);
  background: transparent;
  border: 0;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.agent-plan__head:hover {
  background: var(--surface-hover);
}

.agent-plan__badge {
  display: inline-flex;
  align-items: center;
  padding: 2px var(--space-2);
  border-radius: var(--radius-pill);
  background: var(--accent-medium);
  color: var(--accent);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.agent-plan__title {
  flex: 1;
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-plan__chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px var(--space-1-5);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  font-size: var(--text-2xs);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.agent-plan__chip--warn {
  color: var(--warning);
  border-color: var(--warning-border);
  background: var(--warning-bg);
}

.agent-plan__chevron {
  color: var(--text-muted);
  transition: transform var(--transition-fast);
  flex-shrink: 0;
}

.agent-plan__chevron--open {
  transform: rotate(180deg);
}

/* ── Body (collapse via grid-template-rows trick) ──────── */
.agent-plan__body {
  display: grid;
  grid-template-rows: 1fr;
  transition: grid-template-rows var(--transition-normal);
}

.agent-plan__body--collapsed {
  grid-template-rows: 0fr;
}

.agent-plan__body-inner {
  min-height: 0;
  overflow: hidden;
  padding: 0 var(--space-3) var(--space-3) calc(var(--space-3) + 3px);
}

.agent-plan__goal {
  margin: 0 0 var(--space-2);
  font-style: italic;
  color: var(--text-secondary);
  line-height: var(--leading-snug);
}

/* ── Activity timeline ─────────────────────────────────── */
.agent-plan__activity {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.agent-plan__activity-item {
  display: grid;
  grid-template-columns: 16px 1fr;
  gap: var(--space-2);
  align-items: start;
  color: var(--text-primary);
  transition: opacity var(--transition-fast);
}

.agent-plan__activity-item--pending {
  opacity: 0.55;
}

.agent-plan__dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-top: 2px;
  border-radius: 50%;
  background: var(--surface-3);
  color: var(--text-secondary);
  flex-shrink: 0;
}

.agent-plan__activity-item--done .agent-plan__dot {
  background: var(--success-medium);
  color: var(--success);
}

.agent-plan__activity-item--failed .agent-plan__dot {
  background: var(--danger-medium);
  color: var(--danger);
}

.agent-plan__activity-item--running .agent-plan__dot {
  background: var(--accent-medium);
  color: var(--accent);
}

.agent-plan__bullet {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.7;
}

.agent-plan__pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  animation: agent-plan-pulse 1.4s ease-in-out infinite;
}

@keyframes agent-plan-pulse {

  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }

  50% {
    transform: scale(1.4);
    opacity: 0.55;
  }
}

.agent-plan__activity-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.agent-plan__activity-label {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  line-height: var(--leading-snug);
}

.agent-plan__activity-args {
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: var(--text-2xs);
  color: var(--text-secondary);
  line-height: var(--leading-snug);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-plan__activity-result {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  line-height: var(--leading-snug);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-plan__activity-result--err {
  color: var(--danger);
}

.agent-plan__empty {
  margin: 0;
  color: var(--text-muted);
  font-style: italic;
  font-size: var(--text-xs);
}

/* ── Plan secondary section ───────────────────────────── */
.agent-plan__plan {
  margin-top: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px dashed var(--border);
}

.agent-plan__plan-head {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: 2px 0;
  background: transparent;
  border: 0;
  color: var(--text-secondary);
  font: inherit;
  font-size: var(--text-xs);
  cursor: pointer;
}

.agent-plan__plan-head:hover {
  color: var(--text-primary);
}

.agent-plan__plan-chevron {
  transition: transform var(--transition-fast);
}

.agent-plan__plan-chevron--open {
  transform: rotate(180deg);
}

.agent-plan__plan-list {
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
}

.agent-plan__plan-item {
  display: grid;
  grid-template-columns: 16px 1fr;
  gap: var(--space-2);
  align-items: baseline;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: var(--leading-snug);
}

.agent-plan__plan-item--done {
  color: var(--text-primary);
}

.agent-plan__plan-item--failed,
.agent-plan__plan-item--skipped {
  opacity: 0.55;
}

.agent-plan__plan-num {
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
  text-align: right;
}

.agent-plan__plan-desc {
  color: var(--text-secondary);
}

.agent-plan__plan-verdict {
  grid-column: 2;
  display: block;
  margin-top: 2px;
  color: var(--text-muted);
  font-style: italic;
  font-size: var(--text-2xs);
}

/* ── Auxiliary banners ────────────────────────────────── */
.agent-plan__ask {
  margin-top: var(--space-2);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  color: var(--text-primary);
  font-size: var(--text-xs);
  line-height: var(--leading-snug);
}

.agent-plan__error {
  margin-top: var(--space-2);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--danger-medium);
  border: 1px solid var(--danger);
  color: var(--danger);
  font-size: var(--text-xs);
  line-height: var(--leading-snug);
}
</style>
