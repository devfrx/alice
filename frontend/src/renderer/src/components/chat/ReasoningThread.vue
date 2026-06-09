<script setup lang="ts">
/**
 * ReasoningThread.vue — Unified per-turn agent-activity timeline.
 *
 * Replaces the old AgentActivityCard AND the live ToolExecutionIndicator with
 * a single accent-rail thread of nodes (tools, sub-agents, interactions) folded
 * by the `agentRun` store. While running it shows a live, length-capped trace;
 * when finished it collapses to a re-expandable one-line summary. Renders
 * nothing when no run is in flight (top-level v-if in the consumer).
 */
import { computed, ref } from 'vue'

import { useAgentRunStore } from '../../stores/agentRun'
import type { InteractionActivity, InteractionOutcome, ToolActivity } from '../../types/turn'

const agentRunStore = useAgentRunStore()
const run = computed(() => agentRunStore.currentRun)

const isRunning = computed(() => run.value?.status === 'running')
/** Fresh pending run (send→turn.started gap): no budget yet. */
const isPending = computed(
  () => isRunning.value && (run.value?.maxSteps ?? 0) === 0 && (run.value?.tools.length ?? 0) === 0
)

/** Collapsed/expanded state for the FINISHED summary (re-expandable). */
const expanded = ref(false)

type Node =
  | { kind: 'tool'; seq: number; data: ToolActivity }
  | { kind: 'interaction'; seq: number; data: InteractionActivity }

/** Tools + interactions merged into one chronological node list. */
const nodes = computed<Node[]>(() => {
  const r = run.value
  if (!r) return []
  const t: Node[] = r.tools.map((d) => ({ kind: 'tool', seq: d.seq, data: d }))
  const i: Node[] = r.interactions.map((d) => ({ kind: 'interaction', seq: d.seq, data: d }))
  return [...t, ...i].sort((a, b) => a.seq - b.seq)
})

/** While running, keep only the most recent few nodes; older fold into a pill. */
const VISIBLE_RUNNING = 3
const visibleNodes = computed<Node[]>(() =>
  isRunning.value ? nodes.value.slice(-VISIBLE_RUNNING) : nodes.value
)
const foldedCount = computed(() =>
  isRunning.value ? Math.max(0, nodes.value.length - VISIBLE_RUNNING) : 0
)

/** Compact token formatter: 10777 -> "10.7k". */
function fmtTok(n: number): string {
  return n >= 1000 ? `${Math.round(n / 100) / 10}k` : String(n)
}

const summary = computed(() => {
  const r = run.value
  if (!r) return ''
  return `${r.step} passi · ${r.tools.length} strumenti · ↑${fmtTok(r.inputTokens)} ↓${fmtTok(r.outputTokens)}`
})

const OUTCOME_GLYPH: Record<InteractionOutcome, string> = {
  approved: 'approvato',
  rejected: 'rifiutato',
  answered: 'risposto',
  executed: 'eseguito',
  failed: 'fallito',
  cancelled: 'annullato',
  timeout: 'scaduto'
}
const KIND_LABEL: Record<InteractionActivity['kind'], string> = {
  tool_confirmation: 'conferma',
  client_tool_call: 'client',
  ask_user: 'domanda'
}
function outcomeTone(o: InteractionOutcome | undefined): 'ok' | 'err' | 'muted' {
  if (o === 'approved' || o === 'answered' || o === 'executed') return 'ok'
  if (o === 'rejected' || o === 'failed') return 'err'
  return 'muted'
}
</script>

