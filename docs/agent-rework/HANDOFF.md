# AL\CE — Agent Rework · HANDOFF (resume on another machine)

> **You are the next Claude Code agent.** This is a self‑contained runbook to
> continue the *"single agentic path + professional foundation"* rework from
> exactly where the previous session stopped, **without repeating its
> mistakes**. Everything you need is in this `docs/agent-rework/` folder, which
> is **committed to the `agent-rework` branch and pushed to `origin`** — nothing
> depends on the previous machine's local `~/.claude/` plan or memory files.
>
> **Delivery invariant (must hold before you rely on this):** the source machine
> ran `git add docs/agent-rework && git commit && git push -u origin
> agent-rework`. Verify with `git ls-remote --heads origin agent-rework`; if it's
> empty, the handoff was not completed — push from the source machine first.

Companion files in this folder:
- **`PLAN.md`** — the full approved plan (taxonomy, conventions, Fasi 0–6, `/` command seam). Authoritative for *what* to build.
- **`SESSION-STATE.md`** — raw progress notes copied from the prior session's memory.
- **`HANDOFF.md`** — this file. Authoritative for *how to resume* and *what not to repeat*.

---

## 0) TL;DR — first 5 minutes on the new machine

```powershell
# 1. Get the work, then SWITCH TO THE BRANCH (Fase 0+1 + these docs live only here)
git clone https://github.com/devfrx/alice.git    # or, in an existing clone: git fetch
cd alice
git checkout agent-rework                          # NOT main
#   If this fails with "pathspec did not match", the branch was not pushed —
#   see the Delivery invariant at the top; the SOURCE machine must push it.

# 2. CONFIRM you actually have the work (the only reliable check)
git log --oneline -7
#   You must see the five rework commits ending at the last CODE commit
#   bcc0b4a  fix(turn): preserve "Invalid JSON" ...
#   with a docs/handoff commit sitting on top. If you don't see bcc0b4a,
#   STOP — you don't have the work; do NOT try to recreate Fase 0/1.

# 3. Build the BACKEND dev env (see §2 — DO NOT use system Python 3.14)
uv venv --python 3.13 .venv
.\.venv\Scripts\Activate.ps1
cd backend; uv pip install -e ".[dev,memory]"; uv pip install sqlite-vec; cd ..

# 4. Fast sanity check (≈1.3 s — this is your inner loop, NOT the full suite)
cd backend
..\.venv\Scripts\python.exe -m pytest `
  tests/test_interaction_channel.py tests/test_tool_loop.py `
  tests/test_confirmation_toggle.py tests/test_direct_executor_tool_loop.py `
  tests/test_reflective_executor.py tests/test_turn_factory.py `
  tests/test_direct_executor_cancel.py tests/test_direct_executor_streaming.py `
  tests/test_direct_executor_disconnect.py -q -p no:cacheprovider
