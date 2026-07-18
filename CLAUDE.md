# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**AL\CE** (a.k.a. *Omnia*) — a local-first personal AI assistant. Everything (LLM, STT, TTS, vector store, 3D generation) runs on the user's machine by default; **OpenRouter** is supported as an optional cloud LLM provider of equal rank (`llm.provider: "openrouter"`, API key required, per-token billing). Memory/embeddings stay strictly local regardless of provider. **Windows is the primary target.**

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

### Agent evals (Fase 0 Agent v2)
```powershell
python -m backend.evals list             # elenca gli scenari
python -m backend.evals run              # run ufficiale (OpenRouter, modello pinnato z-ai/glm-5.2, costa denaro)
python -m backend.evals run --filter fs- --no-judge   # subset economico
python -m backend.evals run --baseline docs/superpowers/evals/<ultimo>/report.json
```
I run veri richiedono la API key OpenRouter (keyring o env). Il subset mock
gira in CI dentro pytest (`backend/tests/evals/`).

### Service ports
Backend `8000`, frontend dev `5173`, LM Studio `1234`, Ollama `11434`, TRELLIS `8090`.

## Backend architecture (the big picture)

The backend is **plugin-based and dependency-injected**. Three concepts tie it together:

1. **`AppContext` (`core/context.py`)** — the DI container holding every service (`llm_service`, `qdrant_service`, `memory_service`, `tool_registry`, `knowledge_service`, `event_bus`, …). It is constructed and wired entirely in the lifespan of `core/app.py`. Plugins receive it in `initialize(ctx)` and reach everything through `self.ctx`. Service fields are typed as `Protocol`s (`core/protocols.py`) — depend on those, not concrete classes. Since Fase 5 the canonical fields are 5 cohesive groups (`core/service_groups.py`: `inference`/`knowledge`/`workspace`/`conversation`/`platform`); the flat names (`ctx.llm_service`, …) remain as delegating properties. The lifespan is a sequence of declarative stages in `core/bootstrap/` (explicit order, shutdown in `bootstrap/shutdown.py`).

2. **Plugin system (`core/plugin_base.py`, `core/plugin_manager.py`)** — every capability (web search, calendar, memory, email, MCP client, CAD/chart/3D generators, the agent meta-tools, terminal, pc_automation, file_search, clipboard, notifications, media_control, network_probe, continuum, whiteboard, etc.) is a `BasePlugin` subclass under `backend/plugins/<name>/plugin.py`. Discovery is **static**: each plugin module assigns `PLUGIN_REGISTRY["name"] = MyPlugin` at import time (required for PyInstaller bundling — there is no dynamic filesystem scan in production). The manager resolves dependencies via topological sort, initializes in order, creates plugin-owned DB tables (`get_db_models`), then calls `on_app_startup`. Which plugins load is driven by `config/default.yaml` `plugins.enabled`, then overridden by persisted per-user toggles in the DB.

