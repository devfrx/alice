<script setup lang="ts">
/**
 * AgentPlanCard.vue — Collapsible checklist of an agent loop's plan.
 *
 * Renders the live plan attached to an assistant message: each step
 * shows a status icon (pending / in-progress / done / retry / failed),
 * its description, and any verdict reason once the critic has spoken.
 *
 * Default expansion follows the run state: expanded while
 * `planning` / `running` / `asked_user`, collapsed once the run has
 * settled (`done` / `failed` / `cancelled`).  The user can override
 * the toggle at any time.
 */

import { computed, ref, watch } from 'vue'

import AppIcon from '../ui/AppIcon.vue'
import type { AgentRun, Step, StepStatus, Verdict } from '../../types/agent'

const props = defineProps<{
  /** The run to render. */
  run: AgentRun
}>()

// ---------------------------------------------------------------------------
// Expansion state
// ---------------------------------------------------------------------------

const userToggled = ref<boolean>(false)
const collapsed = ref<boolean>(_defaultCollapsed(props.run.state))

watch(
  () => props.run.state,
  (state) => {
    if (userToggled.value) return
    collapsed.value = _defaultCollapsed(state)
  },
)

function _defaultCollapsed(state: AgentRun['state']): boolean {
  return state === 'done' || state === 'failed' || state === 'cancelled'
}

function toggle(): void {
  collapsed.value = !collapsed.value
  userToggled.value = true
}

// ---------------------------------------------------------------------------
// Derived state
// ---------------------------------------------------------------------------

interface RenderedStep {
  step: Step
  status: StepStatus
  verdict: Verdict | null
}

const steps = computed<RenderedStep[]>(() => {
  const plan = props.run.plan
  if (!plan) return []
  return plan.steps.map((step, idx) => ({
    step,
    status: _statusFor(idx),
    verdict: props.run.verdicts[idx] ?? null,
  }))
})

function _statusFor(index: number): StepStatus {
  const verdict = props.run.verdicts[index]
  const runState = props.run.state
  const current = props.run.current_step

  if (verdict) {
    switch (verdict.action) {
      case 'ok':
        return 'done'
      case 'retry':
        return index === current ? 'in_progress' : 'retry'
      case 'replan':
        return 'done'
      case 'ask_user':
        return 'in_progress'
      case 'abort':
        return 'failed'
    }
  }

  if (runState === 'cancelled' || runState === 'failed') {
    if (index < current) return 'done'
    if (index === current) return 'failed'
    return 'skipped'
  }

  if (index < current) return 'done'
  if (index === current && (runState === 'running' || runState === 'planning')) {
    return 'in_progress'
  }
  return 'pending'
}

const headerLabel = computed<string>(() => {
  const state = props.run.state
  switch (state) {
    case 'planning':
      return 'Pianificazione…'
    case 'running':
      return `Step ${props.run.current_step + 1} / ${props.run.total_steps || '?'}`
    case 'done':
      return 'Piano completato'
    case 'failed':
      return 'Piano fallito'
    case 'cancelled':
      return 'Piano annullato'
    case 'asked_user':
      return 'In attesa di una tua risposta'
    default:
      return 'Piano agente'
  }
})

const stateClass = computed<string>(() => `agent-plan--${props.run.state}`)
</script>

<template>
  <section class="agent-plan" :class="stateClass" aria-label="Piano dell'agente">
    <button
      class="agent-plan__head"
      type="button"
      :aria-expanded="!collapsed"
      @click="toggle"
    >
      <span class="agent-plan__badge">Agente</span>
      <span class="agent-plan__title">{{ headerLabel }}</span>
      <span v-if="run.replans > 0" class="agent-plan__meta" :title="`Ripianificazioni: ${run.replans}`">
        ↻ {{ run.replans }}
      </span>
      <span v-if="run.retries_total > 0" class="agent-plan__meta" :title="`Retry totali: ${run.retries_total}`">
        ⟳ {{ run.retries_total }}
      </span>
      <AppIcon
        name="chevron-down"
        :size="12"
        :stroke-width="1.5"
        class="agent-plan__chevron"
        :class="{ 'agent-plan__chevron--open': !collapsed }"
      />
    </button>

    <div class="agent-plan__body" :class="{ 'agent-plan__body--collapsed': collapsed }">
      <p v-if="run.plan?.goal" class="agent-plan__goal">{{ run.plan.goal }}</p>

      <ol v-if="steps.length" class="agent-plan__steps">
        <li
          v-for="(item, idx) in steps"
          :key="idx"
          class="agent-plan__step"
          :class="`agent-plan__step--${item.status}`"
        >
          <span class="agent-plan__step-icon" :aria-label="item.status">
            <AppIcon
              v-if="item.status === 'done'"
              name="check"
              :size="12"
              :stroke-width="2.5"
            />
            <AppIcon
              v-else-if="item.status === 'failed'"
              name="x"
              :size="12"
              :stroke-width="2.5"
            />
            <AppIcon
              v-else-if="item.status === 'retry'"
              name="refresh-cw"
              :size="12"
              :stroke-width="2"
            />
            <span v-else-if="item.status === 'in_progress'" class="agent-plan__spinner" aria-hidden="true" />
            <span v-else class="agent-plan__dot" aria-hidden="true" />
          </span>

          <div class="agent-plan__step-text">
            <span class="agent-plan__step-num">{{ idx + 1 }}.</span>
            <span class="agent-plan__step-desc">{{ item.step.description }}</span>
            <span
              v-if="item.step.tool_hint"
              class="agent-plan__step-tool"
              :title="`Tool suggerito: ${item.step.tool_hint}`"
            >
              [{{ item.step.tool_hint }}]
            </span>
            <span v-if="item.verdict" class="agent-plan__step-verdict">
              {{ item.verdict.reason }}
            </span>
          </div>
        </li>
      </ol>
      <p v-else class="agent-plan__empty">Nessun passo ancora pianificato.</p>

      <div v-if="run.pending_question" class="agent-plan__ask">
        <strong>Domanda:</strong> {{ run.pending_question }}
      </div>
      <div v-if="run.error && run.state !== 'done'" class="agent-plan__error">
        {{ run.error }}
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-plan {
  --agent-accent: rgb(120 160 230);
  margin: 6px 0 4px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.03);
  font-size: 12px;
  color: rgba(255, 255, 255, 0.85);
}

