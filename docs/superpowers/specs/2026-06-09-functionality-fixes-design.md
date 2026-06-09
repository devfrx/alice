# Functionality-fixes batch — Design spec

- **Date:** 2026-06-09
- **Status:** Approved (design); pending spec review
- **Owner phase:** Functionality stabilization (follows the agentic-chat-ui-polish phase)
- **Rule:** every fix targets the *native root cause*; rework is acceptable. No silent
  degradation, no overlapping controls left behind, no half-broken states.

## Goal

Six independent, user-reported defects/feature-gaps, fixed at the root in a single
spec. Each is a self-contained work-item so the implementation plan can keep them as
independent task-groups (and parallelize where safe). Cross-cutting root cause shared
by #1 and #4 is fixed once, first.

## Cross-cutting principles (apply to every item)

- **Root cause, not symptom.** Where observed behavior contradicts documented intent
  (items #2 and #3), *reproduce first* (systematic-debugging) before changing code.
- **No silent degradation.** A subsystem is either fully working or explicitly
  disabled with a status signal. Never "appears up, returns garbage".
- **Contract consistency.** Any change to a WS message / REST shape / TS type / Pinia
  store / DB model requires the matching change on every side (per CLAUDE.md).
- **TDD where the repo supports it.** Backend services → pytest; frontend stores/utils
  → vitest. `.vue` components are not unit-tested (repo convention) → manual verify.

## Explicit boundary decisions (recorded, not debt)

1. **MCP-external tools (#2).** Our own filesystem/exec tools are confined at the
   permission gate. An external MCP server that writes files in its own process can be
   denied on *known path arguments* but cannot be process-confined by us. Documented
   limit, not a regression.
2. **Voice/lite confirmations (#2).** With no interactive channel, a
   `NEEDS_CONFIRMATION` verdict has no one to ask. Voice/lite uses an explicit
   non-confirming tier — never a silent auto-approve.
3. **Lossy collection recreate (#3).** Recreating a dimension-mismatched Qdrant
   collection drops its vectors. It is the only correct recovery for a corrupt/mismatch
   collection and is surfaced via a status event.

---

## Cross-cutting fix — remove the synchronous LM-Studio call from hot paths

**Powers #1 and #4.**

### Root cause
`llm.get_active_context_window()` → `lmstudio_service.list_models()` is awaited on the
critical path of **both** turn-start ([_assembly.py:431](../../../backend/api/routes/chat/_assembly.py))
**and** every conversation open ([conversations.py:160](../../../backend/api/routes/chat/conversations.py)).
It blocks on a live HTTP round-trip to learn a value (the active model's context
window) that changes only on model switch. When LM Studio is slow/down this is a 5s+
connect stall (Windows TCP retry = the ~3s steps in the logs), and it contends on the
shared `_models_cache_lock` with the 5s background health poll
([service_orchestrator.py](../../../backend/core/service_orchestrator.py)) and the
frontend's `/models/status` (4s) + `/config/models` (uncached) polling.

### Approach
- Cache the active model's context window with a **long TTL**; serve hot paths from
  cache. Refresh **in the background** and **invalidate on model switch / `config.changed`**
  (event-driven — the anti-staleness requirement).
- Any residual hot-path call gets a **short timeout (~1s)** and falls back to the cached
  / configured default rather than blocking.
- Give the background health poll its **own lock** so it never serializes behind a chat
  turn or a conversation open.

### Affected files
`services/llm_service.py` (get_active_context_window, ~1594/1606),
`services/lmstudio_service.py` (list_models cache/lock, ~126),
`api/routes/chat/_assembly.py`, `api/routes/chat/conversations.py`,
`core/service_orchestrator.py` (poll lock).

### Acceptance
- Turn-start and conversation-open issue **zero** blocking LM-Studio calls (verified by
  a test that stubs `list_models` to raise/delay and asserts assembly/GET still return
  promptly using the cached/default window).
- Context window cache invalidates on a model-switch event.

### Tests
pytest: cache hit/miss + TTL, invalidation-on-event, short-timeout fallback, separate
poll lock (no contention with a simulated turn).

---

## 1 · Latency UI → LM Studio

### Root cause
The cross-cutting blocking call (above) **plus** unconditional frontend polling of
`/models/status` (4s) and `/config/models` (uncached) that hammers a down service.

### Approach
Cross-cutting fix + **event-driven frontend back-off**: when a `service.status`/down
event is known, pause/extend model-status & model-list polling; resume on recovery.

### Affected files
`frontend/src/renderer/src/stores/services.ts`, `stores/settings.ts` (or wherever model
polling lives), `services/ws.ts` (status events), backend `api/routes/models.py` /
`api/routes/config.py` (ensure cached + cheap).

### Acceptance
With LM Studio down, polling frequency drops (no per-4s hammering); first message after
recovery is responsive.

### Tests
vitest: polling store backs off on a down status event, resumes on up.

---

## 2 · Hard-sandbox scope + tier-authoritative confirmations (reproduce-first)

### Root cause — scope
`ScopeService.scope_roots()` feeds `PermissionService` as a scope gate, but the
**no-scope fallback was deliberately deferred** (its own docstring; `WorkspaceScopeConfig`
[config.py:385-391](../../../backend/core/config.py) `fallback_mode` default `"disabled"`).
Documented intent says the no-scope breaker blocks the model's FS tools in every tier —
**but writes land in home**, so a tool currently escapes the gate (or no scope is set
and the gate isn't actually confining). `ExecutionContext`
([plugin_models.py:205](../../../backend/core/plugin_models.py)) does not carry the scope,
and file tools resolve against their own `_allowed_paths`
([file_search/plugin.py:564](../../../backend/plugins/file_search/plugin.py), default ≈ home).

### Root cause — confirmations
The tier is already authoritative for DENY (`PermissionMiddleware` reads mode per-call,
`PermissionService.decide()` emits `NEEDS_CONFIRMATION`,
[permission_service.py:213](../../../backend/services/permission_service.py)). But
`ConfirmationMiddleware` **silently auto-approves** a tier-mandated confirmation whenever
the legacy global `confirmations_enabled` toggle is off
([pipeline.py:335-341](../../../backend/services/turn/pipeline.py)). The global toggle acts
as a hidden "force-AUTOPILOT" overriding the chosen tier. `confirmations_enabled` defaults
`True` ([config.py:365](../../../backend/core/config.py)) yet no prompts appear → the path
must be reproduced to find where the round-trip is lost (toggle in a runtime layer, a tier
that never yields `NEEDS_CONFIRMATION`, or a channel issue).

### Approach — scope (hard sandbox)
- **Reproduce** which tool writes to home and why the no-scope breaker doesn't catch it.
- Thread the active scope into tool execution (carry `scope_roots` / effective workspace
  on `ExecutionContext` or via the existing scope provider) so every filesystem/exec tool
  **resolves relative paths under, and is confined to, the scope**.
- **No scope set → hard-sandbox to an ephemeral per-conversation workspace** under
  `data/workspaces/<conversation_id>/` (the `WorkspaceScopeConfig.sandbox_root` already
  exists, [config.py:393](../../../backend/core/config.py)). Never home, never the
  replicated system roots. This removes the home-leak entirely.
- Ensure the permission scope check sees the **effective resolved absolute path** the tool
  will actually use (close the bypass found in repro).

### Approach — confirmations (tier authoritative)
- Remove the `else: approved = True` silent auto-approve. A `NEEDS_CONFIRMATION` verdict
  **always** prompts on an interactive turn. `AUTOPILOT` stays the explicit "never ask"
  tier; `STRICT`/`AUTO_EDITS`/`PLAN` behave per their `decide()` mapping.
- Retire the global `confirmations_enabled` bypass as a behavior control (keep only the
  no-gate-decision fallback used by isolated unit tests).
- Voice/lite (no interactive channel) → explicit non-confirming tier (boundary decision 2).

### Affected files
`core/plugin_models.py` (ExecutionContext), `services/turn/tool_loop.py` (build context +
drop the read-once flag), `services/turn/pipeline.py` (ConfirmationMiddleware),
`services/permission_service.py` (effective-path scope check),
`services/scope_service.py` (no-scope → sandbox resolution), the filesystem/exec plugins
(`plugins/file_search`, `plugins/pc_automation`, terminal), `core/config.py`
(`fallback_mode` semantics for the model path).

### Acceptance
- With a scope set: a write outside it is **denied**; a relative write lands **inside** it.
- With no scope: a write lands in `data/workspaces/<conv_id>/`, **never** in home or a
  system root.
- In `STRICT`/`AUTO_EDITS`: a dangerous tool triggers a **real confirmation prompt**;
  rejecting it blocks the tool. In `AUTOPILOT`: no prompt (by design).
- The global `confirmations_enabled` toggle no longer suppresses tier confirmations.

### Tests
pytest: scope confinement (in/out/relative/no-scope→sandbox), effective-path gate;
confirmation middleware prompts on `NEEDS_CONFIRMATION` regardless of the legacy toggle,
rejection short-circuits, `AUTOPILOT` skips.

---

## 3 · RAG readiness gate + bounded auto-repair

### Root cause
Silent degradation throughout: Qdrant falls back to **in-memory on a Windows file lock**
(data lost on restart, [qdrant_service.py:110](../../../backend/services/qdrant_service.py)),
embedding dim mismatches corrupt vectors, failures are swallowed in assembly, and
`QdrantBackend.health()` only checks object existence, not function
([qdrant_backend.py:256](../../../backend/services/knowledge/qdrant_backend.py)). Tool-RAG
silently returns the full tool list on failure with no signal
([tool_registry.py:612](../../../backend/core/tool_registry.py)).

### Approach
- A single `check_rag_readiness(ctx)` that **truly probes**: Qdrant is on-disk (not the
  in-memory fallback), an embedding round-trip succeeds, memory + tool collections exist at
  the expected dimensions, tool-embeddings are populated (when tool-RAG enabled).
- **Bounded auto-repair** before gating: clear a stale RocksDB lock and retry on-disk open;
  recreate a dimension-mismatched collection (lossy — boundary decision 3).
- If still not 100% → **disable memory + tool-RAG entirely**: assembly skips memory search
  and uses the full tool list deliberately (not as a hidden fallback), and a clear
  `knowledge.status` / service-status event drives a frontend badge.
- **Runtime verification step** proving readiness reaches "healthy" on this Windows machine.

### Affected files
new `services/rag_readiness.py`; wiring in `core/app.py` lifespan;
`services/qdrant_service.py` (lock-clear/repair, in-memory detection),
`services/memory_service.py`, `core/tool_registry.py` (gate on readiness, no silent
fallback), `api/routes/chat/_assembly.py` (skip cleanly when disabled),
`core/event_bus.py` + an events bridge for the status; frontend `stores/services.ts` +
a status badge.

### Acceptance
- Readiness probe returns healthy only when all checks pass; otherwise memory + tool-RAG
  are off and a status event is emitted.
- A simulated in-memory fallback / dim-mismatch is detected (not reported "up").
- On this machine: backend starts, probe reports healthy, an embed→search round-trip
  succeeds against on-disk Qdrant.

### Tests
pytest: readiness true/false per failing sub-check; auto-repair clears a simulated stale
lock; disabled-state assembly path skips memory and uses full tools.
Runtime: documented manual/integration verification on Windows.

---

## 4 · Chat/view switching reliability

### Root cause
`loadConversation` has **no generation guard, no AbortController, no loading flag**
([chat.ts:269](../../../frontend/src/renderer/src/stores/chat.ts)) → a slow response for
chat A overwrites a newer selection of B ("won't switch"); rapid clicks pile up
([AppSidebar.vue:108](../../../frontend/src/renderer/src/components/sidebar/AppSidebar.vue)).
`api.getConversation` never passes the `AbortSignal` the request layer already supports.
Compounded by the cross-cutting heavy backend GET.

### Approach
- A **generation token** per `loadConversation`: only the latest applies its result;
  stale results are discarded.
- An **`AbortController`** per load; a new select **aborts the in-flight** request and
  passes the signal through `api.getConversation`.
- An **`isLoadingConversation`** flag for UI feedback (and to coalesce, not block, rapid
  clicks → latest wins).
- Backend GET made cheap by the cross-cutting fix (no LM-Studio / tool-RAG / token
  estimation on a plain open).

### Affected files
`frontend/src/renderer/src/stores/chat.ts`, `services/api.ts` (pass signal),
`components/sidebar/AppSidebar.vue`; backend `api/routes/chat/conversations.py` (lean GET).

### Acceptance
Rapid A→B clicks always end on B; a slow A response never overwrites B; switching is
responsive with LM Studio down.

### Tests
vitest: generation guard discards a stale resolve; abort cancels in-flight on re-select;
loading flag lifecycle.

---

## 5 · Whiteboard conversation-scoping

### Root cause
`WhiteboardModule` calls `loadBoards()` with **no `conversation_id`**
([WhiteboardModule.vue:78](../../../frontend/src/renderer/src/components/canvas/modules/WhiteboardModule.vue));
the store is **never reset on switch** and an `onMounted` one-shot guard blocks reload
([whiteboard.ts:35](../../../frontend/src/renderer/src/stores/whiteboard.ts)); backend
`count()` omits the `conversation_id` filter that `list()` has
([whiteboards.py:79](../../../backend/api/routes/whiteboards.py)) → foreign boards appear.

### Approach
Align with the correctly-scoped modules (artifacts/charts): `loadBoards(conversationId)`
always passes the id; the store **resets on conversation switch** and **watches**
`conversationId` (drop the one-shot guard); backend `count()` takes the same
`conversation_id` filter as `list()`.

### Affected files
`frontend/src/renderer/src/stores/whiteboard.ts`,
`components/canvas/modules/WhiteboardModule.vue`,
`backend/api/routes/whiteboards.py`.

### Acceptance
Switching conversations shows **only** that conversation's whiteboards; counts/pagination
are scoped; a fresh conversation shows none.

### Tests
vitest: store resets on conversation change and reloads scoped; pytest: list+count both
filtered by `conversation_id`.

---

## 6 · ask_user → sequential multi-question wizard

### Root cause / gap
`ask_user` is single-question / single-answer end to end: tool schema
([agent/plugin.py:178](../../../backend/plugins/agent/plugin.py)), WS frames
([channel.py:50](../../../backend/services/turn/channel.py),
frontend `WsAskUserRequiredMessage`), and `AskUserPrompt.vue`. No radio/checkbox
distinction, no multi-question, no free-text-per-question.

### Approach (clean cutover — no dual single/multi path)
- **Schema** → `questions[]`, each `{ id, text, type: "radio"|"checkbox", options[],
  allow_free_text }`.
- **WS contract** → request carries `questions[]`; response carries `answers[]`
  (`{ questionId, selectedOptions[], freeText? }`); **one `execution_id`**, answers
  correlated by question id.
- **Backend** `_execute_user_interaction`
  ([pipeline.py:729](../../../backend/services/turn/pipeline.py)) builds the multi-question
  payload, awaits the single response, returns a **labeled answer block** to the model.
- **Frontend** `AskUserPrompt.vue` becomes a **Next/Back wizard**: one question per step,
  radio or checkbox, optional free-text field, single submit at the end. Store
  (`addPendingAskUser`) and `useChat.onAskUserRequired`/`answerAskUser` updated to the new
  shapes; `types/chat.ts` + `types/turn.ts` updated in lockstep.
- One `interaction_requested`/`interaction_resolved` pair per call (resolved once all
  answered) — keeps the existing turn-event model.

### Affected files
`backend/plugins/agent/plugin.py`, `services/turn/pipeline.py`, `services/turn/channel.py`
(specs unchanged, payload generic), `services/turn/events.py` (unchanged);
`frontend/src/renderer/src/types/chat.ts`, `types/turn.ts`,
`components/chat/AskUserPrompt.vue`, `composables/useChat.ts`, `stores/chat.ts`.

### Acceptance
The model can request N questions; the user steps through radio/checkbox questions with
optional free-text and submits once; the model receives all answers labeled by question;
cancel/timeout still resolve cleanly.

### Tests
pytest: payload build from `questions[]`, answer-block formatting, cancel/timeout;
vitest: store pending/answer round-trip with the new shapes. `.vue` wizard → manual.

---

## Sequencing

1. Cross-cutting fix + **#1** + **#4** (shared root, biggest felt impact).
2. **#3** (readiness gate; also de-risks the GET path in #4).
3. **#2** (correctness/safety; reproduce-first).
4. **#5** then **#6**.

Items are independent task-groups; the plan may parallelize #5/#6 against the rest.

## Out of scope

- Continuum knowledge backend changes (Alice consumes it over HTTP/MCP only).
- New permission tiers (reuse `STRICT`/`AUTO_EDITS`/`PLAN`/`AUTOPILOT`).
- Process-level sandboxing of external MCP tools (boundary decision 1).
- Any UI restyle beyond what these fixes require (the prior phase covered visuals).

## Verification plan

- pytest (backend) + vitest (frontend) green for every item that has automated coverage.
- `npm run typecheck` clean; `ruff` + `mypy` clean on changed backend files.
- Runtime on this Windows machine: backend up, RAG readiness healthy with an on-disk
  Qdrant embed→search round-trip; a scoped write confined; a `STRICT` confirmation prompt
  appears; conversation switching responsive; whiteboards correctly scoped; an ask_user
  multi-question wizard round-trips.
