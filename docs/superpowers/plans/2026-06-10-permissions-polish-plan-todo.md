# Permissions Polish + Plan/Tasks Distinction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each permission tier distinctly shape the agent (sovereign per-tier tool whitelist, inline scope indicator, custom persona + per-tier prompts) and split the agent's "plan" into a written `.md` document (`write_plan`, shown in the plan module) vs the live executable checklist (`update_tasks`, shown fixed above the composer).

**Architecture:** Backend is plugin/DI (AppContext) FastAPI; turn assembly in `api/routes/chat/_assembly.py` selects tools + builds the system prompt. Permission behavior is centralized in `services/permission_mode_policy.py`. Frontend is Vue 3 `<script setup>` + Pinia; chat surface composes `ChatInput` inside `ChatPanel`. We keep contracts (WS event / REST / TS type / store / DB) in lockstep.

**Tech Stack:** Python 3.11 / FastAPI / SQLModel / loguru; Vue 3 / TypeScript / Pinia / electron-vite; pytest, vitest, ruff, mypy, vue-tsc.

**Execution model:** Phase 0 is a foundational contract rename (sequential). Phase 1 is 8 file-disjoint tracks that run in parallel. Phase 2 is the shared-file integration wiring (sequential, depends on Phase 1). Phase 3 is whole-system verification. File ownership is called out per task to avoid parallel-edit conflicts.

---

## File ownership map (conflict avoidance)

| File | Owner phase/track |
|---|---|
| `backend/services/permission_mode_policy.py` | P1·T1 |
| `backend/core/tool_registry.py` | P1·T1 |
| `backend/db/models.py` | P1·T2 |
| `backend/services/plan_document_service.py` (new) | P1·T2 |
| `backend/api/routes/plan_document.py` (new) | P1·T2 |
| `backend/core/config.py` | P1·T3 |
| `backend/services/llm_service.py` | P1·T3 |
| `backend/services/plan_service.py` (+ `api/routes/plans.py`→`tasks.py`) | P0 |
| `backend/plugins/agent/plugin.py`, `_plan.py` | P0 (rename) + P2 (write_plan) |
| `backend/core/event_bus.py` | P0 |
| `backend/core/app.py` | P2 |
| `backend/api/routes/chat/_assembly.py`, `_helpers.py` | P2 |
| `backend/api/routes/__init__.py` | P2 |
| FE `stores/plan.ts`→`tasks.ts`, `types/plan.ts`→`tasks.ts`, `useEventsWebSocket.ts` | P0 |
| FE `components/chat/TaskStrip.vue` (new), `TaskStepList.vue` (moved) | P1·T4 |
| FE `stores/planDocument.ts` (new), `types/planDocument.ts` (new) | P1·T5 |
| FE `components/canvas/modules/PlanModule.vue` | P1·T5 |
| FE `components/chat/ScopeIndicator.vue` (new) | P1·T6 |
| FE `components/chat/ChatToolControls.vue` | P1·T7 |
| FE `components/settings/AgentPersonaSettings.vue` (new) | P1·T8 |
| FE `components/chat/ChatInput.vue`, `ChatPanel.vue`, `composables/workspace/moduleRegistry.ts`, settings registration | P2 |

---

## PHASE 0 — Foundational rename `plan`→`tasks` (sequential, one agent)

Renames the **tasks** contract end-to-end so naming is unambiguous before features land. The `.md` plan document is added later (P1·T2/P2). The internal SQLite table `conversation_plans` keeps its name (no migration value); everything contract-facing becomes `tasks`.

### Task 0.1: Backend tasks contract rename

