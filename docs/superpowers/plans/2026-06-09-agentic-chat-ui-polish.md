# Agentic Chat UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the agentic chat UI — replace the boxed activity card with a persistent "Reasoning thread", restructure the input bar into a hierarchical labelled-segments layout, refine thinking/streaming motion, flatten the assistant background, and add edge fades — all without backend/contract changes.

**Architecture:** Frontend-only (Vue 3 `<script setup>` + Pinia). The canonical `agentRun` store gains an event sequence + a pending-turn reset; a new `ReasoningThread.vue` reads the store and is mounted once per chat surface. The streaming/thinking components lose their old indicators and gain the new motion language. Input-bar restructure is template+CSS in `ChatInput.vue` with container-query breakpoints.

**Tech Stack:** Vue 3 (Composition API, `<script setup lang="ts">`), Pinia, Vitest (store/unit tests only — the repo does not unit-test `.vue` components), scoped CSS with the existing `theme.css` design tokens.

**Testing note (codebase convention):** This repo tests stores/utils with Vitest and verifies UI via `npm run typecheck` + `npm run lint` + manual run (per `CLAUDE.md`). TDD applies to the `agentRun` store logic (Task 2). Visual components are verified by typecheck/lint + the manual checklist in Task 14 — do **not** invent a `.vue` component-test harness the repo doesn't use.

**Reference:** Design spec at `docs/superpowers/specs/2026-06-09-agentic-chat-ui-polish-design.md`.

---

## File Structure

**Created**
- `frontend/src/renderer/src/components/chat/ReasoningThread.vue` — the unified agent-activity timeline (replaces `AgentActivityCard` and the live tool indicator).

**Modified**
- `frontend/src/renderer/src/types/turn.ts` — add `seq` to `ToolActivity` / `InteractionActivity`.
- `frontend/src/renderer/src/stores/agentRun.ts` — assign `seq`; add `beginPendingTurn()` + pending getter.
- `frontend/src/renderer/src/stores/agentRun.spec.ts` — tests for seq + pending.
- `frontend/src/renderer/src/composables/useChat.ts` — call `beginPendingTurn()` on send/edit/branch.
- `frontend/src/renderer/src/components/chat/StreamingIndicator.vue` — drop old card+indicator; reorder; new cursor.
- `frontend/src/renderer/src/components/canvas/ChatPanel.vue` — mount `ReasoningThread`; add edge fades.
- `frontend/src/renderer/src/components/chat/ThinkingSection.vue` — shimmer label + traveling rail pulse.
- `frontend/src/renderer/src/components/assistant/AmbientBackground.vue` — strip busy layers; keep orb glow.
- `frontend/src/renderer/src/components/assistant/AssistantResponse.vue` — new thinking/cursor + mount `ReasoningThread`.
- `frontend/src/renderer/src/views/AssistantView.vue` — unify/strengthen edge fade.
- `frontend/src/renderer/src/components/chat/ChatInput.vue` — labelled-segments restructure + responsive ladder.
- `frontend/src/renderer/src/components/chat/ChatToolControls.vue` — add a label class for narrow-mode hiding.
- `frontend/src/renderer/src/assets/styles/theme.css` — shared edge-fade + orb-glow tokens.

**Deleted**
- `frontend/src/renderer/src/components/chat/AgentActivityCard.vue`
- `frontend/src/renderer/src/components/chat/ToolExecutionIndicator.vue` (only after confirming no remaining importers).

---

## Task 1: Shared design tokens

**Files:**
- Modify: `frontend/src/renderer/src/assets/styles/theme.css`

- [ ] **Step 1: Add edge-fade + orb-glow tokens**

Find the dark-theme `:root` token block (around line 21 where `--surface-0` is defined) and add these tokens inside it, after the surface tokens:

```css
  /* Chat edge fades (used by ChatPanel + AssistantView message columns) */
  --chat-edge-fade-top: 20px;
  --chat-edge-fade-bottom: 28px;
  /* Faint glow behind the assistant orb (state colour mixed at low alpha) */
  --orb-glow-alpha: 14%;
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend; npm run typecheck`
Expected: PASS (CSS-only change; no TS impact).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/assets/styles/theme.css
git commit -m "feat(theme): add chat edge-fade + orb-glow tokens"
```

---

## Task 2: `agentRun` store — event sequence + pending-turn reset (TDD)

**Files:**
- Modify: `frontend/src/renderer/src/types/turn.ts`
- Modify: `frontend/src/renderer/src/stores/agentRun.ts`
- Test: `frontend/src/renderer/src/stores/agentRun.spec.ts`

- [ ] **Step 1: Add `seq` to the activity view-models**

In `types/turn.ts`, add a `seq` field to both interfaces (it orders tools vs interactions in one timeline):

```ts
export interface ToolActivity {
  executionId: string
  toolName: string
  args: Record<string, unknown>
  status: 'running' | 'success' | 'error'
  /** Monotonic insertion order within the run (interleaves tools + interactions). */
  seq: number
  result?: string
  contentType?: string
  artifactId?: string
}

