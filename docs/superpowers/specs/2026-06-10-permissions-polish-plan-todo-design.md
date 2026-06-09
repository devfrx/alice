# Design — Permissions polish + Plan/Tasks distinction

Date: 2026-06-10
Branch base: `home-rework-editorial-dossier` (work continues here unless told otherwise)
Status: approved design, ready for implementation plan

## Goal

Polish the Fase-7 permission system so each tier's features are **distinct and
legible** (tool management, scope, custom prompts), and introduce a clean
**Plan vs Tasks** separation:

- **Plan** — a written Markdown document the agent authors (`write_plan`),
  shown in the (repurposed) plan module.
- **Tasks** — the live executable checklist (the current `update_plan`,
  renamed `update_tasks`), shown **fixed near the composer**, ticked off as the
  agent progresses.

Reuse existing UI and CSS theme tokens wherever possible; add new generic
components only where needed.

---

## 1. Naming & contract changes (do first — everything else builds on it)

The current todo mechanism is misnamed now that a real plan document exists.
Rename across the stack for clarity:

| Concept | Old | New |
|---|---|---|
| Tasks meta-tool | `update_plan` | **`update_tasks`** |
| Tasks UI label | "Piano operativo" | **"Attività"** |
| Tasks WS event | `plan.updated` | **`tasks.updated`** |
| Tasks REST | `GET /api/plans/{conv}` | **`GET /api/tasks/{conv}`** |
| Tasks store (FE) | `usePlanStore` | **`useTasksStore`** |
| Tasks types (FE) | `plan.ts` (`PlanStep`) | **`tasks.ts` (`TaskStep`)** |
| Plan document meta-tool | — (new) | **`write_plan`** |
| Plan document module | `PlanModule` (todo list) | **`PlanModule`** (markdown doc) |

`update_tasks` keeps the existing replace-whole-list semantics (`PlanStep` →
`TaskStep`: `{step, status}` with `pending|in_progress|completed`). The DB table
`conversation_plans` may keep its name internally (low value to migrate) but all
**contract-facing** names (event, REST, FE) move to `tasks`.

---

## 2. Tasks component (new — NOT a module)

A collapsible panel rendered **above the composer** in the Workspace chat
surface only (in `ChatPanel`, directly above `ChatInput`). Three states:

1. **Empty (placeholder)** — a thin, always-present slot: "Nessuna attività
   pianificata". (User chose "always visible" — keep a discreet fixed slot.)
2. **Collapsed (ticker)** — one line: current `in_progress` step + `3/7`
   progress + expand chevron.
3. **Expanded (panel)** — header ("Attività" + `n/total` + collapse chevron),
   a thin progress bar, and the full `TaskStepList`.

Behavior:
- **Auto-expands** to the full panel when a step flips to `in_progress` (agent
  actively working); **re-collapses** to the ticker when the turn ends / all
  steps complete. Manual expand/collapse always allowed and wins until the next
  turn.
- Appears/updates from the `tasks.updated` WS frame and `GET /api/tasks/{conv}`
  snapshot (existing flow, renamed).

Reuse:
- `PlanStepList.vue` → `TaskStepList.vue` (same status-aware rendering: done =
  strikethrough + `--success` check, in_progress = pulsing `--accent` dot,
  pending = `--text-muted` ring). Move it out of `canvas/modules/`.
- New thin wrapper `TaskStrip.vue` owns the three states + auto-expand logic.
- Store: rename `plan` store → `tasks` store; `TaskStrip` subscribes to
  `tasksStore.tasksFor(conversationId)` + `streaming` to drive auto-expand.

CSS: existing tokens only — `--surface-1/2/3`, `--accent`, `--success`,
`--text-*`, `--space-*`, `--radius-md/lg`, `--ease-out-expo`, dashed
`--border` for the empty slot.

---

## 3. Plan document (.md) — `write_plan` + repurposed module

### Tool
New `agent`-plugin meta-tool **`write_plan`**:
- Capability **`planning`** (NOT `fs_write`) ⇒ allowed in **plan** mode and in
  every tier; never gated as a filesystem write.
- Single living document per conversation: each call **replaces** the whole
  markdown body (model owns current truth, same philosophy as `update_tasks`).
- Args: `{ "document": "<markdown>" }` (optionally a short `title`).

### Persistence & contract
- New service `PlanDocumentService` (mirrors `PlanService`): table
  **`conversation_plan_documents`** `{conversation_id PK, title, body,
  updated_at}`.
- Event **`plan_document.updated`** `{conversation_id, title, body, updated_at}`
  broadcast over the events WS (same bridge as `tasks.updated`).
- REST **`GET /api/plan-document/{conversation_id}`** → `{conversation_id,
  title, body, updated_at}` (empty body when none).