.agent-plan--running,
.agent-plan--planning {
  border-color: rgba(120, 160, 230, 0.35);
  background: rgba(120, 160, 230, 0.06);
}

.agent-plan--failed,
.agent-plan--cancelled {
  border-color: rgba(220, 110, 110, 0.35);
  background: rgba(220, 110, 110, 0.05);
}

.agent-plan--done {
  border-color: rgba(110, 200, 140, 0.25);
}

.agent-plan--asked_user {
  border-color: rgba(230, 190, 110, 0.35);
  background: rgba(230, 190, 110, 0.05);
}

.agent-plan__head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  background: transparent;
  border: 0;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.agent-plan__head:hover {
  background: rgba(255, 255, 255, 0.04);
}

.agent-plan__badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(120, 160, 230, 0.18);
  color: var(--agent-accent);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.agent-plan__title {
  flex: 1;
  font-weight: 500;
}

.agent-plan__meta {
  font-size: 11px;
  opacity: 0.75;
}

.agent-plan__chevron {
  transition: transform 120ms ease;
}

.agent-plan__chevron--open {
  transform: rotate(180deg);
}

.agent-plan__body {
  padding: 0 12px 10px;
  display: grid;
  grid-template-rows: 1fr;
  transition: grid-template-rows 160ms ease, padding 160ms ease;
  overflow: hidden;
}

.agent-plan__body--collapsed {
  grid-template-rows: 0fr;
  padding-top: 0;
  padding-bottom: 0;
}

.agent-plan__body > * {
  min-height: 0;
}

.agent-plan__goal {
  margin: 4px 0 8px;
  font-style: italic;
  opacity: 0.8;
}

.agent-plan__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.agent-plan__step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 4px 0;
}

.agent-plan__step--pending {
  opacity: 0.55;
}

.agent-plan__step--skipped {
  opacity: 0.4;
  text-decoration: line-through;
}

.agent-plan__step-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.85);
}

.agent-plan__step--done .agent-plan__step-icon {
  background: rgba(110, 200, 140, 0.18);
  color: rgb(140, 220, 170);
}

.agent-plan__step--failed .agent-plan__step-icon {
  background: rgba(220, 110, 110, 0.18);
  color: rgb(240, 140, 140);
}

.agent-plan__step--retry .agent-plan__step-icon {
  background: rgba(230, 190, 110, 0.18);
  color: rgb(240, 200, 130);
}

.agent-plan__step--in_progress .agent-plan__step-icon {
  background: rgba(120, 160, 230, 0.2);
  color: var(--agent-accent);
}

.agent-plan__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.45;
}

.agent-plan__spinner {
  width: 10px;
  height: 10px;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: agent-plan-spin 0.9s linear infinite;
}

@keyframes agent-plan-spin {
  to {
    transform: rotate(360deg);
  }
}

.agent-plan__step-text {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 6px;
  line-height: 1.45;
}

.agent-plan__step-num {
  opacity: 0.55;
  font-variant-numeric: tabular-nums;
}

.agent-plan__step-tool {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 11px;
  opacity: 0.7;
  color: var(--agent-accent);
}

.agent-plan__step-verdict {
  flex-basis: 100%;
  margin-left: 14px;
  font-size: 11px;
  opacity: 0.7;
  font-style: italic;
}

.agent-plan__empty {
  margin: 4px 0;
  opacity: 0.6;
  font-style: italic;
}

.agent-plan__ask {
  margin-top: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(230, 190, 110, 0.1);
  border: 1px solid rgba(230, 190, 110, 0.25);
}

.agent-plan__error {
  margin-top: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(220, 110, 110, 0.1);
  border: 1px solid rgba(220, 110, 110, 0.25);
  color: rgb(240, 160, 160);
  font-size: 11px;
}
</style>