3. **Tools & the AgentEngine** — plugins expose `ToolDefinition`s (JSON-serializable, fed to the LLM as function-calling tools). `core/tool_registry.py` aggregates them: it is a facade over the `core/tools/` components (catalog / availability / offer-policy / execution / RAG); the run-time permission gate stays in `services/permission_service.py`. A user message becomes a **turn**, executed by the greenfield **`AgentEngine`** (`backend/services/agent/`, built Agent v2 Fase 1 — replaced the legacy `DirectTurnExecutor`/`ReflectiveTurnExecutor`/`run_tool_loop` stack, fully demolished). One unified loop, no special-cased first step: `engine.py` streams the LLM, gates and executes tool-call batches in parallel, steps again, until a `StopReason` (`stop.py`) fires. The engine talks to the rest of the platform only through **7 injected `Protocol` ports** (`ports.py`): `LLMPort`, `PermissionPort` (authority stays `PermissionService`/scope/mode; the gate *flow* — dedup, decide, confirm, execute — is the engine's), `InteractionPort` (confirm/ask_user/client-tool round-trips, timeout/cancel/disconnect disambiguated), `EventPort` (typed canonical events out), `PersistencePort` (explicit unit-of-work over SQLModel), `ContextPort` (compaction policy between steps), `ExecutionPort` (tool execution via the registry). Supporting modules: `retry.py` (empty-response nudge, transient-vs-fail-fast retry), `dedup.py` (cross-step tool-call dedup), `events.py` (internal typed `AgentEvent` superset of the wire vocabulary). `adapters/` is where the engine meets the platform: `llm.py`, `permission.py`, `context.py`, `execution.py` wrap the domain services; `db.py` is the SQLModel `PersistencePort`; `ws.py` is the from-scratch WS transport (single socket reader, request/response correlation, disconnect handling; interaction round-trips ride `interaction.requested`/`interaction.response` frames correlated by `interaction_id`). The **definitive** event→frame translator (`to_v2_frames`) lives with the contract in `api/ws_schema/wire.py` — each frame is built through its `api/ws_schema` Pydantic model so a frame that doesn't validate cannot be constructed; the wire is v2-only vocabulary, validated by-construction (the throwaway `parity.py` was deleted at the end of Mossa 2). `runner.py` is the **composition root** (`run_agent_turn`): the only place the engine is wired to real `AppContext` services, in two configurations — WebSocket transport (live turns) or headless/sink (eval/trigger, `AutoDeclineInteractionPort` auto-declines interactive requests); the api call sites inject `translator=to_v2_frames`, keeping `services ↛ api` intact. The `_sink.py` sinks (`WSEventSink` Protocol, `TransportEventSink`, `NullEventSink`) are **api-owned** (`api/routes/chat/_sink.py`), not part of the engine package — `runner.py` depends on them only via a structural `Protocol`, never an import, keeping the engine package decoupled from api-owned code. Final-message persistence lives in the engine: `turn.finished` carries the real message id / token usage / cost, and `_persist` emits only typed `context.*` frames through the engine transport (`TransportEventSink`). Agentic behavior (todo-list, subagent delegation, clarification) comes from the `agent` plugin's meta-tools (`update_plan`, `spawn_subagent`, `ask_user`) injected into the same loop; there is no separate pre-planning pass and no legacy classifier/planner/critic pipeline. **Reflection was removed** (`agent.reflection.*` deleted along with `ReflectiveTurnExecutor`) — anti-degeneration guards are a Fase 3 concern, to be built inside the engine, not bolted on as a self-check pass. The `agent.engine` config flag was **removed** at the end of Mossa 2 (v2 has been the only engine since v1 was demolished; the key is stripped from any persisted config layer via `_REMOVED_LEGACY_KEYS`). Config lives under `agent.*`: `planning`, `delegation`, `clarification`, `subagent.{max_steps,max_tools,timeout_seconds,max_output_tokens}`, `voice.max_tools` (tool cap for voice turns).
   - **Command Bridge (spec §7)** — the kernel (not a plugin) owns the `app_command` tool: the agent drives the app UI itself. The frontend Command Registry (`frontend/src/renderer/src/commands/`) sends its agent-exposable manifest (`exposeToAgent` commands only) over the events WS; `services/command_bridge.py` ingests it (structural anti-escalation: guardrail-domain command names are rejected at ingestion, never callable) and runs the RPC — broadcast `command.request` with `correlation_id`, await `command.result` with timeout, every failure a clean `ToolResult` ("UI not available"). Gating is per-call in `PermissionService.decide` on the command's manifest capability tag (`navigation|read|mutate|destructive`; plan tier allows only navigation/read). Kernel tools register via `ToolRegistry.register_kernel_tool` (owner `"kernel"` in the catalog). Config under `commands.*`.
   - **Fondamenta Jarvis (spec §8)** — tre service kernel posati in fase 8 (interfacce, non implementazioni ricche): `services/trigger_service.py` (`TriggerService`: turni autonomi da schedule/eventi bus/manual, filtro anti-eco sugli eventi con `origin="agent"`; il turno autonomo è un turno NORMALE via `api/routes/chat/headless.py::run_headless_turn` — stesso assembly/executor/permission/scope, `NullEventSink` + `HeadlessInteractionChannel` che auto-declina le richieste interattive), `services/attention_service.py` (`AttentionService`: punto unico e disattivabile dell'iniziativa agente→utente, `attention.raised` → toast), `services/background_tasks.py` (`BackgroundTaskService`: task in background osservabili, frame `background_task.updated` → store FE `backgroundTasks`). Wiring in `bootstrap/jarvis.py` (ultimo stage). Il subagent passa dal gate centrale (`PermissionService.explain_denial`, conferma = negazione pulita); i turni voce (frame `source: "voice"`) attivano il trim `agent.voice.max_tools`. Config `triggers.*`, `attention.*`.

4. **Scope & permission modes** — every conversation runs under a **workspace scope** (`services/scope_service.py`, store `scope.ts`): filesystem/exec tools are confined to an explicit folder or an ephemeral sandbox (confinement, not denial). On top, a **four-tier permission mode** per conversation (`services/permission_mode_service.py`, `permission_mode_policy.py`, `permission_rules.py`; store `permissionMode.ts`): `strict` (prompt for everything), `auto_edits` (auto-approve safe in-scope writes), `plan` (read-only), `autopilot` (full autonomy with circuit-breaker guards). Config under `permissions.*`. Tool handlers must respect both gates.

### Request flow
- **WebSocket chat** is the primary interface. The handler is `api/routes/chat/ws.py` (`ws_chat`). The `chat/` package was split out of a monolithic `chat.py`: `ws.py` (WS protocol/cancel/recovery), `_assembly.py` (builds `TurnInput`: conversation resolve, versioning, history, tool selection, memory/MCP/whiteboard context), `_persist.py` (post-turn maintenance: the AgentEngine itself persists the final message and emits `turn.finished`; `_persist` refreshes conversation metadata, emits the typed `context.*` frames, and runs the post-stream compression pass through the engine transport), plus REST CRUD in `conversations.py` and `io.py`. `chat/__init__.py` re-exports `router`.
- All routes are registered in `api/routes/__init__.py` under the `/api` prefix. Middleware (exception handler, origin guard, rate limit, CORS) is set up in `core/app.py:create_app`.
- An **event bus** (`core/event_bus.py`, `AliceEvent` enum) decouples services; the lifespan bridges many events (MCP, email, notes, service status, model-download progress) onto the events WebSocket via `WSConnectionManager.broadcast`.
- **Layered config**: `LayeredConfigService` merges defaults / system / user / runtime layers and rebuilds `ctx.config` on every successful mutation (publishes `config.changed`). Config models are pydantic-settings in `core/config.py`; env overrides use the `ALICE_*` prefix.

### Data & external services
- SQLite via SQLModel/aiosqlite (`backend/db/`, files under `data/*.db`). SQLite is the single source of truth for conversations; JSON export/backup is explicit only (`POST /api/chat/conversations/backup`, agent tool `backup_conversations`, sidebar UI).
- **Qdrant** is the vector store for episodic memory/facts (`services/qdrant_service.py`, `services/memory_service.py`). Note knowledge is delegated to Continuum when enabled. Both sit behind **`KnowledgeService`** (`services/knowledge/service.py`) — the single entry point to the knowledge domain, wrapping `QdrantBackend`/`ContinuumBackend` composed by `CompositeKnowledgeBackend` and built ONLY by `build_knowledge_service` (lifespan + repair). Consume `ctx.knowledge_service`, never the backends or `memory_service` directly.
- LLM access goes through `services/llm_service.py` over LM Studio (default) or Ollama, OpenAI-compatible API. `LLMService` is a facade over the `services/llm/` modules (streaming client, prompting, model resolution).
- The `terminal` plugin provides a **real interactive Windows ConPTY shell** (`pywinpty`; `backend/services/terminal/`, REST in `api/routes/terminal.py`, store `terminalSessions.ts`), gated by scope + permission mode and `config.terminal.*`.

## Frontend architecture

- `src/main/` Electron main (window/IPC/CSP), `src/preload/` context bridge, `src/renderer/src/` the Vue 3 app.
- State is **Pinia** stores (`renderer/src/stores/`: `chat`, `voice`, `settings`, `plugins`, `artifacts`, `memory`, `calendar`, `email`, `mcp`, `services`, `ui`, plus `agentRun`, `tasks`, `planDocument`, `scope`, `permissionMode`, `terminalSessions`, `workspace`, `mcpMemory`, `backgroundTasks`). Charts and whiteboards are *kinds* of the unified `artifacts` store (JSON content via `/api/artifacts/{id}/content`; board view-model in `composables/whiteboard/useWhiteboardBoards.ts`). Backend comms are centralized in `renderer/src/services/api.ts` (REST) and `ws.ts` (WebSocket).
- Logic lives in composables (`renderer/src/composables/`); views in `renderer/src/views/`.
- **Horizon** is the primary assistant surface (`views/HorizonView.vue`, components under `components/horizon/`, composables under `composables/horizon/`, styles in `assets/styles/horizon.css`) — an editorial scene centered on the horizon line with plan, composer cockpit, stage, shelf, and response rendering. The older orb-era components are legacy; prefer Horizon when touching the assistant UI.

## Conventions (enforced — see `.github/copilot-instructions.md`)

- **Python**: type hints on all params + returns; `async def` for all I/O; `loguru.logger` (not stdlib `logging`); `pathlib.Path` (not `os.path`); `httpx` (not `requests`); Google-style docstrings; max line 100.
- **TypeScript/Vue**: `<script setup lang="ts">` only, Composition API (`ref`/`computed`/`watch`), no `any`, scoped CSS.
- **Contract consistency is critical**: API endpoints, WS message types, frontend TS types, Pinia stores, and DB models must all stay in agreement. A backend change to a WS event or REST shape requires the matching frontend update. Verify all callers before changing a signature/endpoint/schema.
- Prefer small, single-responsibility modules. Verify a function/endpoint exists before calling it and that you're not duplicating one before creating it.
- **Layering is enforced by import-linter in CI** (`lint-imports --config backend/pyproject.toml` from the repo root): plugins are independent of each other, api ↛ plugins, services ↛ api, services ↛ plugins, `continuum` imports banned, core ↛ services/api (sanctioned exceptions: the composition root). Config flags are censused in `docs/flag-registry.md`.
- **Contracts are generated**: new/changed REST endpoints must declare a Pydantic `response_model` (ratchet test in `backend/tests/contracts/`); every WebSocket frame on both channels is a Pydantic model in `backend/api/ws_schema/` (flat envelope: `type` discriminant + `origin` + `correlation_id?`; frozen vocabulary tests in `backend/tests/contracts/`). Any contract change requires regenerating (`.\scripts\gen-contracts.ps1`). Files in `frontend/src/renderer/src/types/generated/` are build artifacts — never edit them by hand (except `index.ts`) and never hand-merge them on conflicts: regenerate instead. The events-WS frontend dispatcher (`useEventsWebSocket.ts`) is an exhaustive `type → handler` map: adding a frame without handling it is a compile error. CI runs these gates in `.github/workflows/contracts.yml` (codegen pinned via `npm ci`).

## Notes

- The root is littered with scratch files from prior sessions (`_*.log`, `_*.txt`, `*_plan.md`, `lmstudio_*.md`, `MODELSSTRUCTURE.TT`). These are not authoritative; `ARCHITECTURE_PLAN.md` and `agent_loop_plan.md` describe in-progress directions, not necessarily current state — verify against code.
- `models/`, `data/`, and built artifacts are gitignored.
