# Fase 7 — Claude-Code parity: implementation status

Branch: `fase7-tiered-permissions` (off `main` @ `f474a86`).
Plan of record: `~/.claude/plans/inizieremo-ad-implementare-tutto-async-pebble.md`.

**Status: COMPLETE.** All planned phases (A → E2) are implemented, tested, and
committed. This file is the durable record of what shipped.

## Done (committed, tested)

| Commit | Phase | What |
|---|---|---|
| `bf65213` | **A** | Tiered permission core — `PermissionMode` + `PermissionModeService`, `PermissionService.decide()` (ALLOW/DENY/NEEDS_CONFIRMATION), `PermissionRuleService` (persistent deny>ask>allow), pipeline threading, STRICT-default shim, DB models, REST routes, DI. |
| `5ffb77f` | **C (backend)** | `capabilities`/`path_args` on all `file_search` tools; `fallback_mode` default → `disabled` (no scope ⇒ fs tools blocked). |
| `57e2504` | **D** | Single-instance modules + context-menu toggle; visibility decoupled from lifecycle. |
| `0a36670` | **C (FE)** | `ScopeManager` lifted into its own first-class `Scope` module; removed from Terminal. |
| `b7d3270` | **B (core)** | Permission-tier selector in the workspace input bar + `permissionMode` store + REST/WS + types. |
| `9f82fd9` | **fix** | `write_text_file` rejects empty content (test fix) + this status doc. |
| `d658cfa` | **B (polish)** | Approval-card "remember" choice (none/session/persistent) + persistent-rules Settings panel + rule types/API. Tier selector reaches the assistant/orb surface via the shared `ChatInput`. |
| `00c359f` | **E1 (backend)** | Real interactive PTY terminal: `TerminalSessionManager`, `PtyProcess` backends (winpty/posix/fake), Win32 job tree-kill, `/api/terminal` REST, events-WS live I/O, DI + cleanup. |
| `d9286ec` | **E2** | Agent `run_terminal_command` runs in + mirrors output to the assigned terminal session. |
| `e817f0d` | **E1 (FE)** | xterm.js multi-tab `TerminalModule` (rename / assign / kill / reattach) + `terminalSessions` store + events-WS singleton `sendEventsMessage` + launcher "N active" badge. |
| `ccb3f7a` | **test** | Module-registry spec updated to 7 ids (scope module). |

### Invariants enforced
- **The model can never set the permission tier, the scope, or the terminal
  assignment** — all three surfaces are kept out of the tool registry
  (anti-privilege-escalation).
- **No scope set ⇒ every filesystem tool *and* the terminal is blocked**, in
  every tier (autopilot included). Reads inside scope never prompt.
- `mode=strict` (the default) reproduces the pre-Fase-7 gate exactly — verified
  behaviour-preserving across the turn/permission suite.
- **Exactly one** agent-assigned terminal session per conversation.
- Terminal REST (create/kill/rename/assign) is **not** idle-guarded; live
  keystroke I/O travels over the events-WS receive loop, never blocked by a turn.

### The 4 tiers (`PermissionService.decide`)
`strict` (prompt for confirmation-required/write/exec) → `auto_edits`
(auto-approve safe in-scope writes; prompt dangerous/exec) → `plan` (read-only;
block write/exec) → `autopilot` (no prompts; circuit-breakers still hold:
forbidden, no-scope, out-of-scope, deny-rule).

## Verification

```powershell
# Backend (from backend/, venv at repo-root .venv) — 284 passed, 1 skipped:
pytest tests/test_pty_backend.py tests/test_terminal_session_manager.py `
  tests/test_terminal_routes.py tests/test_terminal_agent_mirror.py `
  tests/test_terminal_plugin.py tests/test_terminal_security.py `
  tests/test_terminal_executor.py tests/test_permission_*.py `
  tests/test_scope_service.py tests/test_pipeline.py tests/test_tool_loop.py `
  tests/test_confirmation_toggle.py tests/test_file_search_plugin.py -q
ruff check services/terminal/ api/routes/terminal.py ; mypy services/terminal/
# A real-ConPTY integration test runs on Windows when pywinpty is installed.

# Frontend (from frontend/) — 163 vitest passed:
npm run typecheck ; npx vitest run
```

### Known pre-existing failures (NOT Fase 7 regressions)
- `test_config.py::test_plugins_enabled_list` — hard-codes `len == 19` but
  `default.yaml` lists 20 plugins (upstream drift).
- `test_context.py` 5 compression-split tests — `context_manager` logic,
  untouched by Fase 7.

## Manual GUI checklist (needs the Electron app running)
The PTY backend is verified headlessly (fake + real ConPTY) and the FE passes
typecheck/lint/vitest, but the live xterm rendering needs the app:
1. Set a workspace scope (Scope module), enable `terminal.enabled`.
2. Open the Terminal module → a shell appears; type `dir` / `ls`.
3. Open a 2nd tab; rename a tab; assign one to the agent (⚡).
4. Run an agent command → it appears in the assigned tab; cwd = scope.
5. Close the module, reopen → sessions reattach with scrollback; badge shows N.
6. Kill a tab → process tree dies (verify no orphaned grandchildren).