**Files:**
- Modify: `backend/plugins/agent/plugin.py` (tool `update_plan`→`update_tasks`; update tool name, description, dispatch key, any internal references; keep params `{tasks:[{step,status}]}` — rename param `plan`→`tasks`)
- Modify: `backend/plugins/agent/_plan.py` (`PlanStep`→`TaskStep`, `render_plan`→`render_tasks`, `PlanStore`→`TaskStore`; keep behavior)
- Modify: `backend/services/plan_service.py` (event `type:"plan.updated"`→`"tasks.updated"`; `render_plan_steps`→`render_task_steps`; method/docstrings; table name unchanged)
- Rename: `backend/api/routes/plans.py` → `backend/api/routes/tasks.py` (route `/api/plans/{conv}`→`/api/tasks/{conv}`, `PlanResponse`→`TasksResponse`, keep `{conversation_id, steps}` shape; `steps` stays `[{step,status}]`)
- Modify: `backend/api/routes/__init__.py` (import path + router include)
- Modify: `backend/core/event_bus.py` (add `AliceEvent.TASKS_UPDATED = "tasks.updated"` enum member; replace ad-hoc string)
- Modify: `backend/core/app.py` (broadcast bridge `_broadcast_plan_event` → `_broadcast_tasks_event`; wiring var names; the assembly call that re-injects task steps)
- Modify: `backend/api/routes/chat/_assembly.py` (the `render_plan_steps`→`render_task_steps` call only — leave other features for P2)
- Test: `backend/tests/` — update/rename any test referencing `update_plan`/`plan.updated`/`/api/plans`/`PlanStep`.

- [ ] **Step 1:** Grep the backend for `update_plan`, `plan.updated`, `PlanStep`, `render_plan`, `/api/plans`, `plan_service` event usages; list every hit.
- [ ] **Step 2:** Apply the renames above. The `update_tasks` tool keeps replace-whole-list semantics and `{step,status}` items; only the tool name and the top-level arg (`tasks`) change.
- [ ] **Step 3:** Run `ruff check backend && mypy backend` on touched files; fix.
- [ ] **Step 4:** Run `cd backend; pytest tests/ -k "plan or task or agent or assembly" -v`; update assertions to new names; expect PASS.
- [ ] **Step 5:** Commit `refactor(agent): rename update_plan→update_tasks and plan.updated→tasks.updated contract`.

### Task 0.2: Frontend tasks contract rename

**Files:**
- Rename: `frontend/src/renderer/src/types/plan.ts` → `types/tasks.ts` (`PlanStep`→`TaskStep`, `WsPlanUpdatedMessage`→`WsTasksUpdatedMessage` with `type:'tasks.updated'`)
- Rename: `stores/plan.ts` → `stores/tasks.ts` (`usePlanStore`→`useTasksStore`, `planFor`→`tasksFor`, `applyPlanUpdated`→`applyTasksUpdated`, REST `/api/tasks/{conv}`, `byConversation` keyed steps unchanged)
- Modify: `composables/useEventsWebSocket.ts` (route `tasks.updated` → `tasksStore.applyTasksUpdated`)
- Modify: existing consumers `components/canvas/modules/PlanModule.vue` + `PlanStepList.vue` references (temporary: keep rendering tasks until P1·T4/T5 restructure them) — repoint imports to the renamed store/types so the app keeps compiling.
- Test: `frontend` vitest specs referencing the plan store/types.

- [ ] **Step 1:** Grep FE for `usePlanStore`, `PlanStep`, `plan.updated`, `WsPlanUpdated`, `/api/plans`; list hits.
- [ ] **Step 2:** Apply renames; keep `PlanModule`/`PlanStepList` compiling against the new store/types (full restructure is P1·T4/T5).
- [ ] **Step 3:** Run `cd frontend; npm run typecheck`; fix.
- [ ] **Step 4:** Run `npm run test` (vitest) for affected specs; update; expect PASS.
- [ ] **Step 5:** Commit `refactor(fe): rename plan store/types to tasks contract`.

**Phase 0 gate:** backend + frontend build/tests green with the `tasks` contract. No behavior change.

---

## PHASE 1 — Parallel building blocks (8 file-disjoint tracks)

All tracks branch from the Phase-0 tip and touch disjoint files; run concurrently.

### Task T1: Sovereign per-tier tool whitelist

**Files:**
- Modify: `backend/services/permission_mode_policy.py`
- Modify: `backend/core/tool_registry.py`
- Test: `backend/tests/test_permission_mode_policy.py`, `backend/tests/test_tool_registry.py` (or existing)