export interface InteractionActivity {
  executionId: string
  kind: InteractionKind
  toolName?: string
  status: 'pending' | 'resolved'
  /** Monotonic insertion order within the run (interleaves tools + interactions). */
  seq: number
  outcome?: InteractionOutcome
}
```

- [ ] **Step 2: Write failing tests for seq + pending**

In `agentRun.spec.ts`, add these tests (reuse the existing `started`/`toolCall`/etc. helpers in that file; if a helper is missing, construct the frame inline matching `types/turn.ts`):

```ts
it('assigns monotonic seq across interleaved tools and interactions', () => {
  const s = useAgentRunStore()
  s.applyTurnStarted(started('t1'))
  s.applyToolCall({ type: 'tool.call', turn_id: 't1', execution_id: 'e1', tool_name: 'web_search', args: {} })
  s.applyInteractionRequested({ type: 'interaction.requested', turn_id: 't1', execution_id: 'e2', kind: 'tool_confirmation', tool_name: 'write_file' })
  s.applyToolCall({ type: 'tool.call', turn_id: 't1', execution_id: 'e3', tool_name: 'read_file', args: {} })
  const run = s.runByTurnId('t1')!
  expect(run.tools.find((t) => t.executionId === 'e1')!.seq).toBe(0)
  expect(run.interactions.find((i) => i.executionId === 'e2')!.seq).toBe(1)
  expect(run.tools.find((t) => t.executionId === 'e3')!.seq).toBe(2)
})

it('beginPendingTurn shows a fresh pending run, not the prior finished one', () => {
  const s = useAgentRunStore()
  s.applyTurnStarted(started('t1'))
  s.applyTurnFinished({ type: 'turn.finished', turn_id: 't1', finish_reason: 'stop', input_tokens: 10, output_tokens: 5, steps: 1 })
  expect(s.currentRun!.status).toBe('finished')
  s.beginPendingTurn()
  expect(s.currentRun!.status).toBe('running')
  expect(s.currentRun!.step).toBe(0)
  expect(s.currentRun!.tools).toEqual([])
  expect(s.currentRun!.finishReason).toBeNull()
})

