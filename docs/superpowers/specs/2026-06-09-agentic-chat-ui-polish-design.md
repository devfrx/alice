# Agentic Chat UI Polish — Design

**Date:** 2026-06-09
**Scope:** Frontend only (`frontend/src/renderer/src`). No backend contract changes.
**Status:** Approved directions (via visual brainstorming); pending spec review.

## Context

A large rework landed (tiered permissions, session scope, PTY terminal). The agentic chat
UI now has rough edges. This spec covers six UI fixes/redesigns, all decided through visual
mockups in the brainstorming companion. A separate, later pass will address functionality
(out of scope here).

Primary surfaces:
- **Workspace chat** — `components/canvas/ChatPanel.vue` → `MessageBubble.vue` + `StreamingIndicator.vue`, driven by `stores/chat`.
- **Assistant (voice) mode** — `views/AssistantView.vue` → `AssistantResponse.vue`, with `AmbientBackground.vue`.
- Shared chat pieces: `ThinkingSection.vue`, `ToolExecutionIndicator.vue`, `AgentActivityCard.vue`, `ChatInput.vue` and its chips.
- Canonical turn-event state: `stores/agentRun.ts` (folds `turn.*` / `tool.*` / `interaction.*` WS frames into a per-`turnId` `AgentRun`).

Design language tokens (dark theme): `--surface-0 #1A1A19`, `--surface-2 #2A2A28`, accent (cream) `--accent #E8DCC8`, mono font for numerics. The whole redesign stays within these tokens.

---

## 1. Agent activity card → "Reasoning thread"

**Decision:** Replace `AgentActivityCard.vue` (the current boxed status card) with a borderless
**Reasoning thread**: an accent left-rail with a vertical mini-timeline of nodes. (Brainstorm direction C, refined.)

**Current problems**
- Card renders *only* inside `StreamingIndicator.vue` (line 57), so it **vanishes** the moment streaming ends (the indicator unmounts).
- It is positioned *above* the streamed content (between thinking and content), not under everything.
- The "stale green `Passo 1/26`" leak: on a new send, `StreamingIndicator` mounts and `AgentActivityCard` reads `agentRunStore.currentRun`, which still points at the **previous, finished** run until the new `turn.started` arrives — so the user briefly sees a green "Completato · stop · 1/26" as if it were the new turn.

**Target component:** new `components/chat/ReasoningThread.vue`, reading `useAgentRunStore().currentRun`. It **subsumes** the live `ToolExecutionIndicator` — one unified agent-activity element, not two overlapping ones.

**Behavior (the three locked rules + re-expand)**
- **Running:** live trace. A head node `Ragionamento` (accent dot) carrying the step counter `passo N/M`. Below it, nodes for each tool call, sub-agent, and interaction (confirmation / ask_user), each with a status glyph (`✓` success / `●` running / `errore` / `approvato`). Keep the head + the **last ~3** nodes visible; older ones fold into a single `+N azioni precedenti` affordance. The active node pulses + softly shimmers. Capped height.
- **Finished:** collapses to **one summary node** — `Completato · N passi · M strumenti · ↑tok ↓tok`. Persists as a calm line under the answer.
- **Re-expandable:** clicking the collapsed summary expands the full node list (with final outcomes incl. errors/approvals) and collapses again — a two-way toggle.

**Placement & lifecycle (avoids backend change)**
- `ChatMessage` has no `turn_id`, and the user's requirement is *latest-turn* behavior, not per-historical-message. So render **one** `<ReasoningThread />` instance at the **end of the thread** (after the message `v-for` and the streaming block), self-guarded by `v-if="currentRun"`. This places it *under* the thinking, the live/streamed content, and the final answer.
- It **persists** after the turn finishes (still bound to `currentRun`, now in collapsed/finished state).
- On the **next generation** it disappears and reappears fresh — see the stale-leak fix below.
- Remove `<AgentActivityCard>` and `<ToolExecutionIndicator>` from `StreamingIndicator.vue`; `StreamingIndicator` keeps only thinking + streamed content + cursor.

**Stale-leak fix**
- Add an action to `stores/agentRun.ts` — `beginPendingTurn()` (name TBD) — that, on user send, clears the stale finished run from `currentRun`'s slot and installs a fresh **pending** run (`status: 'running'`, `step: 0`, `maxSteps: 0`, empty tools/interactions). Call it from the send path (`composables/useChat.ts` `sendMessage`, and the edit/branch paths that start a new turn).
- The thread then shows a fresh `Ragionamento · avvio…` state in the send→`turn.started` gap; `applyTurnStarted` replaces the pending run with the real one. No more "green 1/26".