Design:
- Add to `ModePolicy` a `tool_whitelist: frozenset[str] | None` (None ⇒ permissive: allow all) and keep `priority_plugins` for ordering only. Replace `blocked_capabilities` usage.
- `policy_for(mode, *, custom_guidance: dict[PermissionMode,str] | None = None)`:
  - `PLAN`: `tool_whitelist` resolved per-tool = every tool whose capabilities ⊄ {fs_write, process_exec} **plus** the explicit planning tools `{update_tasks, write_plan, spawn_subagent, ask_user}`. Since the registry isn't known here, express the plan whitelist as a **predicate** `is_allowed(tool_def)` OR resolve it inside the registry. Recommended: keep policy declarative — `blocked_capabilities=frozenset({"fs_write","process_exec"})` + `always_allow_tools=frozenset({"update_tasks","write_plan","spawn_subagent","ask_user"})`; the registry computes the concrete whitelist. Permissive tiers: `blocked_capabilities=frozenset()`, `always_allow_tools=frozenset()`.
  - `guidance`: use `custom_guidance[mode]` if present else `_GUIDANCE[mode]`.
- `ToolRegistry.apply_mode_policy(tools, *, blocked_capabilities=frozenset(), always_allow_tools=frozenset(), priority_plugins=())`:
  - Drop a tool when its ToolDefinition has a capability in `blocked_capabilities`, UNLESS its ns-name ∈ `always_allow_tools`. Unknown/unclassified tools (no def) are kept (permissive default). Then float `priority_plugins` tools to the front. Pure; returns a new list. (This generalizes the current implementation; sovereignty = it runs after RAG too, already the case.)

- [ ] **Step 1:** Write failing tests: plan blocks fs_write/exec tools but keeps `update_tasks`/`write_plan`; permissive tiers keep all; unknown tool kept; priority floats first; custom_guidance overrides default.
- [ ] **Step 2:** Run tests → FAIL.
- [ ] **Step 3:** Implement policy + registry changes.
- [ ] **Step 4:** Tests → PASS; `ruff`+`mypy` clean.
- [ ] **Step 5:** Commit `feat(permissions): sovereign per-tier tool whitelist`.

### Task T2: Plan-document service + table + REST + event

**Files:**
- Modify: `backend/db/models.py` (new `ConversationPlanDocument`: `conversation_id: uuid PK`, `title: str = ""`, `body: str = ""`, `updated_at: datetime`)
- Create: `backend/services/plan_document_service.py` (`PlanDocumentService` mirroring `PlanService`: async `get_document(conv)->{title,body,updated_at}|None`, async `set_document(conv,title,body)` UPSERT + in-memory mirror + emit `{"type":"plan_document.updated", conversation_id, title, body, updated_at}` via injected callback; sync `render_document(doc)->str` for context; `load_all()` startup)
- Create: `backend/api/routes/plan_document.py` (`GET /api/plan-document/{conversation_id}` → `{conversation_id,title,body,updated_at}`; empty when none)
- Modify: `backend/core/event_bus.py` (add `AliceEvent.PLAN_DOCUMENT_UPDATED = "plan_document.updated"`)
- Test: `backend/tests/test_plan_document_service.py`, route test.

- [ ] **Step 1:** Failing tests: set→get round-trips; set replaces wholesale; emits event with body; REST returns empty doc when unset, doc when set.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement model + service + route + event member. Follow `PlanService`/`plans.py` patterns exactly (async, loguru, SQLModel).
- [ ] **Step 4:** Tests → PASS; `ruff`+`mypy` clean. (Route registration + app wiring is P2.)
- [ ] **Step 5:** Commit `feat(plan-doc): ConversationPlanDocument service, REST and event`.

### Task T3: Custom prompts — config + persona append

**Files:**
- Modify: `backend/core/config.py` (under agent config: `prompts.persona: str=""`; `prompts.tier_guidance: dict[str,str]=field(default_factory=dict)` — keys are tier strings; both in the **user** layer, env prefix consistent)
- Modify: `backend/services/llm_service.py` (`get_system_prompt`: after base (+env) and before memory_context, append the global persona block when non-empty, e.g. `\n\n## Istruzioni personalizzate\n\n{persona}`; read from `self._config`. Add `invalidate` parity if persona is cached — keep persona dynamic, not cached.)
- Test: `backend/tests/test_llm_service.py` (persona appended when set; absent when empty; ordering temporal→base→persona).

