# Fase 7 — Claude-Code parity: implementation status

Branch: `fase7-tiered-permissions` (off `main` @ `f474a86`).
Plan of record: `~/.claude/plans/inizieremo-ad-implementare-tutto-async-pebble.md`
(also summarised here). This file tracks what is DONE vs REMAINING so the work is
resumable on any machine.

## Done (committed, tested)

| Commit | Phase | What |
|---|---|---|
| `bf65213` | **A** | Tiered permission core — `PermissionMode` + `PermissionModeService`, `PermissionService.decide()` (ALLOW/DENY/NEEDS_CONFIRMATION), `PermissionRuleService` (persistent deny>ask>allow), pipeline threading, STRICT-default shim, DB models, REST routes, DI. |
| `5ffb77f` | **C (backend)** | `capabilities`/`path_args` on all `file_search` tools; `fallback_mode` default → `disabled` (no scope ⇒ fs tools blocked). |
| `57e2504` | **D** | Single-instance modules + context-menu toggle; visibility decoupled from lifecycle. |
| `0a36670` | **C (FE)** | `ScopeManager` lifted into its own first-class `Scope` module; removed from Terminal. |
| `b7d3270` | **B (core)** | Permission-tier selector in the workspace input bar + `permissionMode` store + REST/WS + types. |

### Invariants enforced
- **The model can never set the permission tier or the scope** — both surfaces
  are kept out of the tool registry (anti-privilege-escalation).
- **No scope set ⇒ every filesystem tool is blocked, in every tier** (autopilot
  included). Reads inside scope never prompt.
- `mode=strict` (the default) reproduces the pre-Fase-7 gate exactly — verified
  behaviour-preserving across the turn/permission suite.

### The 4 tiers (`PermissionService.decide`)
`strict` (prompt for confirmation-required/write/exec) → `auto_edits`
(auto-approve safe in-scope writes; prompt dangerous/exec) → `plan` (read-only;
block write/exec) → `autopilot` (no prompts; circuit-breakers still hold:
forbidden, no-scope, out-of-scope, deny-rule).

## Remaining

### Fase B — polish (FE)
- Tier selector on the **assistant/orb** surface (`AssistantView` composer).
- **Approval card "remember"**: the backend already accepts a `remember`
  field (`none`/`session`/`persistent`) on the `tool_confirmation` response and
  wires it to `PermissionService.grant` / `PermissionRuleService.add_rule`
  (see `ConfirmationMiddleware._persist_remember`). The FE confirmation dialog
  must add Yes / Yes-don't-ask-again(session|persistent) / No and send
  `remember` in the response frame.
- **Settings rules panel**: list/add/remove persistent rules via
  `GET/POST/DELETE /api/permission-rules/{conversation_id}`.

### Fase E1 — real interactive PTY terminal (the big remaining piece)
Backend (coupled-core, manual, testable against a fake):
- `backend/services/terminal/{session,manager,pty_backend,job}.py`:
  - `TerminalSessionManager` mirroring `ScopeService` — per-conversation dict,
    sync `get_session/list_sessions/assigned_session`, async
    `create_session/write_input/resize/kill_session/rename/cleanup_conversation`;
    **exactly one** `agent_assigned` session per conversation; `cwd` validated
    in-scope via the existing `backend/plugins/terminal/security.py` primitives
    (`validate_cwd_within_scope`, `ensure_sandbox`).
  - `PtyProcess` Protocol + `WinptyPtyProcess` (pywinpty/ConPTY, **thread bridge**
    for the blocking read on the ProactorEventLoop, `CREATE_NO_WINDOW`, reuse
    `_reduced_env`) + `SubprocessPtyFallback` (non-Windows/missing lib) +
    `FakePtyProcess` (tests).
  - `job.py`: Win32 Job Object (`KILL_ON_JOB_CLOSE`) for **process-tree kill** —
    fixes the documented grandchild-survival limit in `terminal/executor.py:62`.
  - `pywinpty` is NOT yet a dependency — add to `backend/pyproject.toml` and the
    PyInstaller spec (`--collect-all pywinpty`).
- `backend/api/routes/terminal.py` (mirror `scope.py`): GET/POST/DELETE/PATCH.
  **Idle-guard split**: create/kill may reuse `conversation_active` (409); live
  I/O (`terminal.input`/`terminal.resize`) goes over WS control frames and is
  NEVER idle-guarded (type during a turn). Outbound:
  `terminal.session_opened/output/closed/renamed`.
- App wiring + `AppContext.terminal_session_manager` + cleanup on conv delete.

FE:
- Add **xterm.js** to `frontend/package.json`.
- Rebuild `TerminalModule.vue` as a real interactive terminal with **tabs**
  (multi-instance), rename, "assign to agent" toggle; a terminal-sessions store
  mirroring `scope.ts`; **reattach** live sessions on reopen; a "N terminals
  active" badge when the module is closed; per-tab kill.

### Fase E2 — agent commands stream into the assigned session
- `terminal/plugin.py::execute_tool` keeps the bounded discrete `run_command`
  but resolves `cwd` from `manager.assigned_session(conv).cwd` (auto-create) and
  emits `terminal.output` (`$ cmd` + result block) into that session. Tier
  gating via `decide()` unchanged. Human typing stays raw/ungated. Audit each
  agent command.

## Why E1/E2 weren't completed this session
The PTY subsystem needs `pywinpty`/ConPTY plus real Windows-GUI verification
(interactive shell, resize, tree-kill) that cannot be exercised headlessly, and
the FE needs the Electron app running to verify xterm behaviour. Per the "no
debt / everything verified" rule, it is left as a clean, well-specified next
step rather than committed half-verified. The session-manager + job-kill +
routes backend (testable against `FakePtyProcess`) is the recommended first
slice when resuming.

## Verify what's done
```powershell
# Backend (from backend/, venv at repo-root .venv)
pytest tests/test_permission_*.py tests/test_pipeline.py tests/test_tool_loop.py `
  tests/test_confirmation_toggle.py tests/test_scope_service.py -q
ruff check . ; mypy .
# Frontend (from frontend/)
npx vitest run src/renderer/src/stores/permissionMode.spec.ts `
  src/renderer/src/stores/workspace.spec.ts
npm run typecheck
```