it('applyTurnStarted clears the pending flag', () => {
  const s = useAgentRunStore()
  s.beginPendingTurn()
  expect(s.currentRun!.status).toBe('running')
  s.applyTurnStarted(started('t2'))
  expect(s.currentTurnId).toBe('t2')
  expect(s.currentRun!.turnId).toBe('t2')
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend; npx vitest run src/renderer/src/stores/agentRun.spec.ts`
Expected: FAIL — `beginPendingTurn` is not a function; `seq` is `undefined`.

- [ ] **Step 4: Implement seq assignment + pending state**

In `agentRun.ts`:

(a) Add a stable pending run constant near the top of the store setup (after imports):

```ts
const PENDING_RUN: AgentRun = Object.freeze({
  turnId: '__pending__',
  conversationId: '',
  status: 'running',
  step: 0,
  maxSteps: 0,
  tools: [],
  interactions: [],
  inputTokens: 0,
  outputTokens: 0,
  toolCalls: 0,
  finishReason: null,
}) as AgentRun
```

(b) Add pending state next to `currentTurnId`:

```ts
const pendingTurn = ref(false)
```

(c) Update the `currentRun` getter:

```ts
const currentRun = computed<AgentRun | null>(() => {
  if (pendingTurn.value) return PENDING_RUN
  return currentTurnId.value ? runs.value[currentTurnId.value] ?? null : null
})
```

(d) In `applyTurnStarted`, clear pending (add as the first line of the function body):

```ts
pendingTurn.value = false
```

(e) Add the `seq` at each append site. For `applyToolCall`:

```ts
const activity: ToolActivity = {
  executionId: msg.execution_id,
  toolName: msg.tool_name,
  args: msg.args,
  status: 'running',
  seq: run.tools.length + run.interactions.length,
}
```

For the create-if-absent branch in `applyToolResult`:

```ts
const activity: ToolActivity = {
  executionId: msg.execution_id,
  toolName: msg.tool_name,
  args: {},
  status,
  seq: run.tools.length + run.interactions.length,
  result: msg.result,
  contentType: msg.content_type,
  artifactId: msg.artifact_id,
}
```

For `applyInteractionRequested`:

```ts
const activity: InteractionActivity = {
  executionId: msg.execution_id,
  kind: msg.kind,
  toolName: msg.tool_name,
  status: 'pending',
  seq: run.tools.length + run.interactions.length,
}
```

For the create-if-absent branch in `applyInteractionResolved`:

```ts
const activity: InteractionActivity = {
  executionId: msg.execution_id,
  kind: msg.kind,
  status: 'resolved',
  outcome: msg.outcome,
  seq: run.tools.length + run.interactions.length,
}
```

(f) Add `beginPendingTurn` and reset pending; export both new members. In `reset()` add `pendingTurn.value = false`. Add the function:

```ts
/** Mark a new turn as imminent so the live thread shows a fresh "starting"
 *  state instead of the previous (finished) run during the send→turn.started gap. */
function beginPendingTurn(): void {
  pendingTurn.value = true
}
```

In the returned object add: `pendingTurn,` (state) and `beginPendingTurn,` (action).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend; npx vitest run src/renderer/src/stores/agentRun.spec.ts`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 6: Typecheck + commit**

Run: `cd frontend; npm run typecheck`
Expected: PASS.

```bash
git add frontend/src/renderer/src/types/turn.ts frontend/src/renderer/src/stores/agentRun.ts frontend/src/renderer/src/stores/agentRun.spec.ts
git commit -m "feat(agentRun): event seq + pending-turn reset for the reasoning thread"
```

---

## Task 3: `ReasoningThread.vue` component

**Files:**
- Create: `frontend/src/renderer/src/components/chat/ReasoningThread.vue`

- [ ] **Step 1: Create the component**

```vue
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
const isPending = computed(() => isRunning.value && (run.value?.maxSteps ?? 0) === 0 && (run.value?.tools.length ?? 0) === 0)

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
  approved: 'approvato', rejected: 'rifiutato', answered: 'risposto',
  executed: 'eseguito', failed: 'fallito', cancelled: 'annullato', timeout: 'scaduto',
}
const KIND_LABEL: Record<InteractionActivity['kind'], string> = {
  tool_confirmation: 'conferma', client_tool_call: 'client', ask_user: 'domanda',
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
        <span class="rt__sum">{{ isPending ? 'avvio…' : `passo ${run.step}/${run.maxSteps}` }}</span>
      </div>

      <button v-if="foldedCount > 0" class="rt__fold" type="button">
        +{{ foldedCount }} azioni precedenti
      </button>

      <template v-for="n in visibleNodes" :key="n.data.executionId">
        <div v-if="n.kind === 'tool'" class="rt__node"
          :class="{ 'rt__node--ok': n.data.status === 'success', 'rt__node--err': n.data.status === 'error', 'rt__node--act': n.data.status === 'running' }">
          <span class="rt__tool">{{ n.data.toolName }}</span>
          <span class="rt__glyph"
            :class="{ ok: n.data.status === 'success', err: n.data.status === 'error', run: n.data.status === 'running' }">
            {{ n.data.status === 'success' ? '✓' : n.data.status === 'error' ? 'errore' : '●' }}
          </span>
        </div>
        <div v-else class="rt__node"
          :class="{ 'rt__node--ok': outcomeTone(n.data.outcome) === 'ok', 'rt__node--err': outcomeTone(n.data.outcome) === 'err', 'rt__node--act': n.data.status === 'pending', 'rt__node--io': n.data.status !== 'pending' }">
          <span class="rt__tool"><span class="rt__io">{{ KIND_LABEL[n.data.kind] }} ·</span> {{ n.data.toolName ?? '' }}</span>
          <span v-if="n.data.status === 'pending'" class="rt__glyph run">in attesa…</span>
          <span v-else class="rt__glyph" :class="outcomeTone(n.data.outcome)">{{ n.data.outcome ? OUTCOME_GLYPH[n.data.outcome] : '•' }}</span>
        </div>
      </template>
    </div>

    <!-- FINISHED: collapsed summary, re-expandable -->
    <div v-else class="rt__rail">
      <button class="rt__node rt__node--ok rt__node--toggle" type="button" :aria-expanded="expanded"
        @click="expanded = !expanded">
        <span class="rt__ttl">Completato</span>
        <span class="rt__sum">{{ summary }} <span class="rt__chev" :class="{ 'rt__chev--open': expanded }">▸</span></span>
      </button>

      <template v-if="expanded">
        <template v-for="n in nodes" :key="n.data.executionId">
          <div v-if="n.kind === 'tool'" class="rt__node"
            :class="{ 'rt__node--ok': n.data.status === 'success', 'rt__node--err': n.data.status === 'error' }">
            <span class="rt__tool">{{ n.data.toolName }}</span>
            <span class="rt__glyph" :class="{ ok: n.data.status === 'success', err: n.data.status === 'error' }">
              {{ n.data.status === 'error' ? 'errore' : '✓' }}
            </span>
          </div>
          <div v-else class="rt__node"
            :class="{ 'rt__node--ok': outcomeTone(n.data.outcome) === 'ok', 'rt__node--err': outcomeTone(n.data.outcome) === 'err', 'rt__node--io': true }">
            <span class="rt__tool"><span class="rt__io">{{ KIND_LABEL[n.data.kind] }} ·</span> {{ n.data.toolName ?? '' }}</span>
            <span class="rt__glyph" :class="outcomeTone(n.data.outcome)">{{ n.data.outcome ? OUTCOME_GLYPH[n.data.outcome] : '•' }}</span>
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

.rt__node--head::before { background: var(--accent); }
.rt__node--ok::before { background: var(--success); }
.rt__node--err::before { background: var(--danger); }
.rt__node--io::before { background: var(--surface-0); border-color: var(--border-hover, var(--border)); }
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
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--accent) 18%, transparent), transparent);
  animation: rtShim 1.8s ease-in-out infinite;
}

.rt__toggle { cursor: pointer; width: 100%; }

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
.rt__chev--open { transform: rotate(90deg); }

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
.rt__fold:hover { color: var(--text-secondary); }

.rt__tool {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.rt__io { color: var(--text-muted); }

.rt__glyph {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  white-space: nowrap;
  flex-shrink: 0;
}
.rt__glyph.ok { color: var(--success); }
.rt__glyph.err { color: var(--danger); }
.rt__glyph.run { color: var(--accent); }
.rt__glyph.muted { color: var(--text-muted); }

@keyframes rtPulse { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
@keyframes rtShim { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }

@media (prefers-reduced-motion: reduce) {
  .rt__node--act::before,
  .rt__node--act .rt__tool::after,
  .rt__chev { animation: none; transition: none; }
}
</style>
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend; npm run typecheck`
Expected: PASS. (If `--accent-glow` / `--border-hover` are undefined, the `var(... , fallback)` covers `--border-hover`; `--accent-glow` is already used in the codebase — verify it exists in `theme.css`, else fall back to `var(--accent)`.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/chat/ReasoningThread.vue
git commit -m "feat(chat): ReasoningThread — unified agent-activity timeline"
```

---

## Task 4: Wire the pending-turn reset on new turns

**Files:**
- Modify: `frontend/src/renderer/src/composables/useChat.ts`

- [ ] **Step 1: Call `beginPendingTurn()` in `sendMessage`**

In `sendMessage`, immediately after the optimistic `store.addUserMessage(trimmed, uploaded)` line (~line 467), add:

```ts
    // Reset the live agent thread so it shows a fresh "starting" state instead
    // of the previous (finished) run during the send→turn.started gap.
    agentRunStore.beginPendingTurn()
```

- [ ] **Step 2: Call it in `editMessage` and `branchConversation`**

In `editMessage`, after the optimistic edited-user-message is added (the `store.add*`/push that inserts the edited message, before `wsManager.send`), add the same line:

```ts
    agentRunStore.beginPendingTurn()
```

If `branchConversation` (in `stores/chat.ts`, called from views) triggers a regeneration turn, also call `useAgentRunStore().beginPendingTurn()` at its send point. If branching does NOT start a new turn, skip it. Verify by reading `branchConversation` before editing.

- [ ] **Step 3: Typecheck**

Run: `cd frontend; npm run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/renderer/src/composables/useChat.ts
git commit -m "fix(chat): fresh reasoning thread on new turn (kills stale 'green 1/26' leak)"
```

---

## Task 5: StreamingIndicator — drop old indicators, reorder, new cursor

**Files:**
- Modify: `frontend/src/renderer/src/components/chat/StreamingIndicator.vue`

- [ ] **Step 1: Remove old imports + usages**

Remove the imports of `ToolExecutionIndicator` and `AgentActivityCard` (lines 16–17) and their template usages (`<ToolExecutionIndicator …>` line 54 and `<AgentActivityCard />` line 57). The `useChatStore` import is now unused here — remove it and the `const chatStore = useChatStore()` line. (The thread now lives in `ChatPanel`, mounted once at the end of the thread.)

- [ ] **Step 2: Keep thinking + content; ensure content order**

The template body becomes (thinking-state, thinking section, content, cursor — no card, no tool indicator):

```vue
  <div class="bubble-row row--assistant">
    <div class="streaming-bubble">
      <div v-if="thinkingContent && !content" class="streaming-bubble__thinking-state">
        <span class="streaming-bubble__thinking-label streaming-bubble__thinking-label--shimmer">Ragionamento…</span>
      </div>

      <ThinkingSection v-if="thinkingContent" :thinking-html="thinkingHtml" :initial-collapsed="true"
        :auto-expand="true" :content-length="thinkingContent.length">
        <span v-if="!content" class="streaming-bubble__cursor" />
      </ThinkingSection>

      <Transition name="content-fade">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div v-if="content" class="streaming-bubble__content" v-html="htmlContent" @click="handleCodeBlockClick" />
      </Transition>
      <span v-if="content || !thinkingContent" class="streaming-bubble__cursor" />
    </div>
  </div>
```

(The old spinner in the thinking-state row is replaced by a shimmer label — see Task 8 for `--shimmer`.)

- [ ] **Step 3: Replace the cursor with the shimmer-tail caret**

Replace the `.streaming-bubble__cursor` style block (lines ~129–137 and the `@keyframes cursorBlink`) with the refined glowing caret (shimmer-tail realised as a glowing "comet" caret — a full-line background sweep is impractical over rendered markdown; this is the polished trailing-cursor interpretation flagged in the spec):

```css
.streaming-bubble__cursor {
  display: inline-block;
  width: 2px;
  height: 1.05em;
  margin-left: 3px;
  vertical-align: text-bottom;
  border-radius: 1px;
  background: var(--accent);
  /* leftward fading "tail" + soft glow */
  box-shadow: -9px 0 10px -3px var(--accent-glow), 0 0 6px var(--accent-glow);
  animation: cursorPulse 1.4s ease-in-out infinite;
}

@keyframes cursorPulse {
  0%, 100% { opacity: 0.95; }
  50% { opacity: 0.25; }
}
```

Update the reduced-motion block to freeze it:

```css
@media (prefers-reduced-motion: reduce) {
  .streaming-bubble__cursor { animation: none; opacity: 1; box-shadow: 0 0 4px var(--accent-glow); }
  .content-fade-enter-active { transition: none; }
}
```

- [ ] **Step 4: Add the shimmer thinking-label style**

Add to the `<style scoped>` (full rule provided so the engineer needn't cross-reference):

```css
.streaming-bubble__thinking-label--shimmer {
  font-size: var(--text-xs);
  background: linear-gradient(90deg, var(--text-muted) 28%, var(--accent) 50%, var(--text-muted) 72%);
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: thinkingShimmer 2.3s linear infinite;
}
@keyframes thinkingShimmer { 0% { background-position: 170% 0; } 100% { background-position: -70% 0; } }
@media (prefers-reduced-motion: reduce) {
  .streaming-bubble__thinking-label--shimmer { animation: none; color: var(--text-muted); -webkit-text-fill-color: var(--text-muted); }
}
```

- [ ] **Step 5: Typecheck + lint**

Run: `cd frontend; npm run typecheck; npm run lint`
Expected: PASS (no unused imports remain).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/renderer/src/components/chat/StreamingIndicator.vue
git commit -m "refactor(chat): StreamingIndicator drops card+tool-indicator; shimmer cursor"
```

---

## Task 6: ChatPanel — mount the persistent thread + edge fades

**Files:**
- Modify: `frontend/src/renderer/src/components/canvas/ChatPanel.vue`

- [ ] **Step 1: Import and mount `ReasoningThread`**

Add the import next to the other chat imports (after line 18):

```ts
import ReasoningThread from '../chat/ReasoningThread.vue'
```

In the template, inside `.chat-panel__thread`, place the thread AFTER the streaming block and before `AskUserPrompt` so it sits under everything (it self-guards on `currentRun`):

```vue
        <div v-if="chatStore.isStreamingCurrentConversation" class="chat-panel__streaming">
          <StreamingIndicator
            :content="chatStore.currentStreamContent"
            :thinking-content="chatStore.currentThinkingContent"
          />
        </div>

        <ReasoningThread class="chat-panel__thread-activity" />

        <AskUserPrompt … />
```

- [ ] **Step 2: Add edge fades to the scroll container**

In `<style scoped>`, extend `.chat-panel__messages` (the `overflow-y:auto` container, ~line 277) with a mask fade using the Task 1 tokens:

```css
.chat-panel__messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4) var(--space-2);
  scroll-behavior: smooth;
  -webkit-mask-image: linear-gradient(to bottom,
    transparent 0, black var(--chat-edge-fade-top),
    black calc(100% - var(--chat-edge-fade-bottom)), transparent 100%);
  mask-image: linear-gradient(to bottom,
    transparent 0, black var(--chat-edge-fade-top),
    black calc(100% - var(--chat-edge-fade-bottom)), transparent 100%);
}
```

Add a small top-gap so the persisted thread doesn't crowd the last message:

```css
.chat-panel__thread-activity {
  margin-top: var(--space-2);
}
```

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend; npm run typecheck; npm run lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/renderer/src/components/canvas/ChatPanel.vue
git commit -m "feat(workspace): persistent reasoning thread + top/bottom edge fades"
```

---

## Task 7: Delete AgentActivityCard; retire ToolExecutionIndicator

**Files:**
- Delete: `frontend/src/renderer/src/components/chat/AgentActivityCard.vue`
- Delete: `frontend/src/renderer/src/components/chat/ToolExecutionIndicator.vue` (conditional)

- [ ] **Step 1: Confirm there are no remaining importers**

Run (search the renderer for usages):
```bash
cd frontend; npx --yes rg -n "AgentActivityCard|ToolExecutionIndicator" src/renderer/src || echo "none"
```
Expected after Tasks 5 & 10: the only hits are the files themselves (and Task 10 must already have removed the `AssistantResponse` usage of `ToolExecutionIndicator`). If `AssistantResponse.vue` still imports `ToolExecutionIndicator`, do Task 10 first.

- [ ] **Step 2: Delete the files**

```bash
git rm frontend/src/renderer/src/components/chat/AgentActivityCard.vue
git rm frontend/src/renderer/src/components/chat/ToolExecutionIndicator.vue
```

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend; npm run typecheck; npm run lint`
Expected: PASS (no dangling imports).

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(chat): remove AgentActivityCard + ToolExecutionIndicator (folded into ReasoningThread)"
```

---

## Task 8: ThinkingSection — shimmer label + traveling rail pulse

**Files:**
- Modify: `frontend/src/renderer/src/components/chat/ThinkingSection.vue`

- [ ] **Step 1: Add the shimmer label + rail-pulse markup**

In the template, the toggle label gets a shimmer class while streaming, and a rail-pulse element is added inside the body. Change the `.thinking-section__label` span and add a pulse element on the body's left rail. Replace the toggle/body markup with:

```vue
  <div class="thinking-section" :class="{ 'thinking-section--streaming': isStreaming && !collapsed }" role="region"
    aria-label="Ragionamento del modello">
    <button class="thinking-section__toggle" :aria-expanded="!collapsed" aria-label="Mostra/nascondi ragionamento"
      @click="collapsed = !collapsed">
      <AppIcon name="lightbulb" :size="14" class="thinking-section__icon" />
      <span class="thinking-section__label" :class="{ 'thinking-section__label--shimmer': isStreaming }">Ragionamento</span>
      <span v-if="collapsed && badgeText" class="thinking-section__badge">{{ badgeText }} caratteri</span>
      <AppIcon name="chevron-down" :size="12" class="thinking-section__chevron"
        :class="{ 'thinking-section__chevron--collapsed': collapsed }" />
    </button>
    <div class="thinking-section__body" :class="{ 'thinking-section__body--collapsed': collapsed }">
      <span v-if="isStreaming && !collapsed" class="thinking-section__railpulse" aria-hidden="true" />
      <div class="thinking-section__inner">
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div class="thinking-section__content" v-html="thinkingHtml" @click="handleCodeBlockClick" />
        <slot />
      </div>
    </div>
    <div class="thinking-section__separator" />
  </div>
```

(The old `thinking-section__streaming-text` "pensando..." span is removed — the shimmer label conveys the active state.)

- [ ] **Step 2: Add the styles**

The body must be `position: relative` for the rail pulse. Update `.thinking-section__body` to add `position: relative;`, then append:

```css
.thinking-section__label--shimmer {
  background: linear-gradient(90deg, var(--text-secondary) 28%, var(--accent) 50%, var(--text-secondary) 72%);
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: tsShimmer 2.3s linear infinite;
}
@keyframes tsShimmer { 0% { background-position: 170% 0; } 100% { background-position: -70% 0; } }

/* glow that travels down the body's left rail */
.thinking-section__railpulse {
  position: absolute;
  left: -2px;
  top: 0;
  width: 2px;
  height: 45%;
  border-radius: 2px;
  background: linear-gradient(to bottom, transparent, var(--accent), transparent);
  box-shadow: 0 0 8px var(--accent-glow);
  animation: tsTravel 1.9s ease-in-out infinite;
  pointer-events: none;
}
@keyframes tsTravel { 0% { top: -45%; } 100% { top: 100%; } }

@media (prefers-reduced-motion: reduce) {
  .thinking-section__label--shimmer { animation: none; color: var(--text-secondary); -webkit-text-fill-color: var(--text-secondary); }
  .thinking-section__railpulse { display: none; }
}
```

Remove the now-unused `.thinking-section__streaming-text` rule and its `@keyframes thinkingPulse` if nothing else references them (grep first).

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend; npm run typecheck; npm run lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/renderer/src/components/chat/ThinkingSection.vue
git commit -m "feat(chat): thinking shimmer label + traveling rail pulse"
```

---

## Task 9: AmbientBackground — flat + faint orb glow only

**Files:**
- Modify: `frontend/src/renderer/src/components/assistant/AmbientBackground.vue`

- [ ] **Step 1: Reduce the template to a single orb-glow layer**

Read the file first (it has `.ambient__mesh`, `.ambient__flow`, `.ambient__waves`, `.ambient__grain`). Replace the multi-layer template with a flat root + one centered, state-tinted radial glow:

```vue
<template>
  <div class="ambient" :class="`ambient--${state}`" aria-hidden="true">
    <div class="ambient__orb-glow" :style="glowStyle" />
  </div>
</template>
```

Keep the existing `state` prop. Add a computed for the glow color from the existing state color tokens (reuse whatever mapping the component already had for `--ambient-primary`):

```ts
const glowStyle = computed(() => {
  const color = state.value === 'listening' ? 'var(--listening)'
    : state.value === 'thinking' ? 'var(--thinking)'
    : state.value === 'speaking' ? 'var(--speaking)'
    : state.value === 'processing' ? 'var(--info)'
    : 'var(--accent)'
  return { '--ambient-orb': color } as Record<string, string>
})
```

(If `state` is a prop accessed without `.value` in the existing `<script setup>`, match the existing access style.)

- [ ] **Step 2: Replace the styles**

Remove the `.ambient__mesh/__flow/__waves/__grain` rules and their keyframes. Keep the root flat and add the single glow:

```css
.ambient {
  position: absolute;
  inset: 0;
  z-index: 0;
  background: var(--surface-0);
  overflow: hidden;
}

.ambient__orb-glow {
  position: absolute;
  top: 32%;            /* roughly behind the orb */
  left: 50%;
  width: min(70vw, 620px);
  height: min(70vw, 620px);
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: radial-gradient(circle,
    color-mix(in srgb, var(--ambient-orb, var(--accent)) var(--orb-glow-alpha), transparent) 0%,
    transparent 65%);
  filter: blur(28px);
  transition: background 600ms var(--ease-smooth, ease);
  pointer-events: none;
}

@media (prefers-reduced-motion: reduce) {
  .ambient__orb-glow { transition: none; }
}
```

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend; npm run typecheck; npm run lint`
Expected: PASS (no unused refs/keyframes left).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/renderer/src/components/assistant/AmbientBackground.vue
git commit -m "feat(assistant): flat background + faint state-tinted orb glow"
```

---

## Task 10: AssistantResponse — new thinking/cursor + reasoning thread

**Files:**
- Modify: `frontend/src/renderer/src/components/assistant/AssistantResponse.vue`

- [ ] **Step 1: Swap the tool indicators for the thread**

Remove the `ToolExecutionIndicator` import (line 15) and its usage (the `showToolExecution` block, ~lines 150–154). Keep `ToolCallSection` for the completed-calls summary OR remove it too if redundant with the thread — prefer removing the live `ToolExecutionIndicator` block and adding the thread. Import and mount the thread under the response body:

```ts
import ReasoningThread from '../chat/ReasoningThread.vue'
```

In the template, after the streaming cursor / tool-activity area, add:

```vue
    <div class="alice-voice__activity">
      <ReasoningThread />
    </div>
```

with a left-aligned wrapper so the rail reads correctly inside the centered column:

```css
.alice-voice__activity {
  margin-top: var(--space-3);
  text-align: left;
}
```

If `showToolExecution`/`toolExecutions` become unused after removing the block, delete them to keep lint clean.

- [ ] **Step 2: Streaming cursor → shimmer-tail caret**

Replace `.streaming-cursor` (lines ~557–567) + `@keyframes cursor-blink` with:

```css
.streaming-cursor {
  display: inline-block;
  width: 2px;
  height: 1.05em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--accent);
  border-radius: 1px;
  box-shadow: -9px 0 10px -3px var(--accent-glow), 0 0 6px var(--accent-glow);
  animation: cursorPulse 1.4s ease-in-out infinite;
}
@keyframes cursorPulse { 0%, 100% { opacity: 0.95; } 50% { opacity: 0.25; } }
```

- [ ] **Step 3: Thinking label → shimmer**

The thinking toggle label (`.thinking-toggle__label`, ~line 369) gets the shimmer while in the thinking phase. Bind a class on it: `:class="{ 'thinking-toggle__label--shimmer': isThinkingPhase }"`, and add the rule:

```css
.thinking-toggle__label--shimmer {
  background: linear-gradient(90deg, var(--text-secondary) 28%, var(--accent) 50%, var(--text-secondary) 72%);
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: arShimmer 2.3s linear infinite;
}
@keyframes arShimmer { 0% { background-position: 170% 0; } 100% { background-position: -70% 0; } }
```

Add reduced-motion freezes for `.streaming-cursor` and `.thinking-toggle__label--shimmer` in the existing `@media (prefers-reduced-motion: reduce)` block.

- [ ] **Step 4: Typecheck + lint**

Run: `cd frontend; npm run typecheck; npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/components/assistant/AssistantResponse.vue
git commit -m "feat(assistant): reasoning thread + shimmer thinking/cursor in voice mode"
```

---

## Task 11: AssistantView — unify/strengthen edge fades

**Files:**
- Modify: `frontend/src/renderer/src/views/AssistantView.vue`

- [ ] **Step 1: Use the shared fade tokens on the content scroll area**

Update the existing mask on `.assistant-view__content` (lines ~1332–1343) to use the shared tokens (matches workspace):

```css
  mask-image: linear-gradient(to bottom,
    transparent 0, black var(--chat-edge-fade-top),
    black calc(100% - var(--chat-edge-fade-bottom)), transparent 100%);
  -webkit-mask-image: linear-gradient(to bottom,
    transparent 0, black var(--chat-edge-fade-top),
    black calc(100% - var(--chat-edge-fade-bottom)), transparent 100%);
```

(The background is already `var(--surface-0)` — no change needed; the calmer look comes from Task 9.)

- [ ] **Step 2: Typecheck**

Run: `cd frontend; npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/views/AssistantView.vue
git commit -m "feat(assistant): unify top/bottom edge fades with workspace"
```

---

## Task 12: Input bar — labelled segments + responsive ladder

**Files:**
- Modify: `frontend/src/renderer/src/components/chat/ChatInput.vue`
- Modify: `frontend/src/renderer/src/components/chat/ChatToolControls.vue`

- [ ] **Step 1: Add a label class to the Strumenti chip (for narrow-mode hiding)**

In `ChatToolControls.vue`, the chip's text span (`<span>Strumenti</span>`, line 65) — give it a class so the parent can hide it at narrow widths:

```vue
      <span class="ctc__chip-label">Strumenti</span>
```

Add to its `<style scoped>`:

```css
.ctc__chip-label { display: inline; }
```

- [ ] **Step 2: Restructure the ChatInput control row**

Replace the entire `.ci__controls` block in the template (lines ~298–362) with the labelled-segments layout. The mode-toggle becomes a ghost icon (no text); model selectors go in a "Modelli" segment; tools+tier go in an "Agente" segment:

```vue
    <div class="ci__controls">
      <div class="ci__controls-left">
        <button class="ci__ghost" :disabled="disabled || !supportsVision"
          :aria-label="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
          :title="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
          @click="openFilePicker">
          <AppIcon name="paperclip" :size="14" />
        </button>

        <div class="ci__divider" />

        <span class="ci__glabel">Modelli</span>
        <div class="ci__seg ci__seg--models">
          <ModelSelector model-type="llm" />
          <ModelSelector model-type="embedding" class="ci__embedding" />
        </div>

        <span class="ci__glabel ci__glabel--agent">Agente</span>
        <div class="ci__seg ci__seg--agent">
          <ChatToolControls />
          <PermissionTierSelector />
        </div>
      </div>

      <div class="ci__controls-right">
        <ContextBar :context-info="chatStore.contextInfo" :is-compressing="chatStore.isCompressingContext" />

        <button class="ci__ghost ci__mode" :aria-label="modeTitle" :title="modeTitle" @click="toggleMode">
          <AppIcon :name="modeIcon" :size="13" />
        </button>

        <div class="ci__dot" :class="isConnected ? 'dot--ok' : 'dot--err'"
          :title="isConnected ? 'Connesso' : 'Non connesso'" />

        <MicrophoneButton v-if="voiceStore.isReady" :available="voiceStore.sttAvailable"
          :connected="voiceStore.connected" :audio-devices="audioDevices ?? []"
          :selected-device-id="selectedDeviceId ?? ''" @start-recording="$emit('voice-start')"
          @stop-recording="$emit('voice-stop')" @cancel-processing="$emit('voice-cancel-processing')"
          @refresh-devices="$emit('refresh-devices')" @select-device="(id) => $emit('select-device', id)" />

        <Transition name="btn-swap" mode="out-in">
          <button v-if="isStreaming" key="stop" class="ci__stop" aria-label="Interrompi generazione" @click="emit('stop')">
            <AppIcon name="stop" :size="14" />
          </button>
          <button v-else key="send" class="ci__send"
            :disabled="(!text.trim() && pendingFiles.length === 0) || disabled" aria-label="Invia messaggio" @click="submit">
            <AppIcon name="send" :size="14" />
          </button>
        </Transition>
      </div>
    </div>
```

(The old `.ci__mode-toggle` text chip and `.ci__attach`/`.ci__selectors` wrappers are replaced. The send/stop buttons are unchanged.)

- [ ] **Step 3: Add the segment + ghost + label CSS**

In `ChatInput.vue` `<style scoped>`, replace the old `.ci__attach`, `.ci__selectors`, `.ci__mode-toggle` rules with:

```css
/* Ghost icon utilities (attach, mode) */
.ci__ghost {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color var(--duration-fast) ease, background var(--duration-fast) ease;
}
.ci__ghost:hover:not(:disabled) { background: var(--surface-hover); color: var(--text-primary); }
.ci__ghost:disabled { opacity: var(--opacity-disabled); cursor: not-allowed; }

/* Group micro-label */
.ci__glabel {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
  flex-shrink: 0;
  user-select: none;
}
.ci__glabel--agent { margin-left: var(--space-1); }

/* Segmented group container — children read as one unit */
.ci__seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  flex-shrink: 0;
  min-width: 0;
}

/* Make the child chips bare inside a segment (hero = the llm model gets a subtle ring) */
.ci__seg :deep(.ms__trigger),
.ci__seg :deep(.ctc__chip),
.ci__seg :deep(.tier-chip) {
  background: transparent;
  border-color: transparent;
  height: 24px;
}
.ci__seg :deep(.ms__trigger:hover),
.ci__seg :deep(.ctc__chip:hover:not(:disabled)),
.ci__seg :deep(.tier-chip:hover:not(:disabled)) {
  background: var(--surface-3);
}
/* LLM model is the hero — keep a faint ring */
.ci__seg--models :deep(.ms__trigger:not(.ms__trigger--embedding)) {
  border-color: var(--border-hover, var(--border));
  background: var(--surface-3);
}

.ci__mode { color: var(--text-secondary); }
.ci__dot { /* unchanged from existing rule */ }
```

(Keep the existing `.ci__divider`, `.ci__dot`, `.ci__send`, `.ci__stop`, thumbnail and textarea rules.)

- [ ] **Step 4: Rewrite the responsive ladder**

Replace the existing `@container chat-input` blocks (lines ~749–772) with the agreed ladder:

```css
/* Medium: drop labels, embedding text, mode ghost, status dot */
@container chat-input (max-width: 620px) {
  .ci__glabel { display: none; }
  .ci__mode { display: none; }
  .ci__dot { display: none; }
  .ci__embedding :deep(.ms__label) { display: none; }
}

/* Narrow: drop embedding entirely; model -> short; agente icons-only */
@container chat-input (max-width: 440px) {
  .ci__embedding { display: none; }
  .ci__seg--agent :deep(.ctc__chip-label),
  .ci__seg--agent :deep(.tier-chip__label) { display: none; }
  .ci__controls-left { gap: var(--space-1); }
}
```

- [ ] **Step 5: Typecheck + lint**

Run: `cd frontend; npm run typecheck; npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/renderer/src/components/chat/ChatInput.vue frontend/src/renderer/src/components/chat/ChatToolControls.vue
git commit -m "feat(chat): labelled-segments input bar with responsive collapse ladder"
```

---

## Task 13: Verify obsolete agent toggles are gone

**Files:** none (verification only)

- [ ] **Step 1: Confirm no stranded agent-mode toggles**

Run:
```bash
cd frontend; npx --yes rg -ni "structured|reflection|riflession|pianific|delegation|subagent|react.?agent" src/renderer/src/views/SettingsView.vue src/renderer/src/components/settings || echo "none — confirmed removed"
```
Expected: `none — confirmed removed`. If anything agent-mode-specific appears, report it (do not change behaviour without confirmation). No commit.

---

## Task 14: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full typecheck, lint, unit tests**

```bash
cd frontend; npm run typecheck && npm run lint
npx vitest run src/renderer/src/stores/agentRun.spec.ts
```
Expected: all PASS.

- [ ] **Step 2: Manual run checklist**

Start the app (`.\scripts\start-dev.ps1` from repo root) and verify:
- Workspace chat: send a message that triggers multiple tool calls. The **reasoning thread** appears UNDER the streamed answer, shows live nodes, folds older ones, pulses the active node; thinking label shimmers + rail glow travels; streaming cursor is the soft glowing caret (no block-blink).
- When the turn finishes, the thread stays as a one-line **Completato** summary; clicking it expands/collapses the full node list.
- Send a **new** message: the thread resets to a fresh "avvio…" state immediately — no "green Passo 1/26" flash.
- Input bar: at wide width shows labelled "Modelli"/"Agente" segments + ghost utilities + one filled send; shrink the window → labels/embedding/mode/dot drop (medium), then embedding hidden + agente icons-only (narrow); never overflows.
- Assistant mode: background is flat with a faint state-tinted glow behind the orb (no mesh/waves/grain); top+bottom edge fades present; thinking/cursor motion matches workspace; reasoning thread shows under the response.
- `prefers-reduced-motion` (OS setting): shimmer/pulse/cursor animations freeze gracefully.

- [ ] **Step 3: Final branch state**

Confirm all tasks committed on `feat/agentic-chat-ui-polish`:
```bash
git log --oneline feat/agentic-chat-ui-polish ^main
```
Expected: one commit per task (≈12). Use `superpowers:finishing-a-development-branch` to decide merge/PR.

---

## Self-Review

**Spec coverage:**
- §1 Reasoning thread → Tasks 2 (store), 3 (component), 4 (pending reset), 5 (remove from streaming), 6 (mount+persist), 7 (delete old). ✓
- §2 Input bar → Task 12. ✓
- §3 Thinking indicator → Tasks 8 (ThinkingSection), 10 (AssistantResponse), 5 (streaming thinking-state label). ✓
- §4 Streaming cursor → Tasks 5 + 10 (flagged shimmer-tail as glowing caret; refine on impl). ✓
- §5 Assistant background → Task 9. ✓
- §6 Edge fades → Tasks 6 (workspace) + 11 (assistant), tokens in Task 1. ✓
- §7 Obsolete toggles → Task 13 (verify no-op). ✓

**Placeholder scan:** No TBD/TODO; every code/CSS step shows real content. The two "read the file first / match existing access style" notes (Tasks 4, 9) are verification cues, not deferred work.

**Type consistency:** `beginPendingTurn`, `pendingTurn`, `currentRun`, `seq`, `ReasoningThread` used consistently across tasks. `seq` added to both activity interfaces (Task 2) and consumed in Task 3. `--chat-edge-fade-*` / `--orb-glow-alpha` defined in Task 1 and used in Tasks 6/9/11.

**Watch-points carried from spec:** `--accent-glow`/`--border-hover` existence verified during typecheck (fallbacks provided); `branchConversation` reset is conditional on whether it starts a turn; `agentRun.tools` must populate during a turn for the thread to fully replace the live indicator (confirm in Task 14 manual run).