# expect: 57 passed
```

If those 57 pass, the foundation is intact and you can start **Fase 2** (§6).

**Frontend is OPTIONAL here.** Fase 2 (the next phase, §6) is backend‑only. Do
`cd frontend; npm install` **only** when you reach a frontend‑touching phase
(Fase 3+); in this offline environment npm registry access may be slow or fail,
so don't let it block the fully‑independent backend work above.

---

## 1) Where we are

- **Branch:** `agent-rework` (off `main`). Last **code** commit is `bcc0b4a`; the
  handoff‑docs commit sits on top of it (so `git log` HEAD is the docs commit, and
  `bcc0b4a` is the most recent code change). Working tree clean.
- **Commits on this branch (newest first):**
  | SHA | What |
  |---|---|
  | `bcc0b4a` | Fase 1 fix: preserve "Invalid JSON" reply through the channel pump |
  | `45b65d0` | Fase 1 **A**: relocate engine → `services/turn/tool_loop.py` |
  | `6f11917` | Fase 1 **B-migrate**: wire `InteractionChannel` as the single WS reader |
  | `cca45fd` | Fase 1 **B-core**: add `InteractionChannel` (single inbound read‑pump) |
  | `4bd3585` | Fase 0: collapse to single model‑driven agentic path (rip‑out) |
- **Done:** Fase 0 (rip‑out of the Chat/Agente duality, structured pipeline, voice bypass) **and** Fase 1 (foundation A+B). See §4 for detail.
- **Next:** **Fase 2** (foundation C+D — tool middleware pipeline + central `PermissionService`). Then Fase 3 (canonical turn‑event stream), then features Fasi 4–6. See `PLAN.md`.

### ⚠️ Getting the branch (it lives only on `agent-rework`)
`agent-rework` is **~6 commits ahead of `main`** (Fase 0 + Fase 1 + this handoff
commit). The source machine pushes it to `origin` as part of completing the
handoff (see the Delivery invariant at the top). On the new machine, after
`git checkout agent-rework`, **confirm `git log --oneline -7` shows the last code
commit `bcc0b4a`** before doing anything else. If `git checkout agent-rework`
fails or you don't see `bcc0b4a`, you don't have the work — the source machine
must run `git push -u origin agent-rework`. **Do NOT try to recreate Fase 0/1.**

---

## 2) Dev environment — the setup that actually works (mistakes baked in)

The previous session lost time here. Do it this way and you won't.

1. **Python: use 3.13, managed by `uv`. NOT 3.14.**
   The machine had only a global **Python 3.14**, for which required wheels are
   missing/incompatible — install/test failures. (`requires-python` is actually
   `>=3.11`, and `py313` in `pyproject.toml` is only the *ruff lint target*, not a
   hard pin — so 3.11/3.12 are "allowed", but **3.13.12 is the known‑good one**.)
   Fix that works:
   ```powershell
   uv venv --python 3.13 .venv      # downloads CPython 3.13.x into .venv
   ```
   The known‑good interpreter is **CPython 3.13.12**. `uv` version used: 0.10.10.

2. **Backend deps need the `memory` extra + `sqlite-vec`** (tests import them):
   ```powershell
   .\.venv\Scripts\Activate.ps1
   cd backend; uv pip install -e ".[dev,memory]"; uv pip install sqlite-vec
   ```

3. **Frontend: `vitest` is declared but was not installed** — run `npm install`
   in `frontend/` before any `*.spec.ts` work, or vitest is missing.

4. **Invoke the venv python explicitly** in commands:
   `..\.venv\Scripts\python.exe -m pytest ...` (run from `backend/`).

---

## 3) ⛔ The single biggest time‑sink to AVOID: the full test suite "hangs"

**Do NOT run `pytest tests/` (the whole suite) expecting it to finish quickly,
and do NOT treat a hang there as your regression.**

- The **WebSocket integration tests** — `test_websocket.py`, `test_concurrent.py`,
  `test_message_editing.py`, `test_branch_conversation.py`, `test_voice_ws.py`,
  `test_voice_tool_calling.py` — **hang in this offline environment**. They block
  *inside turn assembly* (`assembler.assemble`) on a **real embedding/memory
  call with no backend** (no LM Studio / embedding server; log says
  `Embedding API unreachable and fastembed fallback is disabled`).
- **This was verified to hang IDENTICALLY at HEAD `4bd3585` (pre‑Fase‑1)** via a
  throwaway `git worktree`. ⇒ It is **environmental, not a migration regression.**
- A **minimal `TestClient` repro** confirmed the new single‑pump pattern itself
  is sound. So the channel/pump design is *not* the cause.
- Practical rule:
  - Use the **57‑test targeted subset** in §0 for your inner loop (~1.3 s).
  - For broader confidence, run the **whole suite EXCEPT the hangers** (copy‑paste,
    from `backend/`):
    ```powershell
    ..\.venv\Scripts\python.exe -m pytest tests/ `
      --ignore=tests/test_websocket.py --ignore=tests/test_concurrent.py `
      --ignore=tests/test_message_editing.py --ignore=tests/test_branch_conversation.py `
      --ignore=tests/test_voice_ws.py --ignore=tests/test_voice_tool_calling.py `
      --ignore=tests/test_app.py -q -p no:cacheprovider
    ```
    (`test_app.py` is excluded only because it's slow — ~100 s spinning the full
    FastAPI app + plugins — not because it hangs; include it if you want and can
    wait.)
  - To unblock the WS tests for real you'd need a running embedding/LLM backend
    **or** additional mocks in `tests/conftest.py` — that's **pre‑existing
    test‑infra debt, out of scope for the foundation phases**. Don't rabbit‑hole.

**Other gotchas that cost time (don't repeat):**
- **pytest output buffering:** `pytest -q | tail` shows nothing until the run
  ends. To watch progress, use `python -u -m pytest ... > file.txt 2>&1` and
  read the file, or check live. A 0‑byte output usually means *still running /
  hung*, not "passed".
- **Background shell working dir:** a backgrounded `Bash` may start a fresh shell
  at the repo root — `cd` from a previous call does **not** persist into it. Put
  an explicit `cd backend && ...` inside the background command, or you'll get
  `file or directory not found: tests/`.
- **Pre‑existing lint/type baselines — don't chase them.** `ruff`/`mypy` are
  **not** clean at HEAD. Before "fixing" an error, confirm it's *new*:
  ```powershell
  git show HEAD:backend/path/file.py | ..\.venv\Scripts\python.exe -m ruff check --stdin-filename file.py -
  ```
  Known pre‑existing in `services/turn/tool_loop.py`: `UP035`, `B905`, `E501`
  (line 945), `I001`. Known pre‑existing mypy in `api/routes/chat/ws.py`:
  `_sync_conversation_to_file` arg‑type. **`channel.py` is fully ruff+mypy clean
  — keep it that way.**

---

## 4) What Fase 0 + Fase 1 actually changed (so you trust the new seams)

### Fase 0 — single path (`4bd3585`)
- One engine: `DirectTurnExecutor`. `ReflectiveTurnExecutor` is an **optional**
  wrapper, selected only by `agent.reflection.enabled`.
- **Deleted:** `AgentTurnExecutor`, the whole `backend/services/agent/` package,
  `_critic_bypass`, the Chat/Agente toggle (frontend), `agent.enabled` /
  `structured_mode` / `voice_mode_bypass` config + structured knobs.
- **Added:** `backend/services/turn/_reflection.py` — slim, self‑contained
  reflection (`ReflectionVerdict`, `detect_degeneration`, `ReflectionCritic`).

### Fase 1 — foundation A+B (`cca45fd`, `6f11917`, `45b65d0`, `bcc0b4a`)
The point of Fase 1 was to kill two structural debts: **(a)** 4+ concurrent
`receive_text()` readers on one socket (the "v3‑1 cancel reader" fragility), and
**(b)** the 1380‑line tool‑loop god‑function living in the route layer and taking
a raw `WebSocket`.

- **`backend/services/turn/channel.py` (NEW)** — the inbound counterpart to
  `WSEventSink`:
  - `InteractionChannel` Protocol:
    `async request(kind, payload, *, execution_id, timeout_s, cancel_event) -> dict | None`,
    plus `cancelled` / `connected` properties.
  - `WebSocketInteractionChannel` — **one** read‑pump task (`start()`/`aclose()`)
    that demultiplexes every frame: cancel → set cancel_event + resolve pending;
    matching `execution_id`+response‑type → resolve the request future; stale
    interaction response → drop; malformed JSON → enqueue a `MALFORMED_FRAME_KEY`
    marker; anything else → user/idle queue (`next_user_message()`); disconnect →
    `connected=False` + wake idle loop. `begin_turn()` returns the per‑turn
    `cancel_event`. `_REQUEST_SPECS` maps `kind → (request, response)` frame types
    and **already includes `ask_user`** (Fase 4 ready).
  - `ScriptedInteractionChannel` — test double (twin of `RecordingEventSink`).
  - Contract preserved vs legacy: confirmation → `bool` (None ⇒ not approved);
    client‑tool → **disconnect > cancel > timeout** disambiguation via
    `connected`/`cancelled`.
- **`backend/services/turn/tool_loop.py`** — the engine, **moved here from
  `api/routes/_tool_loop.py`** (which no longer exists). Signature is now
  transport‑agnostic: `run_tool_loop(*, channel, sink, ...)`. Outbound →
  `sink.send`; inbound → `channel.request`. Removed `_ws_cancel_reader`,
  `_send_json`. `_request_confirmation` / `_execute_client_tool` reimplemented on
  the channel.
- **`backend/services/turn/direct_executor.py`** — `execute(..., channel=None)`;
  removed `_spawn_cancel_reader` (the pump sets `cancel_event` during streaming);
  forwards `sink` + `channel` to the loop. Tool‑loop path now gated on
  `channel is not None` (was `sink._ws is not None`).
- **`backend/services/turn/reflective_executor.py`** — forwards `channel`.
- **`backend/api/routes/chat/ws.py`** — builds `WebSocketInteractionChannel`,
  `channel.start()`, idle loop reads via `channel.next_user_message()`,
  `cancel_event = channel.begin_turn()`, passes `channel` to `execute()`,
  `await channel.aclose()` in `finally`. Maps `MALFORMED_FRAME_KEY` → the legacy
  `{"type":"error","content":"Invalid JSON"}` reply.
- **Tests:** `MockWebSocket` in `test_tool_loop.py` is now a combined
  sink+channel double; confirmation / direct‑executor / reflective tests updated;
  `test_interaction_channel.py` (15 tests) covers routing / cancel / timeout /
  stale / disconnect / malformed.

**Deferred cosmetic cleanups (safe to do, non‑functional):**
- `_receive_ws_text` in `backend/api/routes/chat/_shared.py` is now orphaned
  (the idle loop uses the pump). Removable.
- `sink._ws` escape hatch is no longer used by the engine. Removable later.

---

## 5) Capability taxonomy (so new code lands in the right category)

From `PLAN.md` — classify every capability into **one** of:
Engine/core · **Plugin nativo** (`<plugin>_<tool>`) · **Server MCP** (the
`mcp_client` plugin) · **Meta‑tool** (`agent` plugin: `update_plan`,
`spawn_subagent`) · **Tool a interazione utente** (`ask_user`, `user_interaction`
flag) · **Tool client‑executed** (`client_execution`) · **Modulo frontend** (not a
tool) · **Comando `/`** (future seam).
Hard rules: the **Terminal is a native plugin** (its module is just UI);
**Plan & Scope are core services**; **the model can NOT set the scope** (user sets
it only while idle — deliberately kept out of the tool registry for
anti‑privilege‑escalation). Confirmation / client‑exec / `ask_user` are the
**same mechanism** (InteractionChannel), not separate branches.

---

## 6) NEXT: Fase 2 — foundation C+D (do this next)

Goal: every tool‑call flows through a **composable middleware chain**, and
permission/scope policy is **centralized** (not per‑plugin, not under
`pc_automation`). Behaviour‑preserving. (Full spec in `PLAN.md` → "Fase 2".)

**C — middleware pipeline** — new `backend/services/turn/pipeline.py`:
`ToolMiddleware` Protocol (`async handle(call, nxt) -> ToolResult`), chained per
tool‑call in this order:
1. `DedupMiddleware` (move the `seen`/hash logic out of `tool_loop.py`)
2. `PermissionMiddleware` (forbidden/risk + scope confinement → `PermissionService`)
3. `ConfirmationMiddleware` (uses `InteractionChannel`)
4. `InteractionMiddleware` (`client_execution`/`user_interaction` → `channel.request`, never `execute_tool`)
5. `ExecuteMiddleware` (`tool_registry.execute_tool`)

The engine then iterates tool‑calls **through the pipeline** — no inline `if`s.

**D — `PermissionService`** — new `backend/services/permission_service.py`
(DI in `AppContext`): risk policy, per‑conversation grants, and **by‑construction
scope confinement**. Add **capability tags** to `ToolDefinition`
(`backend/core/plugin_models.py`): `capabilities: tuple[str,...] = ()` (e.g.
`"fs_read"`, `"fs_write"`, `"process_exec"`) and `path_args: tuple[str,...] = ()`
so any `fs_*` tool is confined automatically (deny‑by‑default if it touches a path
outside scope). **Move the confirmation config** out of `pc_automation` into a
neutral `SecurityConfig`/`permissions` block in `core/config.py`
(`confirmations_enabled`, `confirmation_timeout_s`) with **legacy‑key migration**
(reuse the `migrate_legacy_config_keys` pattern) so `pc_automation` keeps working.

**Tests:** `test_pipeline.py` (order/short‑circuit), `test_permission_service.py`
(risk/grant/scope deny‑by‑default), update `test_confirmation_toggle.py` to the new
config home.

---

## 7) Methodology — how to execute (the previous session's agreed rules)

- **Foundation phases (1–3) = MANUAL, SEQUENTIAL.** This is tightly coupled core
  code. The `superpowers:subagent-driven-development` skill **forbids parallel
  implementers on coupled work** — honor that. The "most efficient number of
  simultaneous implementers" for coupled core is effectively **1**.
- **Subagents shine on the feature phases (4–6)** — `ask_user`, the Plan module,
  scope+Terminal — where work is genuinely independent. There, fan out.
- **Subagents must be Claude Opus 4.8** (user's explicit requirement).
- **Two‑stage review after each task:** spec‑compliance review, then code‑quality
  review (per the subagent‑driven‑development skill).
- **Behaviour‑preserving** for Fasi 1–3: lean on the existing tests adapted to the
  new seams; no observable behaviour change until the features land.
- **Conventions (enforced):** Python — `from __future__ import annotations`, full
  type hints, async I/O, `pathlib`, `loguru`, Google docstrings, 100 cols,
  `ruff` + `mypy --strict`; new `ToolDefinition` flags default `False`. TS/Vue —
  `<script setup lang="ts">`, Composition API, no `any`, scoped CSS, Pinia
  setup‑stores, snake_case‑mirroring types. **Contract consistency** across
  WS event / REST shape / TS type / Pinia store / DB model is critical.

---

## 8) Verification checklist (copy‑paste)

```powershell
cd backend
# Fast foundation regression (use this constantly):
..\.venv\Scripts\python.exe -m pytest `
  tests/test_interaction_channel.py tests/test_tool_loop.py `
  tests/test_confirmation_toggle.py tests/test_direct_executor_tool_loop.py `
  tests/test_reflective_executor.py tests/test_turn_factory.py `
  tests/test_direct_executor_cancel.py tests/test_direct_executor_streaming.py `
  tests/test_direct_executor_disconnect.py -q -p no:cacheprovider     # 57 passed

# Lint/type on files you touch (compare new vs HEAD to ignore pre-existing):
..\.venv\Scripts\python.exe -m ruff check <files> --output-format=concise
..\.venv\Scripts\python.exe -m mypy <files>

# No-circular-import smoke (catches packaging mistakes fast):
cd ..
.\.venv\Scripts\python.exe -c "import backend.core.app; import backend.services.turn.tool_loop; print('ok')"

# Frontend (from frontend/), when you touch it:
npm run typecheck   # mandatory before considering FE work done
```

Do **not** gate your progress on the full `pytest tests/` run — see §3.

---

## 9) Open / deferred items

- **Fase 0b (deferred):** voice tool‑set trimming. Needs a renderer voice‑origin
  signal; the config seam `agent.voice.max_tools` already exists.
- **Cosmetic cleanups (§4):** remove orphaned `_receive_ws_text`; retire the
  `sink._ws` escape hatch.
- **WS integration tests** can't run offline (§3) — needs backend or conftest
  mocks; pre‑existing infra debt, not blocking the foundation.

---

## 10) Definition of done for the whole rework

The foundation (1–3) changes **nothing user‑visible** but makes Fasi 4–6 small and
clean and erases the 4 structural debts. Then: **Fase 4** `ask_user` (inline,
client‑answered) · **Fase 5** Plan as a first‑class persisted workspace module ·
**Fase 6** workspace scope (mutable only while idle) + scoped Terminal plugin/module
(confined by‑construction via capability tags, confirmed, audited; sandbox fallback
when no scope). The `/` command seam is only a contract (`CommandDefinition` +
`BasePlugin.get_commands()`) added in Fase 4 — full palette is future work.
See `PLAN.md` for the per‑file spec of every phase.
