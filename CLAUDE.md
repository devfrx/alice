# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**AL\CE** (a.k.a. *Omnia*) — a 100% local personal AI assistant. No external paid APIs; everything (LLM, STT, TTS, vector store, 3D generation) runs on the user's machine. **Windows is the primary target.**

The repo is effectively a small multi-project workspace:

- `backend/` — Python 3.11+ / FastAPI async backend (the core). Installable package `alice-backend`.
- `frontend/` — Electron + Vue 3 (Composition API) + TypeScript desktop app (`alice-frontend`), built with electron-vite.
- `continuum/` — a **separate** project (TypeScript / Fastify / Drizzle) temporarily vendored here. It is the future standalone knowledge base; Alice consumes it over HTTP/MCP only. See `ARCHITECTURE_PLAN.md`. Do not couple Alice code to Continuum internals.
- `trellis2_server/`, `trellis2multiview_server/` — optional TRELLIS 3D-generation microservices (separate Python venvs, GPU-only). Driven via `scripts/start-trellis*.ps1`.

When working on a feature, you are almost always in `backend/` and/or `frontend/`.

## Commands

All commands assume PowerShell on Windows. The Python virtualenv is at the repo root: `.\.venv\`.

### Backend (run from repo root unless noted)
```powershell
.\.venv\Scripts\Activate.ps1
cd backend; uv pip install -e ".[dev]"        # base install
# Tests also need the memory extra (fastembed) and sqlite-vec:
cd backend; uv pip install -e ".[dev,memory]"; uv pip install sqlite-vec

# Run the server (either form; from repo root):
python -m backend --reload --reload-dir backend
uvicorn backend.core.app:create_app --factory --reload --reload-dir backend --host 0.0.0.0 --port 8000

# Tests (run from backend/):
cd backend
pytest tests/ -v
pytest tests/test_app.py -v                    # single file
pytest tests/test_app.py::test_health -v       # single test

