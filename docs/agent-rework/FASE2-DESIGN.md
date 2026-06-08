# Fase 2 — implementation design notes (working)

Authoritative spec: `PLAN.md` → "Fase 2" + `HANDOFF.md` §6. This file records
the **how** decisions made while implementing, so a resume is trivial.

## Commit sequence (small, behavior-preserving steps)
1. **tags** — `ToolDefinition.capabilities`/`path_args` (`core/plugin_models.py`). Isolated.
2. **config** — neutral `PermissionsConfig` (`permissions` block) + legacy migration
   (`pc_automation.confirmations_enabled|confirmation_timeout_s` → `permissions.*`,
   popped per-layer in `migrate_legacy_config_keys`). Switch readers:
   `tool_loop.py` (confirmations_enabled), `direct_executor.py` (timeout),
   `settings.py` route, `config.py` route (GET reads new home; PUT writes new home).
   `default.yaml`: move the 2 keys to a `permissions:` block. Update tests:
   `_turn_helpers.make_ctx` (→ `permissions`), `test_tool_calling` (→ `PermissionsConfig`),
   `test_confirmation_toggle` (mock `cfg.permissions`), `test_tool_loop._PcAutoCfg`+`_Cfg`.
3. **service** — `services/permission_service.py` + `AppContext.permission_service`
   DI (typed via a `protocols.py` Protocol) + `app.py` wiring + `test_permission_service.py`.
4. **pipeline** — `services/turn/pipeline.py` (5 middlewares) + `test_pipeline.py`. Not wired.
5. **wire** — refactor `tool_loop.py` gate loop to drive the pipeline. 57 stay green.

## Pipeline execution model (preserves current two-phase behavior)
Current engine = **sequential gate** (parse → dedup → forbidden → confirm → start+seen.add →
client-exec inline OR defer) **+ parallel server-execute batch** + result persistence.
The 57 tests pin counts/names, NOT parallel timing — but the plan mandates
behavior-preserving, so keep the two phases.

Mapping onto the plan's 5-middleware chain (Dedup→Permission→Confirmation→Interaction→Execute):
- **Gate chain** = `[Dedup, Permission, Confirmation, Interaction]`, run **sequentially** per
  call. `Interaction` emits `tool_execution_start` + `seen.add` for every greenlit call
  (both client and server, matching current order), then: client_execution → channel
  round-trip → terminal `CLIENT_EXECUTED`; server → returns `EXECUTE` (defer).
- **Execute** = `ExecuteMiddleware`, run as a **parallel batch** over deferred (`EXECUTE`)
  calls — exactly the current `asyncio.wait(tasks)`.
- Split point Interaction|Execute == current gate-loop|parallel-batch split. Faithful.

### Parse/no-name validation
Stays in the engine's ToolCall construction (pre-pipeline): bad JSON → `PARSE_ERROR`,
missing name → `NO_NAME` terminal outcomes. The pipeline only sees well-formed calls.

### Persistence / audit stays in the engine
Middlewares decide + do channel round-trips; they annotate the mutable `ToolCall`
(`audit_decision`, `result`, `disposition`). The engine's `_persist_outcome` maps
disposition → (DB tool msg text, sink frames, audit row, artifacts/image). Per-disposition
behavior table (must match current exactly): see PLAN/HANDOFF + tool_loop.py今.

### Dedup ordering
`seen` lives in the engine (loop-level, across iterations). DedupMiddleware READS it
(skip for client tools); the engine/Interaction WRITES it only when a call is greenlit —
so a rejected call can be retried later (current invariant, comment at tool_loop.py:295).
Sequential gate ⇒ within-iteration dups deduped deterministically (test relies on this).

## PermissionService (Fase 2 = inert scope, live forbidden)
- `evaluate(tool_name, args, tool_def, conversation_id) -> PermissionDecision`.
- forbidden risk → DENY(forbidden). scope confinement is **inert** in Fase 2 (no scope
  provider yet; ScopeService is Fase 6) → ALLOW. ⇒ no new denials, behavior preserved.
- per-conversation grants implemented + tested, not yet consulted by the loop.
- capability/path_args drive by-construction confinement in Fase 6.
- Engine obtains it via `isinstance(getattr(ctx,'permission_service',None), PermissionService)`
  else builds a default — robust against MagicMock/SimpleNamespace test ctxs.

## Confirmation toggle home (back-compat)
Canonical: `config.permissions.confirmations_enabled` / `confirmation_timeout_s`.
Old `pc_automation.*` keys migrate via `migrate_legacy_config_keys` (covers default.yaml,
user.yaml, persisted dotted prefs via `_set_dotted`+per-layer migrate, env, direct ctor).
`/settings/tool-confirmations` API contract (`{confirmations_enabled}`) is UNCHANGED — only
internal storage path moves; FE untouched. `_request_confirmation`/`_execute_client_tool`
live in `pipeline.py` as patchable module fns (test_confirmation_toggle patches there).