**Node-order detail:** `agentRun` keeps `tools` and `interactions` as separate arrays with no shared sequence. To interleave them chronologically in the thread, add a monotonic `seq` (or arrival index) to each `ToolActivity` / `InteractionActivity` when folded, and merge-sort on it in the component. (Implementation detail for the plan.)

**Assistant (voice) mode:** surface the same thread under `AssistantResponse` (it currently shows `ToolExecutionIndicator` + `ToolCallSection` only). The thread is inherently a left-aligned list, so wrap it in a left-aligned, max-width container within the centered column. This unifies the two surfaces. (Lower priority than the workspace surface; style adaptation expected.)

**Acceptance**
- During a run, the thread shows live nodes, folds older ones, pulses the active node, and sits under the streamed answer.
- When the run finishes, the thread stays as a one-line summary and can be expanded/collapsed by click.
- Sending a new message shows a fresh thread (never the previous run's finished summary as "current").
- No separate live tool indicator remains during streaming.

---

## 2. Input bar → "Labelled segments" + responsive ladder

**Decision:** Restructure `ChatInput.vue`'s bottom control row into micro-labelled segmented
groups with clear primary/secondary weighting (brainstorm direction C). Not a recolor — a
structural hierarchy change.

**Layout (wide ≥ 620px)**
- `📎` attach (ghost icon) · divider
- **Modelli** label → segment `[ ◆ LLM-model ▾ (hero) | embedding ▾ ]`
- **Agente** label → segment `[ ⚒ Strumenti | 🛡 Conferma ]` (tier chip shows its tier color)
- spacer
- mode-toggle (ghost icon) · mic (ghost icon) · connection dot · **Send** (the only filled/accent control)

Utilities (attach, mode toggle, mic) become quiet ghost icon-buttons. The LLM model is the
bordered hero; the embedding selector is visually secondary. Send→stop swap, drag-drop,
thumbnails, and paste are unchanged.

**Responsive collapse ladder** (via the existing `container-name: chat-input` query)
- **Medium (~440–620px):** drop the "Modelli/Agente" micro-labels, the embedding chip's text (→ icon only), the mode-toggle ghost, and the connection dot. Segments stay.
- **Narrow (< 440px):** drop the embedding selector entirely (still reachable in the LLM model popover); LLM model → short name; "Agente" segment → **icon-only** chips. Always keep: attach · model · tools/tier · mic · send. No overflow/wrap — icon-only.

**Components touched:** `ChatInput.vue` (template + CSS, new segment wrappers + labels +
breakpoints). Minor chip-style alignment in `ModelSelector.vue`, `ChatToolControls.vue`,
`PermissionTierSelector.vue` so they read as one family inside a segment (consistent height,
radius, ghost/hover treatment). No behavior/store changes.

**Acceptance:** clear visual hierarchy (one filled send, hero model, ghost utilities, labelled
groups); the ladder degrades exactly as above at the two breakpoints without overflow.

---

## 3. Thinking indicator → shimmer label + traveling rail pulse

**Decision:** Combine brainstorm options 2 + 3. The thinking state shows `Ragionamento…` with a
**shimmer gradient** sweeping through the text **and** a soft **glow traveling down the accent
rail**.

**Components touched:** `ThinkingSection.vue` (used by both `MessageBubble` and
`StreamingIndicator`) and the thinking treatment in `AssistantResponse.vue`. Retire the current
"pensando…" pulse text + plain spinner in favor of the shimmer label; add the rail-pulse glow
element on the left border. Respect `prefers-reduced-motion` (freeze to a static accent label +
static rail).

**Acceptance:** while thinking tokens stream, the label shimmers and the rail glow travels; both
stop cleanly when thinking ends; reduced-motion users get a static treatment.

---

## 4. Streaming cursor → "Shimmer tail" (refine on implementation)

**Decision:** Brainstorm option B. The line currently being written carries a faint left→right
shimmer highlight, with a thin glowing trailing bar. The harsh blinking block-cursor is removed
everywhere.

> **Explicitly flagged by the user:** the mockup is a *direction*, not the bar. The
> implementation must be meaningfully more polished — smoother sweep, correct timing, integrated
> with real token streaming (the sweep should track genuinely-arriving text, not a fixed CSS
> typewriter), and it must degrade gracefully for `prefers-reduced-motion` (static thin caret).

**Components touched:** `StreamingIndicator.vue` (`.streaming-bubble__cursor`) and
`AssistantResponse.vue` (`.streaming-cursor`). Shares the shimmer motion vocabulary with the
thinking indicator (one family).

**Acceptance:** streaming text shows the shimmer-tail + thin glowing bar, smooth and on-brand;
no block-blink anywhere; reduced-motion fallback present.

---

## 5. Assistant background → flat + faint orb glow

**Decision:** Calm the assistant background to match the workspace look. Remove
`AmbientBackground.vue`'s animated layers (`.ambient__mesh`, `.ambient__flow`, `.ambient__waves`,
`.ambient__grain`); render flat `--surface-0` like the workspace gutters, **keeping a single
faint, state-tinted radial glow directly behind the orb** so it doesn't float on dead-flat.