<template>
  <div v-if="run" class="rt" role="group" aria-label="Attività dell'agente">
    <!-- RUNNING: live trace -->
    <div v-if="isRunning" class="rt__rail">
      <div class="rt__node rt__node--head">
        <span class="rt__ttl">Ragionamento</span>
        <span class="rt__sum">{{
          isPending ? 'avvio…' : `passo ${run.step}/${run.maxSteps}`
        }}</span>
      </div>

      <button v-if="foldedCount > 0" class="rt__fold" type="button">
        +{{ foldedCount }} azioni precedenti
      </button>

      <template v-for="n in visibleNodes" :key="n.data.executionId">
        <div
          v-if="n.kind === 'tool'"
          class="rt__node"
          :class="{
            'rt__node--ok': n.data.status === 'success',
            'rt__node--err': n.data.status === 'error',
            'rt__node--act': n.data.status === 'running'
          }"
        >
          <span class="rt__tool">{{ n.data.toolName }}</span>
          <span
            class="rt__glyph"
            :class="{
              ok: n.data.status === 'success',
              err: n.data.status === 'error',
              run: n.data.status === 'running'
            }"
          >
            {{ n.data.status === 'success' ? '✓' : n.data.status === 'error' ? 'errore' : '●' }}
          </span>
        </div>
        <div
          v-else
          class="rt__node"
          :class="{
            'rt__node--ok': outcomeTone(n.data.outcome) === 'ok',
            'rt__node--err': outcomeTone(n.data.outcome) === 'err',
            'rt__node--act': n.data.status === 'pending',
            'rt__node--io': n.data.status !== 'pending'
          }"
        >
          <span class="rt__tool"
            ><span class="rt__io">{{ KIND_LABEL[n.data.kind] }} ·</span>
            {{ n.data.toolName ?? '' }}</span
          >
          <span v-if="n.data.status === 'pending'" class="rt__glyph run">in attesa…</span>
          <span v-else class="rt__glyph" :class="outcomeTone(n.data.outcome)">{{
            n.data.outcome ? OUTCOME_GLYPH[n.data.outcome] : '•'
          }}</span>
        </div>
      </template>
    </div>

    <!-- FINISHED: collapsed summary, re-expandable -->
    <div v-else class="rt__rail">
      <button
        class="rt__node rt__node--ok rt__node--toggle"
        type="button"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        <span class="rt__ttl">Completato</span>
        <span class="rt__sum"
          >{{ summary }}
          <span class="rt__chev" :class="{ 'rt__chev--open': expanded }">▸</span></span
        >
      </button>

      <template v-if="expanded">
        <template v-for="n in nodes" :key="n.data.executionId">
          <div
            v-if="n.kind === 'tool'"
            class="rt__node"
            :class="{
              'rt__node--ok': n.data.status === 'success',
              'rt__node--err': n.data.status === 'error'
            }"
          >
            <span class="rt__tool">{{ n.data.toolName }}</span>
            <span
              class="rt__glyph"
              :class="{ ok: n.data.status === 'success', err: n.data.status === 'error' }"
            >
              {{ n.data.status === 'error' ? 'errore' : '✓' }}
            </span>
          </div>
          <div
            v-else
            class="rt__node"
            :class="{
              'rt__node--ok': outcomeTone(n.data.outcome) === 'ok',
              'rt__node--err': outcomeTone(n.data.outcome) === 'err',
              'rt__node--io': true
            }"
          >
            <span class="rt__tool"
              ><span class="rt__io">{{ KIND_LABEL[n.data.kind] }} ·</span>
              {{ n.data.toolName ?? '' }}</span
            >
            <span class="rt__glyph" :class="outcomeTone(n.data.outcome)">{{
              n.data.outcome ? OUTCOME_GLYPH[n.data.outcome] : '•'
            }}</span>
          </div>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.rt {
  margin-top: var(--space-2);
}

.rt__rail {
  border-left: 2px solid var(--border);
  padding: 1px 0 1px var(--space-3);
  margin-left: var(--space-1);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.rt__node {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  position: relative;
  min-width: 0;
  background: none;
  border: none;
  padding: 0;
  text-align: left;
  font-family: var(--font-sans);
}

.rt__node::before {
  content: '';
  position: absolute;
  left: calc(-1 * var(--space-3) - 5px);
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--surface-3);
  border: 2px solid var(--surface-0);
}

.rt__node--head::before {
  background: var(--accent);
}
.rt__node--ok::before {
  background: var(--success);
}
.rt__node--err::before {
  background: var(--danger);
}
.rt__node--io::before {
  background: var(--surface-0);
  border-color: var(--border-hover, var(--border));
}
.rt__node--act::before {
  background: var(--accent);
  box-shadow: 0 0 8px var(--accent-glow);
  animation: rtPulse 1.4s ease-in-out infinite;
}

.rt__node--act .rt__tool {
  position: relative;
  overflow: hidden;
}
.rt__node--act .rt__tool::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent,
    color-mix(in srgb, var(--accent) 18%, transparent),
    transparent
  );
  animation: rtShim 1.8s ease-in-out infinite;
}

.rt__node--toggle {
  cursor: pointer;
  width: 100%;
}

.rt__ttl {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
}

.rt__sum {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  white-space: nowrap;
}

.rt__chev {
  display: inline-block;
  transition: transform var(--transition-fast);
}
.rt__chev--open {
  transform: rotate(90deg);
}

.rt__fold {
  position: relative;
  background: none;
  border: none;
  padding: 0;
  text-align: left;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  cursor: pointer;
}
.rt__fold::before {
  content: '⋯';
  position: absolute;
  left: calc(-1 * var(--space-3) - 4px);
  top: -3px;
  color: var(--text-muted);
}
.rt__fold:hover {
  color: var(--text-secondary);
}

.rt__tool {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.rt__io {
  color: var(--text-muted);
}

.rt__glyph {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  white-space: nowrap;
  flex-shrink: 0;
}
.rt__glyph.ok {
  color: var(--success);
}
.rt__glyph.err {
  color: var(--danger);
}
.rt__glyph.run {
  color: var(--accent);
}
.rt__glyph.muted {
  color: var(--text-muted);
}

@keyframes rtPulse {
  0%,
  100% {
    opacity: 0.45;
  }
  50% {
    opacity: 1;
  }
}
@keyframes rtShim {
  0% {
    transform: translateX(-100%);
  }
  100% {
    transform: translateX(100%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .rt__node--act::before,
  .rt__node--act .rt__tool::after,
  .rt__chev {
    animation: none;
    transition: none;
  }
}
</style>