- Re-injection into context: the current plan body is appended to
  `memory_context` per turn (like task steps are today) so the model sees its
  own plan.

### UI
- `PlanModule.vue` repurposed as a **Markdown viewer** (reuse `ModulePanel`
  chrome + existing `.markdown-body` rendering). Header meta: "aggiornato HH:MM
  · `<tier>`".
- New FE store `planDocument` (`documentFor(conv)`, `applyDocUpdated`, `fetch`)
  + type `planDocument.ts`. Module id stays `plan` in `moduleRegistry`.
- **Auto-open / foreground** on every `write_plan` (reuse the module intent bus
  used for artifacts).

---

## 4. Permissions — per-tier tool whitelist (sovereign)

### Mechanism (centralized)
Extend `services/permission_mode_policy.py` so each tier carries a **tool
whitelist**. Granularity is **per-tool**, but **only restrictive tiers spell it
out**; permissive tiers (`strict`, `auto_edits`, `autopilot`) whitelist
everything.

- Represent the whitelist as a predicate the policy resolves to a concrete set
  given the live tool catalog. For `plan`: derive from capabilities (exclude
  `fs_write`, `process_exec`) **and** guarantee the planning tools
  (`update_tasks`, `write_plan`, `spawn_subagent`, `ask_user`) are present —
  i.e. an explicit, per-tool list for the restrictive tier. Permissive tiers:
  whitelist = all.
- `ModePolicy` gains `tool_whitelist` (resolved set / predicate), which
  **supersedes `blocked_capabilities`** as the way to restrict the offered set.
  `priority_plugins` is **retained** purely for ordering (lead-with-planning).

### Sovereignty + RAG bound
- The whitelist is **sovereign**: it governs the offered toolset whether RAG is
  off (full candidate set) or on (the tier whitelist **bounds** what RAG may
  surface — RAG selects only within it).
- `ToolRegistry.apply_mode_policy` becomes **whitelist-based**: keep tools whose
  ns-name is in the resolved whitelist (unknown/unclassified tools follow the
  permissive default of their tier), drop the rest, then float `priority_plugins`
  to the front. Pure, returns a new list.
- **Outer master filter (resolution of open point D):** the global per-tool
  enable/disable (the Settings tool catalog) still applies **first** — a tool
  the user globally disabled is never offered, in any tier. The tier whitelist
  restricts further within the globally-enabled set.

### In-chat "Strumenti" popover → informative / read-only
`ChatToolControls.vue` stops being an editor of the global selection in-chat and
becomes a **read-only reflection of the active tier**:
- Included tools → shown active + locked. Excluded → shown off + locked, with a
  "bloccato dalla modalità <tier>" hint.
- With **RAG on**, instead of a plain disabled chip, the chip shows this tier
  summary (e.g. "plan · scrittura ed exec off; pianificazione in evidenza").
- Editing the global tool catalog moves to **Settings** (master switches live
  where the persona/prompt settings go — see §6).

---

## 5. Permissions — scope indicator + inline management

- New **`ScopeIndicator.vue`** chip in the `ChatInput` "Agente" group. Chip
  order in the control row: **scope → strumenti → tier** ("dove" before "come").
- Shows the **active folder name**: "📁 Desktop", "📁 Desktop +2" for multiple,
  and **"📁 Nessuno scope" in amber (`--warning`)** when unset. Tooltip lists
  full paths.
- Click → **inline management popover** (`UiPopover`) reusing `ScopeManager.vue`
  logic (add/remove/clear, idle-guard 409 handling, `scope.updated` frames).
  The separate `ScopeModule` becomes redundant — retire it from the module
  registry (keep `ScopeManager` logic, now hosted in the popover).
- Unchanged: manual folder picker, **uniform read-write** permissions per
  folder, idle-guard on mutate.

---

## 6. Permissions — custom system prompts (two levels)

Two user-editable layers, both edited in **Settings** (new "Agente / Persona"
section), persisted in the **user config layer** (`LayeredConfigService`),
rebuilt into `ctx.config` on save:

1. **Global persona** — free text **appended** to the base system prompt
   (base structure/rules preserved). Applies everywhere (workspace + voice).
   Wired in `llm_service.get_system_prompt` (append after base, before
   memory_context).
2. **Per-tier guidance** — four editable texts that **replace** the hardcoded
   `_GUIDANCE[tier]` blocks, each with **"ripristina default"** restoring the
   shipped Italian text. `_build_permission_context` uses the custom per-tier
   text when set, else the default from `permission_mode_policy`.