- [ ] **Step 1:** Failing tests for persona append + config defaults.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement config fields + persona append. (Per-tier `tier_guidance` is consumed in P2 `_helpers`/`_assembly`; here just define + load it.)
- [ ] **Step 4:** Tests → PASS; `ruff`+`mypy` clean.
- [ ] **Step 5:** Commit `feat(prompts): global persona + per-tier guidance config`.

### Task T4: FE Tasks component (TaskStrip + TaskStepList)

**Files:**
- Create: `frontend/src/renderer/src/components/chat/TaskStepList.vue` (move/rename from `canvas/modules/PlanStepList.vue`; identical status rendering; prop `steps: TaskStep[]`)
- Create: `frontend/src/renderer/src/components/chat/TaskStrip.vue` (3-state collapsible: empty placeholder slot "Nessuna attività pianificata"; collapsed ticker = current in_progress step + `n/total` + chevron; expanded panel = header "Attività" + `n/total` + progress bar + `TaskStepList`. Auto-expand when any step is `in_progress` AND streaming; re-collapse when streaming ends or all complete; manual toggle overrides until next turn. Props: `conversationId`. Uses `useTasksStore` + `useChatStore` streaming.)
- Test: `frontend` vitest `TaskStrip.spec.ts` (state transitions, auto-expand, progress count).
- CSS: theme tokens only (`--surface-1/2/3`, `--accent`, `--success`, `--text-*`, `--space-*`, `--radius-md/lg`, `--ease-out-expo`, dashed `--border`).

- [ ] **Step 1:** Failing spec: empty→placeholder; steps present→ticker; in_progress+streaming→expanded; all complete→collapsed.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement both components (reuse PlanStepList markup). Do NOT mount in ChatPanel yet (P2).
- [ ] **Step 4:** `npm run typecheck` + vitest → PASS.
- [ ] **Step 5:** Commit `feat(fe): TaskStrip + TaskStepList components`.

### Task T5: FE Plan-document module + store

**Files:**
- Create: `frontend/src/renderer/src/types/planDocument.ts` (`PlanDocument={title:string;body:string;updatedAt:string}`; `WsPlanDocumentUpdatedMessage={type:'plan_document.updated';conversation_id;title;body;updated_at}`)
- Create: `stores/planDocument.ts` (`usePlanDocumentStore`: `byConversation`, `documentFor(conv)`, `ensureForConversation`, `applyDocUpdated`, `fetch` → `GET /api/plan-document/{conv}`)
- Modify: `components/canvas/modules/PlanModule.vue` (render `documentFor(conv).body` as Markdown via existing `.markdown-body` renderer; header meta "aggiornato HH:MM"; empty state when no body). Module id stays `plan`.
- Test: vitest store spec.

- [ ] **Step 1:** Failing store spec (fetch + applyDocUpdated).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement type + store + module markdown viewer. (Auto-open intent + WS routing is P2.)
- [ ] **Step 4:** `npm run typecheck` + vitest → PASS.
- [ ] **Step 5:** Commit `feat(fe): plan document module + store`.

### Task T6: FE Scope indicator chip + inline popover

**Files:**
- Create: `frontend/src/renderer/src/components/chat/ScopeIndicator.vue` (chip showing active folder: "📁 <name>", "📁 <name> +N", or "📁 Nessuno scope" in `--warning` when unset; tooltip = full paths; click opens a `UiPopover` hosting scope management — reuse `ScopeManager.vue` add/remove/clear logic + idle-guard 409 handling + `scope.updated` frames via `useScopeStore`.)
- Test: vitest `ScopeIndicator.spec.ts` (label states from store).

- [ ] **Step 1:** Failing spec: unset→"Nessuno scope" amber; one folder→name; many→"name +N".
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement (reuse ScopeManager internals; extract a shared composable if cleaner). Do NOT mount in ChatInput yet (P2).
- [ ] **Step 4:** typecheck + vitest → PASS.
- [ ] **Step 5:** Commit `feat(fe): scope indicator chip + inline popover`.

### Task T7: FE ChatToolControls → read-only tier reflection