**Components touched:** `AmbientBackground.vue` (strip the busy layers; keep one subtle
state-reactive radial glow centered on the orb, using the existing `--accent`/`--thinking`/
`--speaking`/`--listening`/`--info` state colors at low alpha). `AssistantView.vue` background
stays `--surface-0`.

**Acceptance:** assistant mode reads as calm/flat like the workspace; the orb retains a subtle
backing glow that still reflects its state; no mesh/waves/grain motion.

---

## 6. Top + bottom edge fades (both modes)

**Decision:** A consistent CSS `mask-image` fade at the **top** (content dissolves as it scrolls
up) and **bottom** of the message column, in **both** workspace and assistant modes.

**Components touched:**
- **Workspace:** `ChatPanel.vue` `.chat-panel__messages` (the `overflow-y:auto` scroll
  container) — add a top+bottom mask gradient. The composer lives outside this container, so a
  bottom fade is safe.
- **Assistant:** `AssistantView.vue` `.assistant-view__content` already has a weak mask
  (12px/16px) — unify it with the workspace values and strengthen slightly. Apply the same
  treatment to `AssistantResponse`'s scroll region if it scrolls independently.

Use shared fade sizes (e.g. a `--chat-edge-fade` length) so both modes match.

**Acceptance:** in both modes, long threads softly dissolve at the top and bottom edges; the fade
does not clip interactive controls or the input bar.

---

## 7. Obsolete agent-mode toggles

**Decision:** No action — the user confirmed the two legacy toggles were **already removed**.
Verify nothing agent-mode-specific remains stranded in Settings; otherwise skip.

---

## Non-goals
- Backend/WS contract changes (no `turn_id` on messages, no new events).
- Functionality fixes (a later, separate pass).
- Per-historical-message reasoning threads (only the latest turn persists).
- Reworking the orb engine, voice pipeline, or side panels.

## Risks / watch-points
- **`agentRun` node interleaving** needs a sequence field to order tools vs interactions correctly.
- **Pending-turn reset** must fire on every new-turn entrypoint (send, edit-resubmit, branch) or the stale leak returns; conversely it must not wipe a still-valid finished thread on conversation switch (handle via `currentTurnId`).
- **Shimmer-tail** tied to real streaming, not a CSS typewriter — verify it looks right with actual token cadence.
- **Reduced motion** across thinking shimmer, rail pulse, streaming tail, and the removed ambient.
- **Assistant-mode thread** styling inside the centered voice layout may need iteration.
- Contract consistency: removing `ToolExecutionIndicator` from streaming — confirm it isn't relied on elsewhere before deleting the file.

## Affected files (inventory)
- New: `components/chat/ReasoningThread.vue`
- Replace/remove: `components/chat/AgentActivityCard.vue`, usage of `components/chat/ToolExecutionIndicator.vue`
- Edit: `components/chat/StreamingIndicator.vue`, `components/chat/ThinkingSection.vue`, `components/chat/ChatInput.vue`, `components/settings/ModelSelector.vue`, `components/chat/ChatToolControls.vue`, `components/chat/PermissionTierSelector.vue`, `components/canvas/ChatPanel.vue`, `views/AssistantView.vue`, `components/assistant/AssistantResponse.vue`, `components/assistant/AmbientBackground.vue`, `stores/agentRun.ts`, `composables/useChat.ts`, `assets/styles/theme.css` (shared fade/glow tokens)

## Verification
- `npm run typecheck` and `npm run lint` clean (per CLAUDE.md, always before done).
- Update `stores/agentRun.spec.ts` for the new pending-turn action.
- Manual: run the app, exercise a multi-tool agent turn in workspace + assistant mode, confirm all six items behave per the acceptance criteria.