Config shape (user layer), e.g. under `agent.prompts`:
```
agent.prompts.persona: str = ""              # global, appended
agent.prompts.tier_guidance: dict[tier,str]  # overrides, empty ⇒ default
```
REST: extend the existing config GET/PUT surface (no new bespoke endpoints if
the config route already round-trips these); otherwise add
`GET/PUT /api/agent/prompts`. Settings section also hosts the **global tool
catalog** master switches relocated from the in-chat popover (§4).

---

## 7. Integration & behaviors

- **plan tier deliverable**: the per-tier guidance steers the agent to produce
  **both** a plan `.md` (`write_plan`) **and** the executable tasks
  (`update_tasks`), then invite the user to switch to `auto_edits`/`autopilot`
  to execute. `write_plan` + `update_tasks` are guaranteed present (planning
  whitelist) and float to the front in plan.
- Plan document and tasks are **per-conversation and persist across tier
  changes** — switching plan → autopilot keeps both; execution ticks the tasks.
- All injected prompt blocks keep their order: temporal → base (+env) → persona
  → `[AMBITO DI LAVORO]` + `[MODALITÀ OPERATIVA]` (custom per-tier) → plan body
  → tasks → other memory context.

---

## 8. Components & files (reuse-first)

**Backend**
- `plugins/agent/plugin.py` — rename `update_plan`→`update_tasks`; add
  `write_plan`; register `planning` capability for both.
- `plugins/agent/_plan.py` — `PlanStep`→`TaskStep` naming (internal).
- `services/plan_service.py` — tasks (event/REST renamed to `tasks`).
- `services/plan_document_service.py` — **new** (document).
- `services/permission_mode_policy.py` — per-tier whitelist + custom guidance
  passthrough.
- `core/tool_registry.py` — whitelist-based `apply_mode_policy`.
- `api/routes/chat/_assembly.py`, `_helpers.py` — wire whitelist, plan body,
  custom per-tier text, persona.
- `services/llm_service.py` — append global persona.
- `core/config.py` — `agent.prompts.*`.
- `db/models.py` — `conversation_plan_documents`.
- `api/routes/` — `tasks.py` (renamed `plans.py`), `plan_document.py` (new),
  config/prompts surface.
- `core/event_bus.py` — add `tasks.updated`, `plan_document.updated` as proper
  members (currently ad-hoc strings).

**Frontend**
- `components/chat/TaskStrip.vue` — **new** (3-state collapsible panel).
- `components/chat/TaskStepList.vue` — moved/renamed from
  `canvas/modules/PlanStepList.vue`.
- `components/canvas/modules/PlanModule.vue` — markdown viewer.
- `components/chat/ScopeIndicator.vue` — **new** chip + inline popover (reuses
  `ScopeManager`).
- `components/chat/ChatToolControls.vue` — read-only tier reflection.
- `components/chat/ChatInput.vue` — add scope chip, reorder group; host
  `TaskStrip` is in `ChatPanel` above `ChatInput`.
- `components/settings/…` — "Agente / Persona" section (persona, 4 tier texts,
  tool master switches).
- stores: `tasks` (renamed `plan`), `planDocument` (new); types `tasks.ts`,
  `planDocument.ts`.
- `moduleRegistry.ts` — `plan` module → doc viewer; retire `scope` module.
- WS handler — route `tasks.updated`, `plan_document.updated`.

---

## 9. Testing

- Backend: `update_tasks`/`write_plan` tool dispatch + persistence + events;
  `PlanDocumentService`; whitelist resolution per tier (incl. RAG-bound and
  unknown-tool default); `apply_mode_policy` whitelist semantics; custom
  per-tier guidance + persona injection in assembly; gate unchanged.
- Frontend (vitest): `TaskStrip` state machine (empty/ticker/panel,
  auto-expand on in_progress, re-collapse), `ScopeIndicator` label states,
  `ChatToolControls` read-only reflection, store renames.
- Keep contract consistency (event/REST/type/store) green; run `typecheck` +
  `mypy`/`ruff`.

---

## 10. Out of scope / non-goals

- Tasks derived from / synced to the plan document (they stay independent).
- Per-folder read-only scope, scope presets/auto-suggest, plan versioning.
- Per-conversation or per-scope custom prompts (only global persona + per-tier).
- User-editable per-tier tool whitelists in UI (whitelists are code-defined;
  the in-chat popover is read-only).

## 11. Risks

- Broad rename (`plan`→`tasks`) touches many contract points — sequence it
  first and verify every caller (WS/REST/type/store) in lockstep.
- Whitelist refactor must preserve the existing gate precedence (the whitelist
  shapes *offering*, the gate still decides ALLOW/DENY/CONFIRM).
- Small-model drift in plan mode: rely on whitelist (tools simply absent) more
  than on prose.