# Lint / type-check:
ruff check .            # config in pyproject.toml (line-length 100, py313 target)
ruff format .
mypy .                  # strict mode
```

### Frontend (run from `frontend/`)
```powershell
npm install
npm run dev              # electron-vite dev (renderer on localhost:5173)
npm run typecheck        # node + web (vue-tsc); ALWAYS run before considering FE work done
npm run lint
npm run build:win        # NSIS installer
```

### One-shot setup / dev
```powershell
.\scripts\setup.ps1            # installs venv + backend deps + TTS models + frontend (flags: -CpuOnly -SkipModels -SkipFrontend -SkipOllama)
.\scripts\start-dev.ps1        # launches backend + frontend together
```

### Contracts (FE<->BE codegen)
```powershell
.\scripts\gen-contracts.ps1      # regenerate OpenAPI schema + generated TS types
.\scripts\check-contracts.ps1    # fail if committed contract artifacts are stale
```

### Service ports
Backend `8000`, frontend dev `5173`, LM Studio `1234`, Ollama `11434`, TRELLIS `8090`.

## Backend architecture (the big picture)

The backend is **plugin-based and dependency-injected**. Three concepts tie it together:

1. **`AppContext` (`core/context.py`)** — the DI container. A single dataclass holding every service (`llm_service`, `qdrant_service`, `memory_service`, `tool_registry`, `knowledge_backend`, `event_bus`, …). It is constructed and wired entirely in the lifespan of `core/app.py`. Plugins receive it in `initialize(ctx)` and reach everything through `self.ctx`. Service fields are typed as `Protocol`s (`core/protocols.py`) — depend on those, not concrete classes.

2. **Plugin system (`core/plugin_base.py`, `core/plugin_manager.py`)** — every capability (web search, calendar, memory, email, MCP client, CAD/chart/3D generators, the agent meta-tools, terminal, pc_automation, file_search, clipboard, notifications, media_control, network_probe, continuum, whiteboard, etc.) is a `BasePlugin` subclass under `backend/plugins/<name>/plugin.py`. Discovery is **static**: each plugin module assigns `PLUGIN_REGISTRY["name"] = MyPlugin` at import time (required for PyInstaller bundling — there is no dynamic filesystem scan in production). The manager resolves dependencies via topological sort, initializes in order, creates plugin-owned DB tables (`get_db_models`), then calls `on_app_startup`. Which plugins load is driven by `config/default.yaml` `plugins.enabled`, then overridden by persisted per-user toggles in the DB.

3. **Tools & the turn executor** — plugins expose `ToolDefinition`s (JSON-serializable, fed to the LLM as function-calling tools). `core/tool_registry.py` aggregates them. A user message becomes a **turn**, executed through `services/turn/`. There is **one execution path**:
   - `DirectTurnExecutor` — streams the LLM and drives the tool-call loop (`services/turn/tool_loop.py` `run_tool_loop`: step budget, per-iteration context compaction, tool dedup, confirmation). Agentic behavior comes from the `agent` plugin's meta-tools injected into the same loop — `update_plan` (mutable todo-list), `spawn_subagent` (isolated-context delegation), `ask_user` (clarification). There is no separate pre-planning pass and no legacy classifier/planner/critic pipeline (removed).
   - `ReflectiveTurnExecutor` — wraps it with a single, non-blocking final-answer self-check. Selected by `create_turn_executor()` (`turn/factory.py`) only when `agent.reflection.enabled` (off by default).
   - Config lives under `agent.*`: `planning`, `delegation`, `clarification`, `reflection.{enabled,tool_turns_only,fail_open,degeneration_detector_enabled,...}`, `subagent.{max_steps,max_tools,timeout_seconds,max_output_tokens}`, `voice.max_tools` (tool cap for voice turns).

4. **Scope & permission modes** — every conversation runs under a **workspace scope** (`services/scope_service.py`, store `scope.ts`): filesystem/exec tools are confined to an explicit folder or an ephemeral sandbox (confinement, not denial). On top, a **four-tier permission mode** per conversation (`services/permission_mode_service.py`, `permission_mode_policy.py`, `permission_rules.py`; store `permissionMode.ts`): `strict` (prompt for everything), `auto_edits` (auto-approve safe in-scope writes), `plan` (read-only), `autopilot` (full autonomy with circuit-breaker guards). Config under `permissions.*`. Tool handlers must respect both gates.

### Request flow
- **WebSocket chat** is the primary interface. The handler is `api/routes/chat/ws.py` (`ws_chat`). The `chat/` package was split out of a monolithic `chat.py`: `ws.py` (WS protocol/cancel/recovery), `_assembly.py` (builds `TurnInput`: conversation resolve, versioning, history, tool selection, memory/MCP/whiteboard context), `_persist.py` (final-turn persistence), plus REST CRUD in `conversations.py` and `io.py`. `chat/__init__.py` re-exports `router`.
- All routes are registered in `api/routes/__init__.py` under the `/api` prefix. Middleware (exception handler, origin guard, rate limit, CORS) is set up in `core/app.py:create_app`.
- An **event bus** (`core/event_bus.py`, `AliceEvent` enum) decouples services; the lifespan bridges many events (MCP, email, notes, service status, model-download progress) onto the events WebSocket via `WSConnectionManager.broadcast`.
- **Layered config**: `LayeredConfigService` merges defaults / system / user / runtime layers and rebuilds `ctx.config` on every successful mutation (publishes `config.changed`). Config models are pydantic-settings in `core/config.py`; env overrides use the `ALICE_*` prefix.

### Data & external services
- SQLite via SQLModel/aiosqlite (`backend/db/`, files under `data/*.db`). Conversations are also mirrored to JSON in `data/conversations/` and rebuilt into the DB on startup.
- **Qdrant** is the vector store for episodic memory/facts (`services/qdrant_service.py`, `services/memory_service.py`). Note knowledge is delegated to Continuum when enabled. Both sit behind the `KnowledgeBackend` abstraction (`services/knowledge/`) — `QdrantBackend` and `ContinuumBackend` composed by `CompositeKnowledgeBackend`. Consume the backend, not the underlying services.
- LLM access goes through `services/llm_service.py` over LM Studio (default) or Ollama, OpenAI-compatible API.
- The `terminal` plugin provides a **real interactive Windows ConPTY shell** (`pywinpty`; `backend/services/terminal/`, REST in `api/routes/terminal.py`, store `terminalSessions.ts`), gated by scope + permission mode and `config.terminal.*`.

## Frontend architecture

- `src/main/` Electron main (window/IPC/CSP), `src/preload/` context bridge, `src/renderer/src/` the Vue 3 app.
- State is **Pinia** stores (`renderer/src/stores/`: `chat`, `voice`, `settings`, `plugins`, `artifacts`, `memory`, `calendar`, `email`, `whiteboard`, `mcp`, `services`, `ui`, plus `agentRun`, `tasks`, `planDocument`, `scope`, `permissionMode`, `terminalSessions`, `workspace`, `charts`, `mcpMemory`). Backend comms are centralized in `renderer/src/services/api.ts` (REST) and `ws.ts` (WebSocket).
- Logic lives in composables (`renderer/src/composables/`); views in `renderer/src/views/`.
- **Horizon** is the primary assistant surface (`views/HorizonView.vue`, components under `components/horizon/`, composables under `composables/horizon/`, styles in `assets/styles/horizon.css`) — an editorial scene centered on the horizon line with plan, composer cockpit, stage, shelf, and response rendering. The older orb-era components are legacy; prefer Horizon when touching the assistant UI.

## Conventions (enforced — see `.github/copilot-instructions.md`)

- **Python**: type hints on all params + returns; `async def` for all I/O; `loguru.logger` (not stdlib `logging`); `pathlib.Path` (not `os.path`); `httpx` (not `requests`); Google-style docstrings; max line 100.
- **TypeScript/Vue**: `<script setup lang="ts">` only, Composition API (`ref`/`computed`/`watch`), no `any`, scoped CSS.
- **Contract consistency is critical**: API endpoints, WS message types, frontend TS types, Pinia stores, and DB models must all stay in agreement. A backend change to a WS event or REST shape requires the matching frontend update. Verify all callers before changing a signature/endpoint/schema.
- Prefer small, single-responsibility modules. Verify a function/endpoint exists before calling it and that you're not duplicating one before creating it.
- **Contracts are generated**: new/changed REST endpoints must declare a Pydantic `response_model` (ratchet test in `backend/tests/contracts/`) and require regenerating contracts (`.\scripts\gen-contracts.ps1`). Files in `frontend/src/renderer/src/types/generated/` are build artifacts — never edit them by hand (except `index.ts`) and never hand-merge them on conflicts: regenerate instead.

## Notes

- The root is littered with scratch files from prior sessions (`_*.log`, `_*.txt`, `*_plan.md`, `lmstudio_*.md`, `MODELSSTRUCTURE.TT`). These are not authoritative; `ARCHITECTURE_PLAN.md` and `agent_loop_plan.md` describe in-progress directions, not necessarily current state — verify against code.
- `models/`, `data/`, and built artifacts are gitignored.