**Files:**
- Modify: `frontend/src/renderer/src/components/chat/ChatToolControls.vue` (when a tier governs, render a **read-only** reflection: tools in the tier whitelist shown active+locked, excluded shown off+locked with "bloccato dalla modalità <tier>"; with RAG on, show this tier summary instead of a plain disabled chip. It needs the active tier from `usePermissionModeStore` and the tier→whitelist mapping. Expose the whitelist from the backend via the existing tool catalog OR compute client-side from a small tier-capability map mirrored in FE constants. Prefer: backend returns per-tool `capabilities` in the tool catalog so FE can reflect plan's block of fs_write/process_exec.)
- Test: vitest update.

- [ ] **Step 1:** Confirm the tool catalog FE type carries `capabilities`; if not, add it (and ensure backend catalog endpoint returns it — coordinate, small).
- [ ] **Step 2:** Failing spec: in plan, write/exec tools shown locked-off; planning locked-on.
- [ ] **Step 3:** Implement read-only reflection + RAG-on summary.
- [ ] **Step 4:** typecheck + vitest → PASS.
- [ ] **Step 5:** Commit `feat(fe): tool controls reflect active tier (read-only)`.

### Task T8: FE Settings — Agent / Persona section

**Files:**
- Create: `frontend/src/renderer/src/components/settings/AgentPersonaSettings.vue` (global persona textarea; 4 per-tier guidance textareas each with "Ripristina default"; relocate the **global tool catalog master switches** here from the in-chat popover. Reads/writes via settings store / config REST.)
- Test: vitest (renders fields; reset restores default text).

- [ ] **Step 1:** Identify the settings config round-trip (settings store + `/config` or `/api/agent/prompts`). If no field exists, add `agent.prompts` to the settings store typed config (mirrors backend T3).
- [ ] **Step 2:** Failing spec for render + reset.
- [ ] **Step 3:** Implement section (do NOT register into Settings nav yet — P2).
- [ ] **Step 4:** typecheck + vitest → PASS.
- [ ] **Step 5:** Commit `feat(fe): agent persona + per-tier prompt settings`.

**Phase 1 gate:** all 8 tracks merged to the working branch; backend + frontend build green; each track's tests pass. Nothing user-visible wired yet.

---

## PHASE 2 — Integration wiring (sequential, shared files)

### Task 2.1: Agent plugin `write_plan` + planning capability + app wiring

**Files:**
- Modify: `backend/plugins/agent/plugin.py` (add `write_plan` tool: params `{title?:str, document:str}`, capability `("planning",)`; handler calls `ctx.plan_document_service.set_document(conv,title,document)`, returns ok+rendered. Ensure `update_tasks` and `write_plan` carry capability `planning` so the whitelist's `always_allow_tools` matches.)
- Modify: `backend/core/app.py` (construct `PlanDocumentService`, wire its emit callback to the WS broadcast bridge, call `load_all()` at startup, expose on `AppContext`; add `plan_document_service` to `core/context.py` + a Protocol in `core/protocols.py`)
- Modify: `backend/core/context.py`, `backend/core/protocols.py` (add `plan_document_service`)
- Test: plugin dispatch test for `write_plan`.

- [ ] Step 1: Failing test: calling `write_plan` persists + emits.
- [ ] Step 2: FAIL.
- [ ] Step 3: Implement tool + wiring.
- [ ] Step 4: PASS; ruff/mypy.
- [ ] Step 5: Commit `feat(agent): write_plan meta-tool + plan-document wiring`.

### Task 2.2: Turn assembly — whitelist, plan body, per-tier guidance, persona

**Files:**
- Modify: `backend/api/routes/chat/_assembly.py` (resolve `policy = policy_for(mode, custom_guidance=ctx.config.agent.prompts.tier_guidance)`; after tool selection, `apply_mode_policy(tools, blocked_capabilities=..., always_allow_tools=..., priority_plugins=...)`; guarantee planning tools via `get_tools_for_plugins({"agent"})`; inject plan-document body into memory_context (fetch `ctx.plan_document_service.get_document`); keep task-steps injection; prepend `_build_permission_context`. Persona is appended by `llm_service` already (T3).)
- Modify: `backend/api/routes/chat/_helpers.py` (`_build_permission_context` uses `policy.guidance` which already resolves custom per-tier text from T1/T3)
- Modify: `backend/api/routes/__init__.py` (register `tasks` router (P0 done) + new `plan_document` router)
- Test: assembly tests (whitelist applied per tier; plan body injected; custom guidance used).

- [ ] Step 1: Failing assembly tests.
- [ ] Step 2: FAIL.
- [ ] Step 3: Implement wiring (order: temporal→base→persona→AMBITO+MODALITÀ→plan body→tasks→memory).
- [ ] Step 4: PASS; ruff/mypy.
- [ ] Step 5: Commit `feat(chat): wire whitelist + plan body + custom per-tier guidance into assembly`.

### Task 2.3: FE composer integration

**Files:**
- Modify: `components/canvas/ChatPanel.vue` (mount `<TaskStrip :conversation-id>` directly above `<ChatInput>` in the footer area, workspace only)
- Modify: `components/chat/ChatInput.vue` (add `<ScopeIndicator>` to the "Agente" group; chip order **scope → strumenti → tier**; keep container-query responsiveness)
- Modify: `composables/workspace/moduleRegistry.ts` (keep `plan` module = doc viewer; **retire `scope` module**)
- Modify: `composables/useEventsWebSocket.ts` (route `plan_document.updated` → `planDocumentStore.applyDocUpdated`; tasks already routed in P0)
- Modify: module intent bus / `PanelWorkspace.vue` (auto-open/foreground `plan` module on `plan_document.updated`)
- Modify: Settings nav registration to include `AgentPersonaSettings.vue`
- Test: vitest where feasible (ChatInput renders scope chip; ChatPanel mounts TaskStrip).

- [ ] Step 1: Mount + wire all of the above.
- [ ] Step 2: `npm run typecheck` + `npm run lint` clean.
- [ ] Step 3: vitest affected specs PASS.
- [ ] Step 4: Commit `feat(fe): mount TaskStrip, scope indicator, plan-doc auto-open, persona settings`.

**Phase 2 gate:** end-to-end wired; contracts consistent (event/REST/type/store).

---

## PHASE 3 — Verification

### Task 3.1: Backend full check
- [ ] `cd backend; ruff check .; mypy .` — clean on touched files (pre-existing noise documented, not introduced).
- [ ] `cd backend; pytest tests/ -v` — green except the documented pre-existing/environment failures (`test_config.py::test_plugins_enabled_list`, 5 `test_context.py` compression-split, `test_voice_tool_calling…no_stt_service`). If the plugins-enabled count assertion now also counts a new plugin, that's unrelated — leave as documented.

### Task 3.2: Frontend full check
- [ ] `cd frontend; npm run typecheck` — clean.
- [ ] `cd frontend; npm run lint` — clean.
- [ ] `cd frontend; npm run test` — green.

### Task 3.3: Contract sweep
- [ ] Grep for any lingering `update_plan`, `plan.updated`, `/api/plans`, `usePlanStore`, `PlanStep` — zero hits outside intentional internal table name.
- [ ] Manual smoke (user, app running): plan tier → agent writes plan.md (module auto-opens) + tasks appear fixed above composer; switch to autopilot → tasks tick off; scope indicator shows folder / amber when unset; tool chip read-only reflects tier; Settings persona + per-tier text persist and affect prompt.

### Task 3.4: Memory + docs
- [ ] Update memory note `fase7-tiered-permissions.md` with this extension (whitelist sovereign, plan-vs-tasks, persona/per-tier prompts, scope indicator) once landed.

---

## Self-review notes
- Spec §1–§7 each map to tasks: rename (P0), tasks component (T4+2.3), plan doc (T2+T5+2.1+2.3), whitelist (T1+2.2), scope (T6+2.3), prompts (T3+T8+2.2/2.3), integration (2.1–2.3).
- Type consistency: `TaskStep{step,status}`, `update_tasks(tasks=[…])`, event `tasks.updated`, `plan_document.updated`, `ModePolicy.blocked_capabilities`+`always_allow_tools`+`priority_plugins`, `apply_mode_policy(tools, blocked_capabilities, always_allow_tools, priority_plugins)`, `agent.prompts.{persona,tier_guidance}` — used consistently across tasks.
- Open point D resolved: global tool disable = outer master filter (kept), in-chat popover read-only (T7), master switches relocated to Settings (T8).
