# Fase 7 — Command Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L'agente pilota il programma: tool kernel `app_command(name, args)`, manifest dei comandi FE come terzo contratto generato, RPC backend→frontend sull'events-WS con `correlation_id` + timeout, gating permission-mode sui capability tag, invariante anti-escalation strutturale (spec §7).

**Architecture:** Il frontend invia sul canale events il manifest dei comandi `exposeToAgent` (frame `command.manifest`, validato da ws_schema → codegen). Il backend ha un `CommandBridgeService` (services) che tiene manifest + pending-future per `correlation_id`: il tool kernel `app_command` (registrato nel `ToolCatalog` con owner fittizio `kernel`, dispatch dedicato nell'executor) inoltra `command.request` via broadcast, attende `command.result` con timeout e ritorna un `ToolResult` pulito ("UI non disponibile" è un risultato, mai un'eccezione). Il gate run-time è in `PermissionService.decide`: il tag `ui_command` risolve la capability EFFETTIVA per-chiamata (navigation|read|mutate|destructive) dal manifest via provider iniettato.

**Tech Stack:** FastAPI + Pydantic (ws_schema), pipeline contratti esistente (`WS_CONTRACT_ADAPTERS` → openapi.json → openapi-typescript), Vue 3 + Pinia (Command Registry fase 6), vitest, pytest.

**Branch:** `arch/fase7-command-bridge` (figlio di `main`, già creato).

---

## Contesto e vincoli per l'implementatore (leggere PRIMA di ogni task)

- **Spec normativa**: `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` §7 (righe 143-176). Invariante non negoziabile: i comandi guardrail (permission/scope/allowlist/config guardrail) sono STRUTTURALMENTE esclusi dal manifest agent-callable, su ENTRAMBI i lati.
- **Convenzioni Python**: type hints ovunque, `async def` per I/O, `loguru.logger`, line length 100, Google docstrings (inglese). **Convenzioni TS**: `<script setup lang="ts">`, no `any`, tipi generati mai editati a mano (eccetto `types/generated/index.ts`).
- **Comandi** (PowerShell 5.1, NIENTE `&&`):
  - pytest: da `backend/` → `..\.venv\Scripts\python.exe -m pytest tests/<file> -v`
  - lint-imports: dalla REPO ROOT → `.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml`
  - ruff (scoped sui file toccati): da `backend/` → `..\.venv\Scripts\ruff.exe check <files>`
  - FE: da `frontend/` → `npm run typecheck`, `npm run lint`, `npm test` (NO `npm install`/`npm ci`)
  - regen contratti: dalla REPO ROOT → `.\scripts\gen-contracts.ps1` (SOLO nel Task 7)
- **Gotchas ereditati** (handoff 2026-07-11): suite backend completa impraticabile (test mirati + `tests/contracts/`); `ToolResult.error()` riempie `error_message`, NON `content`; `test_plugins_enabled_list` è rosso ereditato (21 vs 20, non è una regressione); verificare `git ls-files --eol` PRIMA e DOPO ogni commit (flip EOL = incidente ricorrente); mai cmdlet PowerShell su file non-ASCII; `check-contracts.ps1` solo DOPO il commit (untracked = dirty).
- **Layering (import-linter)**: services ↛ api (il bridge NON importa `ws_schema`: frame come dict raw, validati dal validator iniettato nel manager e da `validate_events_client` nella route); api → services OK; core ↛ services.
- Commit convenzionali con trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. MAI push.

## Decisioni di design (registrate qui, non rilitigare durante l'implementazione)

1. **Tool kernel senza plugin (opzione "kernel tools" nel catalogo)**: la spec impone "di proprietà del kernel, non di un plugin qualsiasi". Non esiste precedente → si estendono `ToolCatalog` (mappa kernel tools + handler, owner fittizio `KERNEL_TOOL_OWNER = "kernel"`), `AvailabilityProbe` (owner `kernel` sempre CONNECTED) e `ToolExecutor` (dispatch all'handler kernel). I meta-tool dell'agent restano plugin: non si migra nulla.
2. **Gating dinamico via `PermissionService.decide`**: `app_command` porta il tag statico `ui_command`; `decide()` risolve la capability effettiva dal nome comando negli `args` tramite `command_capability_provider` iniettato (bound method del bridge). Matrice §7: navigation/read → ALLOW ovunque (anche `plan`); mutate/destructive → DENY in `plan`, CONFIRM in `strict`; `auto_edits` → ALLOW mutate, CONFIRM destructive; `autopilot` → ALLOW. Comando ignoto/manifest assente → trattato come `destructive` (fail-conservative). Regole allow/ask/deny e grants restano sovraordinati come per gli altri tool.
3. **RPC sull'events-WS via broadcast**: `command.request` è broadcast (l'app è single-window; con più finestre risponde la prima, i duplicati con `correlation_id` ignoto sono ignorati). Primo uso reale di `correlation_id` (riservato in `_base.py` dal 1b).
4. **Manifest → schema del tool**: a ogni `command.manifest` il bridge RI-registra `app_command` con `enum` dei nomi nei parameters e `usage_guidance` che elenca i comandi (name, capability, description) — il modello scopre i comandi dalla superficie tool normale; la validazione jsonschema dell'executor valida gratis il nome.
5. **Validatore argsSchema FE fatto in casa** (`commands/validate.ts`, subset: object root, properties con type primitivo + enum, required, extra-prop rifiutate): nessuna nuova dipendenza (niente ajv). Gli schemi sono nostri e usano solo questo subset (obbligo dal backlog fase 6: gli args agente sono JSON non fidato, `execute` non valida).
6. **Comandi core esposti all'agente**: `view.switch`, `conversation.open`, `conversation.new`, `artifact.show` (con nuovo campo `description` machine-facing inglese). `sidebar.toggle` resta UI-only. Il test fase 6 "tutti exposeToAgent false" viene DELIBERATAMENTE sostituito dal test "l'insieme esposto è esattamente questo".
7. **Anti-escalation su due lati**: FE = solo `exposeToAgent === true` entra nel manifest ED è eseguibile via bridge (doppio check in `handleCommandRequest`); BE = `set_manifest` rifiuta strutturalmente i nomi nei domini guardrail (`GUARDRAIL_COMMAND_DOMAINS`) e le capability fuori vocabolario; `commands.disabled_commands` (config) è l'allowlist/denylist per-comando della spec.
8. **`always_offered=True`** su `app_command`: superficie di protocollo del runtime (come i meta-tool). A manifest vuoto/UI chiusa il tool resta offerto e ritorna il risultato pulito.

---

### Task 1: Contratto WS — frame `command.request` / `command.result` / `command.manifest`

**Files:**
- Modify: `backend/api/ws_schema/events.py`
- Test: `backend/tests/contracts/test_ws_schema_events.py`

- [ ] **Step 1.1: aggiorna i test di contratto (falliranno)**

In `backend/tests/contracts/test_ws_schema_events.py`:

1. In `EXPECTED_EVENTS_SERVER_TYPES` (dopo `"terminal.assigned",`, riga ~50) aggiungi:

```python
    "command.request",
```

2. In `EXPECTED_EVENTS_CLIENT_TYPES` (riga ~53) porta il set a:

```python
EXPECTED_EVENTS_CLIENT_TYPES = frozenset({
    "ping",
    "terminal.input",
    "terminal.resize",
    "command.manifest",
    "command.result",
})
```

3. In `REPRESENTATIVE_SERVER_FRAMES` aggiungi in coda alla lista:

```python
    {
        "type": "command.request",
        "origin": "agent",
        "correlation_id": "c-1",
        "name": "view.switch",
        "args": {"view": "board"},
        "conversation_id": "conv-1",
    },
]
```

4. In `REPRESENTATIVE_CLIENT_FRAMES` aggiungi in coda alla lista:

```python
    {
        "type": "command.manifest",
        "commands": [
            {
                "name": "view.switch",
                "description": "Switch the main app view",
                "capability": "navigation",
                "args_schema": {"type": "object", "properties": {}},
            },
        ],
    },
    {
        "type": "command.result",
        "correlation_id": "c-1",
        "ok": True,
        "result": {"done": True},
    },
    {
        "type": "command.result",
        "correlation_id": "c-2",
        "ok": False,
        "error": "Unknown view",
    },
]
```

- [ ] **Step 1.2: verifica che falliscano**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/contracts/test_ws_schema_events.py -v`
Expected: FAIL sui frozen-vocabulary test (`command.request` ecc. non nel vocabolario) e sui representative frame nuovi.

- [ ] **Step 1.3: aggiungi i modelli a `backend/api/ws_schema/events.py`**

1. Estendi l'import da `_base` (riga 23) a:

```python
from backend.api.ws_schema._base import ClientFrame, EventsServerFrame, Origin
```

2. Dopo la classe `WsTerminalAssigned` (riga ~341), PRIMA della sezione "Client→server frames", aggiungi:

```python
class WsCommandRequest(EventsServerFrame):
    """Command Layer RPC (spec §7): the kernel asks the UI to run a command.

    First real consumer of the envelope's ``correlation_id``: the bridge
    always sets it and the client MUST echo it verbatim on the matching
    ``command.result`` frame. ``origin`` defaults to ``agent`` because the
    request is issued on the agent's behalf inside a turn.
    """

    type: Literal["command.request"]
    origin: Origin = "agent"
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = None
```

3. In coda alla sezione "Client→server frames" (dopo `WsTerminalResize`, riga ~370) aggiungi:

```python
class CommandManifestEntry(BaseModel):
    """One agent-exposable UI command, as declared by the frontend registry.

    The manifest is the THIRD generated contract (spec §7): this model rides
    the same OpenAPI-injection pipeline as the channel unions.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    capability: Literal["navigation", "read", "mutate", "destructive"]
    args_schema: dict[str, Any] = Field(default_factory=dict)


class WsCommandManifest(ClientFrame):
    """The frontend's agent-exposable command manifest.

    Sent on events-WS connect and whenever the exposed set changes. It
    REPLACES the backend's previous manifest wholesale.
    """

    type: Literal["command.manifest"]
    commands: list[CommandManifestEntry] = Field(default_factory=list)


class WsCommandResult(ClientFrame):
    """The UI's response to a ``command.request``.

    ``correlation_id`` (envelope) must echo the request's id; a frame
    without it is dropped by the route.
    """

    type: Literal["command.result"]
    ok: bool
    result: Any = None
    error: str | None = None
```

4. In `EventsServerMessage` aggiungi `| WsCommandRequest` dopo `WsTerminalAssigned` (riga ~404).

5. Porta `EventsClientMessage` a:

```python
EventsClientMessage = Annotated[
    WsPing | WsTerminalInput | WsTerminalResize | WsCommandManifest | WsCommandResult,
    Field(discriminator="type"),
]
```

- [ ] **Step 1.4: verifica verde + contratti adiacenti**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/contracts/ -v`
Expected: PASS tutti (anche `test_openapi_export.py` e `test_ws_guard.py` — l'injection dei nuovi frame è automatica via unione).

- [ ] **Step 1.5: ruff scoped + commit**

Run (da `backend/`): `..\.venv\Scripts\ruff.exe check api/ws_schema/events.py tests/contracts/test_ws_schema_events.py`
Expected: 0 errori sui file toccati.

```powershell
git add backend/api/ws_schema/events.py backend/tests/contracts/test_ws_schema_events.py
git commit -m "feat(ws): command.request/result/manifest frames on the events channel (spec §7)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Config `commands.*` + default.yaml + flag-registry

**Files:**
- Modify: `backend/core/config.py`, `config/default.yaml`, `docs/flag-registry.md`
- Test: `backend/tests/test_config.py` (append)

- [ ] **Step 2.1: test (failing)** — in coda a `backend/tests/test_config.py` aggiungi:

```python
class TestCommandsConfig:
    """Command Bridge config section (Fase 7, spec §7)."""

    def test_defaults(self) -> None:
        from backend.core.config import AliceConfig

        cfg = AliceConfig()
        assert cfg.commands.enabled is True
        assert cfg.commands.rpc_timeout_s == 10.0
        assert cfg.commands.disabled_commands == []

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.core.config import CommandsConfig

        monkeypatch.setenv("ALICE_COMMANDS__ENABLED", "false")
        monkeypatch.setenv("ALICE_COMMANDS__RPC_TIMEOUT_S", "3.5")
        cfg = CommandsConfig()
        assert cfg.enabled is False
        assert cfg.rpc_timeout_s == 3.5
```

(Se `test_config.py` non importa già `pytest`, aggiungi l'import in testa.)

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_config.py -k Commands -v`
Expected: FAIL (`CommandsConfig` inesistente).

- [ ] **Step 2.2: implementa** — in `backend/core/config.py`, subito DOPO la classe `PermissionsConfig` (dopo riga ~373, prima di `WorkspaceScopeConfig`):

```python
class CommandsConfig(BaseSettings):
    """Command Bridge policy (Fase 7, spec §7).

    Governs the kernel-owned ``app_command`` tool and the events-WS command
    RPC. ``disabled_commands`` is the per-command denylist the spec calls
    "allowlist configurabile per comando": a listed command is dropped at
    manifest ingestion and refused at call time.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_COMMANDS__")

    enabled: bool = True
    """Master switch for the Command Bridge (tool + manifest ingestion)."""
    rpc_timeout_s: float = 10.0
    """Seconds the ``app_command`` tool waits for the UI's command.result."""
    disabled_commands: list[str] = Field(default_factory=list)
    """Command names never callable by the agent, regardless of manifest."""
```

In `AliceConfig` aggiungi il campo dopo `permissions` (riga ~1324):

```python
    commands: CommandsConfig = Field(default_factory=CommandsConfig)
```

- [ ] **Step 2.3: default.yaml** — in `config/default.yaml`, tra il blocco `permissions:` (righe 129-131) e `agent:` (riga 133), inserisci:

```yaml
# Command Bridge (spec §7): the agent drives app UI commands over the events WS.
commands:
  enabled: true
  rpc_timeout_s: 10.0
```

- [ ] **Step 2.4: flag-registry** — in `docs/flag-registry.md`, tabella "Flag vivi", aggiungi la riga (in ordine con le altre, dopo `permissions.confirmations_enabled`):

```markdown
| `commands.enabled` | true | `bootstrap/workspace.py`, `services/command_bridge.py`, route events | spegne app_command + ingestione manifest |
```

- [ ] **Step 2.5: verde + commit**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: PASS (tutti, non solo i nuovi).

```powershell
git add backend/core/config.py config/default.yaml docs/flag-registry.md backend/tests/test_config.py
git commit -m "feat(config): commands.* section for the Command Bridge (spec §7)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Kernel tools nel catalogo (registrazione, availability, dispatch)

**Files:**
- Modify: `backend/core/plugin_models.py`, `backend/core/tools/catalog.py`, `backend/core/tools/availability.py`, `backend/core/tools/execution.py`, `backend/core/tool_registry.py`, `backend/core/protocols.py`
- Test: `backend/tests/test_kernel_tools.py` (nuovo)

- [ ] **Step 3.1: test (failing)** — crea `backend/tests/test_kernel_tools.py`:

```python
"""Kernel-owned tools (Fase 7, spec §7): registration, availability, dispatch.

``app_command`` is owned by the kernel, not a plugin: the catalog stores it
under the pseudo-owner ``kernel``, the availability probe treats that owner
as always connected, and the executor dispatches to the registered handler.
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.core.config import LLMConfig
from backend.core.event_bus import EventBus
from backend.core.plugin_models import (
    KERNEL_TOOL_OWNER,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.core.tool_registry import ToolRegistry


class _NoPlugins:
    """Plugin-manager stand-in with no plugins loaded."""

    def get_all_plugins(self) -> dict[str, Any]:
        return {}

    def get_plugin(self, name: str) -> Any | None:
        return None


def _make_registry() -> ToolRegistry:
    return ToolRegistry(
        plugin_manager=_NoPlugins(),
        event_bus=EventBus(),
        qdrant_service=None,
        embedding_client=None,
        llm_config=LLMConfig(),
    )


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="s1", conversation_id="c1", execution_id="e1",
    )


def _tool(name: str = "app_command") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Kernel tool under test",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        capabilities=("ui_command",),
        always_offered=True,
    )


@pytest.mark.asyncio
async def test_kernel_tool_is_registered_and_available() -> None:
    registry = _make_registry()

    async def handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok({"echo": args})

    await registry.register_kernel_tool(_tool(), handler)
    assert registry.get_tool_definition("app_command") is not None
    assert registry.get_tool_plugin("app_command") == KERNEL_TOOL_OWNER
    available = await registry.get_available_tools()
    assert any(t["function"]["name"] == "app_command" for t in available)


@pytest.mark.asyncio
async def test_kernel_tool_dispatches_to_handler() -> None:
    registry = _make_registry()
    calls: list[dict[str, Any]] = []

    async def handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        calls.append(args)
        return ToolResult.ok({"ran": args["name"]})

    await registry.register_kernel_tool(_tool(), handler)
    result = await registry.execute_tool("app_command", {"name": "view.switch"}, _ctx())
    assert result.success is True
    assert calls == [{"name": "view.switch"}]


@pytest.mark.asyncio
async def test_kernel_tool_survives_refresh() -> None:
    registry = _make_registry()

    async def handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok(None)

    await registry.register_kernel_tool(_tool(), handler)
    await registry.refresh()
    assert registry.get_tool_definition("app_command") is not None
    assert registry.get_tool_plugin("app_command") == KERNEL_TOOL_OWNER


@pytest.mark.asyncio
async def test_kernel_tool_reregistration_replaces() -> None:
    registry = _make_registry()

    async def handler_a(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok("a")

    async def handler_b(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok("b")

    await registry.register_kernel_tool(_tool(), handler_a)
    await registry.register_kernel_tool(_tool(), handler_b)
    result = await registry.execute_tool("app_command", {"name": "x"}, _ctx())
    assert result.content == "b"
    # No duplicate OpenAI cache entry after re-registration.
    names = [t["function"]["name"] for t in registry.get_all_tools()]
    assert names.count("app_command") == 1


@pytest.mark.asyncio
async def test_kernel_tool_args_are_schema_validated() -> None:
    registry = _make_registry()

    async def handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok(None)

    await registry.register_kernel_tool(_tool(), handler)
    result = await registry.execute_tool("app_command", {}, _ctx())
    assert result.success is False
    assert "validation failed" in (result.error_message or "")
```

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_kernel_tools.py -v`
Expected: FAIL (`KERNEL_TOOL_OWNER` / `register_kernel_tool` inesistenti).

- [ ] **Step 3.2: costante in `plugin_models.py`** — accanto a `TOOL_NAME_PATTERN` (riga ~18) aggiungi:

```python
#: Pseudo owner recorded in the catalog's tool→plugin map for kernel-owned
#: tools (spec §7: ``app_command`` belongs to the kernel, not a plugin). The
#: availability probe treats this owner as always connected.
KERNEL_TOOL_OWNER = "kernel"
```

- [ ] **Step 3.3: `ToolCatalog`** — in `backend/core/tools/catalog.py`:

1. Estendi gli import:

```python
from collections.abc import Awaitable, Callable

from backend.core.plugin_models import (
    KERNEL_TOOL_OWNER,
    MAX_TOOL_DESCRIPTION_LENGTH,
    TOOL_NAME_PATTERN,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)

#: Signature of a kernel-owned tool handler (no owning plugin to delegate to).
KernelToolHandler = Callable[[dict[str, Any], ExecutionContext], Awaitable[ToolResult]]
```

2. In `__init__` aggiungi:

```python
        self._kernel_tools: dict[str, ToolDefinition] = {}
        self._kernel_handlers: dict[str, KernelToolHandler] = {}
```

3. Dopo `plugin_of` aggiungi accessor + registrazione:

```python
    def kernel_handler_of(self, ns_name: str) -> KernelToolHandler | None:
        """Return the kernel handler for *ns_name*, or ``None`` for plugin tools."""
        return self._kernel_handlers.get(ns_name)

    async def register_kernel_tool(
        self, tool_def: ToolDefinition, handler: KernelToolHandler,
    ) -> None:
        """Register (or replace) a kernel-owned tool (spec §7).

        Kernel tools have no owning plugin: they are stored under their BARE
        name (no ``<plugin>_`` prefix), mapped to :data:`KERNEL_TOOL_OWNER`,
        and survive :meth:`refresh`. Re-registration replaces definition and
        handler in place (the Command Bridge re-registers ``app_command`` on
        every manifest update to refresh the name enum).
        """
        async with self._lock:
            self._kernel_tools[tool_def.name] = tool_def
            self._kernel_handlers[tool_def.name] = handler
            self._tools[tool_def.name] = tool_def
            self._tool_to_plugin[tool_def.name] = KERNEL_TOOL_OWNER
            fmt = tool_def.to_openai_format()
            fmt["function"]["name"] = tool_def.name
            for i, entry in enumerate(self._openai_cache):
                if entry["function"]["name"] == tool_def.name:
                    self._openai_cache[i] = fmt
                    break
            else:
                self._openai_cache.append(fmt)
            self._logger.info("Kernel tool registered: {}", tool_def.name)
```

4. In `refresh()`, sostituisci l'inizializzazione di `new_tools` / `new_map` (righe 105-106) con il seeding dei kernel tools (che così sopravvivono al rebuild e vincono le collisioni via first-wins esistente):

```python
            # Kernel-owned tools survive every rebuild and win collisions
            # (a plugin tool landing on the same namespaced name is skipped
            # by the existing first-wins check below).
            new_tools: dict[str, ToolDefinition] = dict(self._kernel_tools)
            new_map: dict[str, str] = dict.fromkeys(self._kernel_tools, KERNEL_TOOL_OWNER)
```

- [ ] **Step 3.4: `AvailabilityProbe`** — in `backend/core/tools/availability.py`:

1. Estendi l'import di plugin_models (riga 17):

```python
from backend.core.plugin_models import KERNEL_TOOL_OWNER, ConnectionStatus
```

2. In testa a `_probe_plugin_status` (riga ~103, prima di `plugin = self._plugin_manager.get_plugin(...)`):

```python
        if plugin_name == KERNEL_TOOL_OWNER:
            # Kernel-owned tools have no plugin to probe: always reachable.
            return ConnectionStatus.CONNECTED
```

- [ ] **Step 3.5: `ToolExecutor`** — in `backend/core/tools/execution.py`:

1. Nel blocco snapshot-under-lock di `execute_tool` (righe 232-234), dopo `plugin_name = ...` aggiungi:

```python
            kernel_handler = self._catalog.kernel_handler_of(tool_name)
```

e nel ramo bare-name fallback, dopo `plugin_name = self._catalog.tool_to_plugin.get(resolved)` (riga ~254):

```python
                    kernel_handler = self._catalog.kernel_handler_of(resolved)
```

2. Sostituisci il blocco di risoluzione plugin (righe 267-278, da `if plugin_name is None:` a `f"plugin '{plugin_name}' is not loaded"` incluso) con:

```python
        plugin: Any = None
        if kernel_handler is None:
            if plugin_name is None:
                return ToolResult.error(
                    f"Tool '{tool_name}' not available: "
                    "no owning plugin"
                )
            plugin = self._plugin_manager.get_plugin(plugin_name)
            if plugin is None:
                return ToolResult.error(
                    f"Tool '{tool_name}' not available: "
                    f"plugin '{plugin_name}' is not loaded"
                )
```

3. Nell'invocazione (righe ~319-325) sostituisci il `try` con:

```python
        try:
            if kernel_handler is not None:
                invocation = kernel_handler(args, context)
            else:
                invocation = plugin.execute_tool(tool_def.name, args, context)
            result: ToolResult = await asyncio.wait_for(
                invocation,
                timeout=timeout_s,
            )
```

- [ ] **Step 3.6: facade + protocol**

1. In `backend/core/tool_registry.py`, dopo `refresh_availability_cache` (riga ~143) aggiungi (import `KernelToolHandler` da `backend.core.tools.catalog` in testa al file, accanto agli import esistenti dei componenti):

```python
    async def register_kernel_tool(
        self, tool_def: ToolDefinition, handler: KernelToolHandler,
    ) -> None:
        """Register (or replace) a kernel-owned tool (spec §7: app_command)."""
        await self._catalog.register_kernel_tool(tool_def, handler)
```

2. In `backend/core/protocols.py`, dentro `class ToolRegistryProtocol` (cerca `class ToolRegistryProtocol`), aggiungi accanto agli altri metodi:

```python
    async def register_kernel_tool(self, tool_def: Any, handler: Any) -> None:
        """Register (or replace) a kernel-owned tool (spec §7)."""
        ...
```

- [ ] **Step 3.7: verde + regressione mirata + commit**

Run (da `backend/`):
`..\.venv\Scripts\python.exe -m pytest tests/test_kernel_tools.py tests/test_tool_registry.py tests/test_tool_status_caching.py -v`
Expected: PASS (i test esistenti del registry NON devono cambiare comportamento).

Run: `..\.venv\Scripts\ruff.exe check core/plugin_models.py core/tools/catalog.py core/tools/availability.py core/tools/execution.py core/tool_registry.py core/protocols.py tests/test_kernel_tools.py`
Expected: 0 errori.

```powershell
git add backend/core/plugin_models.py backend/core/tools/catalog.py backend/core/tools/availability.py backend/core/tools/execution.py backend/core/tool_registry.py backend/core/protocols.py backend/tests/test_kernel_tools.py
git commit -m "feat(kernel): kernel-owned tools in the catalog with dedicated dispatch (spec §7)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `CommandBridgeService` (manifest, anti-escalation, RPC, tool app_command)

**Files:**
- Create: `backend/services/command_bridge.py`
- Test: `backend/tests/test_command_bridge.py` (nuovo)

- [ ] **Step 4.1: test (failing)** — crea `backend/tests/test_command_bridge.py`:

```python
"""Command Bridge service (Fase 7, spec §7): manifest, anti-escalation, RPC."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from backend.core.plugin_models import ExecutionContext
from backend.services.command_bridge import (
    CommandBridgeService,
    CommandSpec,
    build_app_command_definition,
)


class FakeWSManager:
    """Records broadcast frames; connection_count is settable."""

    def __init__(self, connections: int = 1) -> None:
        self.sent: list[dict[str, Any]] = []
        self.connections = connections

    @property
    def connection_count(self) -> int:
        return self.connections

    async def broadcast(self, event: dict[str, Any]) -> None:
        self.sent.append(event)


class FakeToolRegistry:
    """Records kernel-tool registrations."""

    def __init__(self) -> None:
        self.registered: list[Any] = []

    async def register_kernel_tool(self, tool_def: Any, handler: Any) -> None:
        self.registered.append(tool_def)


def _bridge(
    ws: FakeWSManager | None = None,
    registry: FakeToolRegistry | None = None,
    *,
    enabled: bool = True,
    timeout: float = 0.2,
    disabled: list[str] | None = None,
) -> CommandBridgeService:
    return CommandBridgeService(
        ws_manager=ws,
        tool_registry=registry,
        enabled=enabled,
        rpc_timeout_s=timeout,
        disabled_commands=disabled or [],
    )


def _entry(name: str, capability: str = "navigation") -> dict[str, Any]:
    return {
        "name": name,
        "description": f"desc {name}",
        "capability": capability,
        "args_schema": {"type": "object", "properties": {}},
    }


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="s1", conversation_id="c1", execution_id="e1",
    )


@pytest.mark.asyncio
async def test_manifest_rejects_guardrail_domains() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry())
    await bridge.set_manifest([
        _entry("view.switch"),
        _entry("permission.set_mode", "mutate"),
        _entry("scope.set_folder", "mutate"),
        _entry("guardrails.disable", "destructive"),
    ])
    assert bridge.capability_of("view.switch") == "navigation"
    assert bridge.capability_of("permission.set_mode") is None
    assert bridge.capability_of("scope.set_folder") is None
    assert bridge.capability_of("guardrails.disable") is None


@pytest.mark.asyncio
async def test_manifest_drops_disabled_commands_and_reregisters_tool() -> None:
    registry = FakeToolRegistry()
    bridge = _bridge(FakeWSManager(), registry, disabled=["conversation.new"])
    await bridge.set_manifest([_entry("view.switch"), _entry("conversation.new", "mutate")])
    assert bridge.capability_of("conversation.new") is None
    assert len(registry.registered) == 1
    params = registry.registered[0].parameters
    assert params["properties"]["name"]["enum"] == ["view.switch"]


@pytest.mark.asyncio
async def test_call_unknown_command_is_clean_error() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry())
    await bridge.set_manifest([_entry("view.switch")])
    outcome = await bridge.call_command("nope", {}, conversation_id="c1")
    assert outcome["ok"] is False
    assert "Unknown command" in outcome["error"]


@pytest.mark.asyncio
async def test_call_without_ui_is_clean_error() -> None:
    ws = FakeWSManager(connections=0)
    bridge = _bridge(ws, FakeToolRegistry())
    await bridge.set_manifest([_entry("view.switch")])
    outcome = await bridge.call_command("view.switch", {}, conversation_id="c1")
    assert outcome["ok"] is False
    assert "UI not available" in outcome["error"]
    assert ws.sent == []


@pytest.mark.asyncio
async def test_call_roundtrip_resolves_on_command_result() -> None:
    ws = FakeWSManager()
    bridge = _bridge(ws, FakeToolRegistry())
    await bridge.set_manifest([_entry("view.switch")])

    async def respond() -> None:
        while not ws.sent:
            await asyncio.sleep(0.01)
        frame = ws.sent[0]
        assert frame["type"] == "command.request"
        assert frame["origin"] == "agent"
        assert frame["name"] == "view.switch"
        bridge.resolve(frame["correlation_id"], {"ok": True, "result": {"view": "board"}})

    task = asyncio.create_task(respond())
    outcome = await bridge.call_command(
        "view.switch", {"view": "board"}, conversation_id="c1",
    )
    await task
    assert outcome == {"ok": True, "result": {"view": "board"}}


@pytest.mark.asyncio
async def test_call_times_out_cleanly() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry(), timeout=0.05)
    await bridge.set_manifest([_entry("view.switch")])
    outcome = await bridge.call_command("view.switch", {}, conversation_id="c1")
    assert outcome["ok"] is False
    assert "did not respond" in outcome["error"]


@pytest.mark.asyncio
async def test_disabled_bridge_refuses() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry(), enabled=False)
    await bridge.set_manifest([_entry("view.switch")])
    outcome = await bridge.call_command("view.switch", {}, conversation_id="c1")
    assert outcome["ok"] is False
    assert "disabled" in outcome["error"]


@pytest.mark.asyncio
async def test_execute_app_command_maps_to_tool_result() -> None:
    ws = FakeWSManager()
    bridge = _bridge(ws, FakeToolRegistry())
    await bridge.set_manifest([_entry("view.switch")])

    async def respond() -> None:
        while not ws.sent:
            await asyncio.sleep(0.01)
        bridge.resolve(ws.sent[0]["correlation_id"], {"ok": True, "result": None})

    task = asyncio.create_task(respond())
    result = await bridge.execute_app_command(
        {"name": "view.switch", "args": {"view": "board"}}, _ctx(),
    )
    await task
    assert result.success is True

    failure = await bridge.execute_app_command({"name": "nope"}, _ctx())
    assert failure.success is False
    assert "Unknown command" in (failure.error_message or "")


def test_resolve_unknown_correlation_is_noop() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry())
    bridge.resolve("ghost", {"ok": True})  # must not raise


def test_build_app_command_definition_bakes_manifest() -> None:
    specs = [
        CommandSpec(
            name="view.switch", description="Switch view",
            capability="navigation", args_schema={"type": "object"},
        ),
    ]
    tool = build_app_command_definition(specs)
    assert tool.name == "app_command"
    assert tool.capabilities == ("ui_command",)
    assert tool.always_offered is True
    assert tool.parameters["properties"]["name"]["enum"] == ["view.switch"]
    assert "view.switch" in (tool.usage_guidance or "")

    empty = build_app_command_definition([])
    assert "enum" not in empty.parameters["properties"]["name"]
```

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_command_bridge.py -v`
Expected: FAIL (modulo inesistente).

- [ ] **Step 4.2: implementa** — crea `backend/services/command_bridge.py`:

```python
"""AL\\CE — Command Bridge (Fase 7, spec §7): the kernel's hands on the app UI.

Backend side of the Command Layer: holds the frontend's agent-exposable
command manifest, gates it structurally (guardrail domains are rejected at
ingestion — the anti-escalation invariant), and runs the events-WS RPC for
the kernel-owned ``app_command`` tool: broadcast a ``command.request`` with a
fresh ``correlation_id``, await the matching ``command.result`` with a
timeout, and hand a CLEAN outcome back to the tool loop ("UI not available"
is a result, never an exception).

Layering: this module never imports ``backend.api.ws_schema`` — outbound
frames are plain dicts validated by the frame validator injected into the
connection manager; inbound frames are validated by the events route.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger

from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult
from backend.core.protocols import ToolRegistryProtocol, WSConnectionManagerProtocol

#: Command-name domains that configure the guardrails themselves. STRUCTURAL
#: anti-escalation (spec §7, non-negotiable): a manifest entry whose first
#: dotted segment is in this set is rejected at ingestion — the agent can
#: never call it, regardless of what the frontend declares.
GUARDRAIL_COMMAND_DOMAINS: frozenset[str] = frozenset({
    "permission",
    "permissions",
    "permission_mode",
    "scope",
    "guardrail",
    "guardrails",
})

_VALID_CAPABILITIES: frozenset[str] = frozenset({
    "navigation", "read", "mutate", "destructive",
})


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Service-layer mirror of one accepted manifest entry.

    Attributes:
        name: Dotted command name (``domain.action``).
        description: Machine-facing description for the LLM guidance.
        capability: One of ``navigation|read|mutate|destructive``.
        args_schema: JSON Schema of the command's args (informational here;
            enforced client-side before execution).
    """

    name: str
    description: str
    capability: str
    args_schema: dict[str, Any]


def build_app_command_definition(specs: list[CommandSpec]) -> ToolDefinition:
    """Build the kernel-owned ``app_command`` ToolDefinition for *specs*.

    The live manifest is baked into the tool surface: the ``name`` parameter
    carries an enum of the agent-callable command names (so the executor's
    JSON-Schema validation rejects unknown names for free) and
    ``usage_guidance`` lists each command for the system prompt.

    Args:
        specs: Accepted manifest entries (possibly empty).

    Returns:
        The ``app_command`` tool definition.
    """
    names = sorted(spec.name for spec in specs)
    name_schema: dict[str, Any] = {"type": "string"}
    if names:
        name_schema["enum"] = names
    guidance: str | None = None
    if specs:
        lines = [
            f"- `{spec.name}` ({spec.capability}): {spec.description}"
            for spec in sorted(specs, key=lambda spec: spec.name)
        ]
        guidance = (
            "Use `app_command` to drive the ALICE app UI itself (navigate, "
            "open conversations or artifacts). Pass the command `name` and "
            "its `args` object. Commands available now:\n" + "\n".join(lines)
        )
    return ToolDefinition(
        name="app_command",
        description=(
            "Invoke a UI command of the ALICE app (Command Layer). Available "
            "commands come from the app's live manifest; pass the command "
            "name and its args object."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": name_schema,
                "args": {"type": "object"},
            },
            "required": ["name"],
        },
        result_type="json",
        timeout_ms=30_000,
        capabilities=("ui_command",),
        always_offered=True,
        usage_guidance=guidance,
    )


class CommandBridgeService:
    """Manifest store + events-WS RPC for the ``app_command`` kernel tool."""

    def __init__(
        self,
        *,
        ws_manager: WSConnectionManagerProtocol | None,
        tool_registry: ToolRegistryProtocol | None,
        enabled: bool,
        rpc_timeout_s: float,
        disabled_commands: list[str],
    ) -> None:
        """Initialise the bridge.

        Args:
            ws_manager: Events-WS connection manager (broadcast + count).
            tool_registry: Registry used to (re-)register ``app_command`` on
                every manifest update. ``None`` skips tool refresh (tests).
            enabled: Master switch (``commands.enabled``).
            rpc_timeout_s: Seconds to wait for the UI's ``command.result``.
            disabled_commands: Per-command denylist (``commands.disabled_commands``).
        """
        self._ws_manager = ws_manager
        self._tool_registry = tool_registry
        self._enabled = enabled
        self._timeout_s = rpc_timeout_s
        self._disabled = frozenset(disabled_commands)
        self._manifest: dict[str, CommandSpec] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    def capability_of(self, command_name: str) -> str | None:
        """Return the manifest capability of *command_name* (``None`` = unknown).

        Consumed by ``PermissionService.decide`` as the
        ``command_capability_provider`` to resolve ``app_command``'s
        per-call effective capability.
        """
        spec = self._manifest.get(command_name)
        return spec.capability if spec is not None else None

    async def set_manifest(self, entries: list[dict[str, Any]]) -> None:
        """Replace the manifest with *entries* and refresh the kernel tool.

        Structural gates, in order: guardrail domains are REJECTED (the
        anti-escalation invariant — not configuration, construction),
        unknown capabilities are rejected, configured ``disabled_commands``
        are dropped. The surviving set replaces the previous manifest
        wholesale and ``app_command`` is re-registered with the new name
        enum + usage guidance.

        Args:
            entries: Plain-dict manifest entries (validated upstream by the
                events route against ``ws_schema``).
        """
        accepted: dict[str, CommandSpec] = {}
        for entry in entries:
            name = str(entry.get("name", ""))
            capability = str(entry.get("capability", ""))
            domain = name.split(".", 1)[0].lower()
            if not name or domain in GUARDRAIL_COMMAND_DOMAINS:
                logger.warning(
                    "Command Bridge: rejected guardrail command '{}' from manifest",
                    name,
                )
                continue
            if capability not in _VALID_CAPABILITIES:
                logger.warning(
                    "Command Bridge: rejected command '{}' with invalid capability '{}'",
                    name, capability,
                )
                continue
            if name in self._disabled:
                logger.info(
                    "Command Bridge: command '{}' disabled by configuration", name,
                )
                continue
            args_schema = entry.get("args_schema")
            accepted[name] = CommandSpec(
                name=name,
                description=str(entry.get("description", "")),
                capability=capability,
                args_schema=dict(args_schema) if isinstance(args_schema, dict) else {},
            )
        self._manifest = accepted
        logger.info(
            "Command Bridge: manifest updated ({} agent-callable commands)",
            len(accepted),
        )
        if self._tool_registry is not None:
            await self._tool_registry.register_kernel_tool(
                build_app_command_definition(list(accepted.values())),
                self.execute_app_command,
            )

    # ------------------------------------------------------------------
    # RPC
    # ------------------------------------------------------------------

    def resolve(self, correlation_id: str, payload: dict[str, Any]) -> None:
        """Resolve the pending request matching *correlation_id*.

        Called by the events route on an inbound ``command.result``. A stale
        or unknown id (timeout already fired, duplicate window answering
        twice) is a debug-logged no-op.
        """
        future = self._pending.pop(correlation_id, None)
        if future is None or future.done():
            logger.debug(
                "Command Bridge: stale/unknown correlation_id '{}'", correlation_id,
            )
            return
        future.set_result(payload)

    async def call_command(
        self,
        name: str,
        args: dict[str, Any],
        *,
        conversation_id: str,
    ) -> dict[str, Any]:
        """Run one command RPC round-trip against the UI.

        Every failure mode is a CLEAN outcome dict (never an exception), so
        the tool loop always receives a normal ``ToolResult``.

        Args:
            name: Manifest command name.
            args: Command args (opaque JSON object, validated client-side).
            conversation_id: Conversation the turn belongs to (audit/context).

        Returns:
            ``{"ok": True, "result": ...}`` or ``{"ok": False, "error": str}``.
        """
        if not self._enabled:
            return {
                "ok": False,
                "error": "Command Bridge disabled by configuration (commands.enabled=false)",
            }
        if name in self._disabled:
            return {"ok": False, "error": f"Command '{name}' is disabled by configuration"}
        if name not in self._manifest:
            known = ", ".join(sorted(self._manifest)) or "none"
            return {
                "ok": False,
                "error": f"Unknown command '{name}'. Agent-callable commands: {known}",
            }
        if self._ws_manager is None or self._ws_manager.connection_count == 0:
            return {"ok": False, "error": "UI not available (no connected frontend)"}

        correlation_id = uuid.uuid4().hex
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[correlation_id] = future
        try:
            await self._ws_manager.broadcast({
                "type": "command.request",
                "origin": "agent",
                "correlation_id": correlation_id,
                "name": name,
                "args": args,
                "conversation_id": conversation_id,
            })
            payload = await asyncio.wait_for(future, timeout=self._timeout_s)
        except TimeoutError:
            return {
                "ok": False,
                "error": f"UI did not respond to '{name}' within {self._timeout_s:.0f}s",
            }
        except Exception as exc:  # noqa: BLE001 — a clean result, never an exception
            logger.warning("Command Bridge: dispatch of '{}' failed: {}", name, exc)
            return {"ok": False, "error": f"Command dispatch failed: {exc}"}
        finally:
            self._pending.pop(correlation_id, None)

        if payload.get("ok"):
            return {"ok": True, "result": payload.get("result")}
        return {
            "ok": False,
            "error": str(payload.get("error") or "command failed in the UI"),
        }

    # ------------------------------------------------------------------
    # Kernel tool handler
    # ------------------------------------------------------------------

    async def execute_app_command(
        self, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        """Kernel handler for the ``app_command`` tool.

        Args:
            args: ``{"name": str, "args": dict}`` (schema-validated upstream
                by the executor against the manifest-derived enum).
            context: The turn's execution context.

        Returns:
            ``ToolResult.ok`` with the UI's result payload, or a clean
            ``ToolResult.error``.
        """
        name = str(args.get("name", ""))
        command_args = args.get("args") or {}
        if not isinstance(command_args, dict):
            return ToolResult.error("app_command: 'args' must be an object")
        outcome = await self.call_command(
            name, command_args, conversation_id=context.conversation_id,
        )
        if outcome.get("ok"):
            return ToolResult.ok(
                {"command": name, "result": outcome.get("result")},
                content_type="application/json",
            )
        return ToolResult.error(str(outcome.get("error") or "command failed"))
```

- [ ] **Step 4.3: verde + commit**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_command_bridge.py -v`
Expected: PASS (11 test).

Run: `..\.venv\Scripts\ruff.exe check services/command_bridge.py tests/test_command_bridge.py`
Expected: 0 errori.

```powershell
git add backend/services/command_bridge.py backend/tests/test_command_bridge.py
git commit -m "feat(services): CommandBridgeService - manifest, anti-escalation, events-WS RPC (spec §7)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: gating `ui_command` in `PermissionService.decide`

**Files:**
- Modify: `backend/services/permission_service.py`
- Test: `backend/tests/test_permission_ui_commands.py` (nuovo)

- [ ] **Step 5.1: test (failing)** — crea `backend/tests/test_permission_ui_commands.py`:

```python
"""Permission gating of the app_command kernel tool (Fase 7, spec §7).

The ``ui_command`` capability marks a tool whose EFFECTIVE capability is
per-call: the invoked command's manifest tag, resolved via the injected
``command_capability_provider``. Matrix under test (spec §7):

* navigation/read → ALLOW in every tier, ``plan`` included;
* mutate/destructive → DENY in ``plan``;
* strict → CONFIRM for mutate/destructive;
* auto_edits → ALLOW mutate, CONFIRM destructive;
* autopilot → ALLOW;
* unknown command / no manifest → treated as destructive (fail-conservative).
"""

from __future__ import annotations

import pytest
from backend.core.plugin_models import ToolDefinition
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_rules import RuleEffect
from backend.services.permission_service import GateAction, PermissionService

_CAPS = {
    "view.switch": "navigation",
    "settings.get": "read",
    "conversation.new": "mutate",
    "conversation.delete": "destructive",
}

APP_COMMAND = ToolDefinition(
    name="app_command",
    description="Command Layer tool",
    parameters={"type": "object", "properties": {"name": {"type": "string"}}},
    capabilities=("ui_command",),
)


def _service(**kwargs: object) -> PermissionService:
    return PermissionService(
        command_capability_provider=_CAPS.get,
        **kwargs,  # type: ignore[arg-type]
    )


def _decide(
    service: PermissionService, command: str, mode: PermissionMode,
) -> GateAction:
    return service.decide(
        tool_name="app_command",
        args={"name": command},
        tool_def=APP_COMMAND,
        conversation_id="c1",
        mode=mode,
    ).action


@pytest.mark.parametrize("mode", list(PermissionMode))
@pytest.mark.parametrize("command", ["view.switch", "settings.get"])
def test_navigation_and_read_allowed_everywhere(
    mode: PermissionMode, command: str,
) -> None:
    assert _decide(_service(), command, mode) is GateAction.ALLOW


@pytest.mark.parametrize("command", ["conversation.new", "conversation.delete"])
def test_mutate_and_destructive_denied_in_plan(command: str) -> None:
    assert _decide(_service(), command, PermissionMode.PLAN) is GateAction.DENY


@pytest.mark.parametrize("command", ["conversation.new", "conversation.delete"])
def test_mutate_and_destructive_confirm_in_strict(command: str) -> None:
    assert (
        _decide(_service(), command, PermissionMode.STRICT)
        is GateAction.NEEDS_CONFIRMATION
    )


def test_auto_edits_allows_mutate_confirms_destructive() -> None:
    service = _service()
    assert (
        _decide(service, "conversation.new", PermissionMode.AUTO_EDITS)
        is GateAction.ALLOW
    )
    assert (
        _decide(service, "conversation.delete", PermissionMode.AUTO_EDITS)
        is GateAction.NEEDS_CONFIRMATION
    )


def test_autopilot_allows_all() -> None:
    service = _service()
    for command in _CAPS:
        assert _decide(service, command, PermissionMode.AUTOPILOT) is GateAction.ALLOW


def test_unknown_command_is_fail_conservative() -> None:
    service = _service()
    assert _decide(service, "ghost.cmd", PermissionMode.PLAN) is GateAction.DENY
    assert (
        _decide(service, "ghost.cmd", PermissionMode.STRICT)
        is GateAction.NEEDS_CONFIRMATION
    )
    assert _decide(service, "ghost.cmd", PermissionMode.AUTOPILOT) is GateAction.ALLOW


def test_no_provider_is_fail_conservative() -> None:
    service = PermissionService()
    assert (
        _decide(service, "view.switch", PermissionMode.STRICT)
        is GateAction.NEEDS_CONFIRMATION
    )


def test_rules_and_grants_still_apply() -> None:
    deny = PermissionService(
        command_capability_provider=_CAPS.get,
        rule_provider=lambda conv, tool: RuleEffect.DENY,
    )
    assert _decide(deny, "view.switch", PermissionMode.AUTOPILOT) is GateAction.DENY

    ask = PermissionService(
        command_capability_provider=_CAPS.get,
        rule_provider=lambda conv, tool: RuleEffect.ASK,
    )
    assert (
        _decide(ask, "conversation.new", PermissionMode.AUTOPILOT)
        is GateAction.NEEDS_CONFIRMATION
    )

    granted = _service()
    granted.grant("c1", "app_command")
    assert (
        _decide(granted, "conversation.delete", PermissionMode.STRICT)
        is GateAction.ALLOW
    )
```

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_permission_ui_commands.py -v`
Expected: FAIL (`command_capability_provider` inesistente).

- [ ] **Step 5.2: implementa** — in `backend/services/permission_service.py`:

1. Dopo `RuleProvider` (riga ~45) aggiungi:

```python
# Resolves a UI command name to its manifest capability tag
# (navigation|read|mutate|destructive), or ``None`` when unknown (Fase 7).
CommandCapabilityProvider = Callable[[str], "str | None"]

#: Capability tag marking the kernel's ``app_command`` tool: its EFFECTIVE
#: capability is per-call (the invoked command's manifest tag), resolved via
#: the injected ``command_capability_provider``.
UI_COMMAND_CAPABILITY = "ui_command"
```

2. In `__init__` aggiungi il parametro (dopo `fs_capabilities`) e il campo:

```python
        command_capability_provider: CommandCapabilityProvider | None = None,
```

```python
        self._command_capability_provider = command_capability_provider
```

e nel docstring degli Args:

```python
            command_capability_provider: Resolves a UI command name to its
                manifest capability tag (Fase 7 Command Bridge). ``None``
                (or an unknown command) makes ``app_command`` calls
                fail-conservative (treated as ``destructive``).
```

3. In `decide()`, subito DOPO il blocco "2. explicit deny rule" (riga ~274) e PRIMA di "3 + 4. filesystem scope confinement", aggiungi:

```python
        # 2-bis. UI commands (Fase 7, spec §7): the EFFECTIVE capability is
        # the invoked command's manifest tag, not the tool's own — resolve it
        # per-call and apply the §7 matrix. Grants and allow/ask rules keep
        # their usual precedence; the deny rule above already won.
        if UI_COMMAND_CAPABILITY in caps:
            return self._decide_ui_command(args, mode, granted=granted, rule=rule)
```

4. Dopo `decide()` (prima di `_check_scope`) aggiungi:

```python
    def _decide_ui_command(
        self,
        args: dict[str, object],
        mode: PermissionMode,
        *,
        granted: bool,
        rule: RuleEffect | None,
    ) -> GateDecision:
        """Spec §7 matrix for ``app_command``: gate on the command's tag.

        ``navigation``/``read`` are always allowed (reads never prompt, any
        tier — plan included); ``mutate``/``destructive`` are denied in
        ``plan`` and confirmed in ``strict``; ``auto_edits`` auto-approves
        ``mutate`` but confirms ``destructive``; ``autopilot`` allows. An
        unknown command (absent manifest/provider) is treated as
        ``destructive`` — fail-conservative; execution then returns its own
        clean "unknown command" / "UI not available" result.
        """
        command = str(args.get("name", ""))
        capability = (
            self._command_capability_provider(command)
            if self._command_capability_provider is not None
            else None
        ) or "destructive"
        if capability in ("navigation", "read"):
            return GateDecision.allow()
        if mode is PermissionMode.PLAN:
            return GateDecision.deny(PermissionOutcome.DENY_PLAN_MODE, "plan_mode")
        if granted or rule is RuleEffect.ALLOW:
            return GateDecision.allow()
        if rule is RuleEffect.ASK:
            return GateDecision.confirm()
        if mode is PermissionMode.AUTOPILOT:
            return GateDecision.allow()
        if mode is PermissionMode.AUTO_EDITS and capability == "mutate":
            return GateDecision.allow()
        return GateDecision.confirm()
```

- [ ] **Step 5.3: verde + regressione permessi + commit**

Run (da `backend/`):
`..\.venv\Scripts\python.exe -m pytest tests/test_permission_ui_commands.py tests/test_permission_service.py tests/test_permission_tiers.py tests/test_permission_scope_confinement.py tests/test_permission_rules.py -v`
Expected: PASS tutti (nessuna regressione sui gate esistenti).

Run: `..\.venv\Scripts\ruff.exe check services/permission_service.py tests/test_permission_ui_commands.py`
Expected: 0 errori.

```powershell
git add backend/services/permission_service.py backend/tests/test_permission_ui_commands.py
git commit -m "feat(permissions): per-call ui_command gating for app_command (spec §7 matrix)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: wiring — service group, context, bootstrap, route events

**Files:**
- Modify: `backend/core/service_groups.py`, `backend/core/context.py`, `backend/core/bootstrap/workspace.py`, `backend/api/routes/events.py`
- Test: `backend/tests/test_command_bridge_route.py` (nuovo); attenzione a `backend/tests/test_context_groups.py` (potrebbe enumerare i campi dei gruppi: se fallisce, aggiorna la lista attesa aggiungendo `command_bridge_service`)

- [ ] **Step 6.1: test route (failing)** — crea `backend/tests/test_command_bridge_route.py`:

```python
"""Events-route ingestion of command.manifest / command.result (Fase 7)."""

from __future__ import annotations

from typing import Any

import pytest
from backend.api.routes.events import _handle_command_frame


class _FakeBridge:
    def __init__(self) -> None:
        self.manifests: list[list[dict[str, Any]]] = []
        self.resolved: list[tuple[str, dict[str, Any]]] = []

    async def set_manifest(self, entries: list[dict[str, Any]]) -> None:
        self.manifests.append(entries)

    def resolve(self, correlation_id: str, payload: dict[str, Any]) -> None:
        self.resolved.append((correlation_id, payload))


class _FakeCtx:
    def __init__(self) -> None:
        self.command_bridge_service = _FakeBridge()


@pytest.mark.asyncio
async def test_manifest_frame_is_validated_and_ingested() -> None:
    ctx = _FakeCtx()
    await _handle_command_frame(ctx, {
        "type": "command.manifest",
        "commands": [{
            "name": "view.switch",
            "description": "Switch view",
            "capability": "navigation",
            "args_schema": {"type": "object"},
        }],
    })
    assert len(ctx.command_bridge_service.manifests) == 1
    assert ctx.command_bridge_service.manifests[0][0]["name"] == "view.switch"


@pytest.mark.asyncio
async def test_result_frame_resolves_by_correlation_id() -> None:
    ctx = _FakeCtx()
    await _handle_command_frame(ctx, {
        "type": "command.result",
        "correlation_id": "c-9",
        "ok": True,
        "result": {"done": True},
    })
    assert ctx.command_bridge_service.resolved == [
        ("c-9", {"ok": True, "result": {"done": True}, "error": None}),
    ]


@pytest.mark.asyncio
async def test_invalid_frame_is_dropped_silently() -> None:
    ctx = _FakeCtx()
    await _handle_command_frame(ctx, {"type": "command.result", "ok": "not-a-bool"})
    await _handle_command_frame(ctx, {"type": "command.manifest", "commands": "nope"})
    assert ctx.command_bridge_service.resolved == []
    assert ctx.command_bridge_service.manifests == []


@pytest.mark.asyncio
async def test_result_without_correlation_id_is_dropped() -> None:
    ctx = _FakeCtx()
    await _handle_command_frame(ctx, {"type": "command.result", "ok": True})
    assert ctx.command_bridge_service.resolved == []


@pytest.mark.asyncio
async def test_missing_bridge_is_noop() -> None:
    class _EmptyCtx:
        pass

    await _handle_command_frame(_EmptyCtx(), {"type": "command.result", "ok": True})
```

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_command_bridge_route.py -v`
Expected: FAIL (`_handle_command_frame` inesistente).

- [ ] **Step 6.2: service group + context**

1. In `backend/core/service_groups.py`, dentro `WorkspaceServices` (dopo `terminal_session_manager`, riga 95):

```python
    command_bridge_service: Any = None
    """Command Bridge (spec §7): manifest + events-WS RPC for app_command."""
```

2. In `backend/core/context.py`, nella sezione del gruppo Workspace (cerca `def terminal_session_manager`), aggiungi accanto la coppia property/setter:

```python
    @property
    def command_bridge_service(self) -> Any:
        return self.workspace.command_bridge_service

    @command_bridge_service.setter
    def command_bridge_service(self, value: Any) -> None:
        self.workspace.command_bridge_service = value
```

- [ ] **Step 6.3: bootstrap** — in `backend/core/bootstrap/workspace.py`:

1. Subito PRIMA del blocco "Permission service" (riga ~65, il commento `# -- Permission service ...`), aggiungi:

```python
    # -- Command Bridge (Fase 7, spec §7): agent-driven UI commands ------
    # Needs the events-WS manager (stage_surfaces) and the tool registry
    # (stage_plugins) — both already wired when this stage runs. Created
    # BEFORE PermissionService so its bound ``capability_of`` can be
    # injected as the per-call capability resolver for ``app_command``.
    from backend.services.command_bridge import (
        CommandBridgeService,
        build_app_command_definition,
    )

    command_bridge = CommandBridgeService(
        ws_manager=ctx.ws_connection_manager,
        tool_registry=ctx.tool_registry,
        enabled=ctx.config.commands.enabled,
        rpc_timeout_s=ctx.config.commands.rpc_timeout_s,
        disabled_commands=ctx.config.commands.disabled_commands,
    )
    ctx.command_bridge_service = command_bridge
```

2. Estendi il costruttore di `PermissionService` (righe 75-79) a:

```python
    ctx.permission_service = PermissionService(
        scope_provider=scope_service.effective_roots,
        rule_provider=rule_service.match,
        forbidden_paths=ctx.config.scope.forbidden_paths,
        command_capability_provider=command_bridge.capability_of,
    )
```

3. In coda alla funzione (dopo il blocco terminal, riga ~98) aggiungi:

```python
    # -- Kernel tool: app_command (spec §7) ------------------------------
    # Registered from boot with an empty manifest so the tool exists even
    # before the UI connects; every command.manifest re-registers it with
    # the live name enum + usage guidance.
    if ctx.config.commands.enabled and ctx.tool_registry is not None:
        await ctx.tool_registry.register_kernel_tool(
            build_app_command_definition([]),
            command_bridge.execute_app_command,
        )
```

- [ ] **Step 6.4: route events** — in `backend/api/routes/events.py`:

1. Estendi gli import:

```python
from pydantic import ValidationError

from backend.api.ws_schema import validate_events_client
from backend.core.context import AppContext
```

2. Dopo `_handle_terminal_frame` (riga ~57) aggiungi:

```python
async def _handle_command_frame(ctx: Any, data: dict[str, Any]) -> None:
    """Validate and route a Command Layer frame (spec §7) from the client.

    ``command.manifest`` replaces the bridge's agent-callable manifest;
    ``command.result`` resolves the pending RPC future by ``correlation_id``
    (a frame without one is dropped). Best-effort: an invalid frame is
    debug-logged and ignored — a bad frame must never drop the events socket.
    """
    bridge = getattr(ctx, "command_bridge_service", None)
    if bridge is None:
        return
    try:
        frame = validate_events_client(data)
    except ValidationError as exc:
        logger.debug("Events WS: invalid command frame ignored: {}", exc)
        return
    if frame.type == "command.manifest":
        await bridge.set_manifest([entry.model_dump() for entry in frame.commands])
    elif frame.type == "command.result" and frame.correlation_id:
        bridge.resolve(
            frame.correlation_id,
            {"ok": frame.ok, "result": frame.result, "error": frame.error},
        )
```

(Nota: il parametro `ctx` è tipato `Any` perché il test lo pilota con un fake; il chiamante passa l'`AppContext` reale.)

3. Nel receive loop di `ws_events`, dopo il ramo `terminal.*` (riga ~100), aggiungi:

```python
                elif mtype in ("command.manifest", "command.result"):
                    # Command Layer RPC (spec §7): manifest ingestion and
                    # command.result correlation for the app_command tool.
                    await _handle_command_frame(ctx, data)
```

- [ ] **Step 6.5: verde + boot-check + commit**

Run (da `backend/`):
`..\.venv\Scripts\python.exe -m pytest tests/test_command_bridge_route.py tests/test_context.py tests/test_context_groups.py tests/test_bootstrap.py -v`
Expected: PASS. Se `test_context_groups` enumera i campi di `WorkspaceServices`, aggiorna la lista attesa con `command_bridge_service` (è un cambiamento intenzionale del gruppo).

Run (dalla REPO ROOT, boot-check offline):
`.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('boot ok')"`
Expected: `boot ok`.

Run (dalla REPO ROOT): `.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml`
Expected: `Contracts: X kept, 0 broken`.

```powershell
git add backend/core/service_groups.py backend/core/context.py backend/core/bootstrap/workspace.py backend/api/routes/events.py backend/tests/test_command_bridge_route.py
git commit -m "feat(kernel): wire CommandBridgeService - workspace group, bootstrap, events-route RPC ingestion (spec §7)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Se `test_context_groups.py` è stato aggiornato, includilo nel commit.

---

### Task 7: rigenerazione contratti (UNICO task che rigenera)

**Files:**
- Regenerate: `frontend/src/renderer/src/types/generated/openapi.json`, `frontend/src/renderer/src/types/generated/api.d.ts`
- Modify: `frontend/src/renderer/src/types/generated/index.ts`

- [ ] **Step 7.1: rigenera**

Run (dalla REPO ROOT): `.\scripts\gen-contracts.ps1`
Expected: exit 0; `git status` mostra `openapi.json` e `api.d.ts` modificati.

- [ ] **Step 7.2: alias in `types/generated/index.ts`** (unico file generato editabile a mano) — accanto agli alias WS esistenti aggiungi:

```ts
export type WsCommandRequest = ApiSchema<'WsCommandRequest'>
export type CommandManifestEntry = ApiSchema<'CommandManifestEntry'>
```

- [ ] **Step 7.3: typecheck FE — DEVE fallire sul dispatcher**

Run (da `frontend/`): `npm run typecheck`
Expected: FAIL con errore su `useEventsWebSocket.ts` (`'command.request'` mancante in `EventsHandlerMap`). Questo è il tripwire di contratto atteso: NON sistemarlo qui — l'handler arriva nel Task 8.

- [ ] **Step 7.4: commit**

```powershell
git add frontend/src/renderer/src/types/generated/
git commit -m "chore(contracts): regenerate for command.request/result/manifest frames" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Run (dalla REPO ROOT, DOPO il commit): `.\scripts\check-contracts.ps1`
Expected: exit 0 (albero pulito).

---

### Task 8: frontend — description, comandi esposti, validatore, bridge, dispatcher

**Files:**
- Modify: `frontend/src/renderer/src/commands/types.ts`, `commands/core.ts`, `commands/core.spec.ts`, `commands/index.ts`, `composables/useEventsWebSocket.ts`
- Create: `frontend/src/renderer/src/commands/validate.ts`, `commands/validate.spec.ts`, `commands/bridge.ts`, `commands/bridge.spec.ts`

- [ ] **Step 8.1: `description` su `CommandDefinition`** — in `commands/types.ts`, dopo il campo `title` aggiungi:

```ts
  /**
   * Machine-facing description (English) for the agent manifest. Required
   * on every `exposeToAgent` command; `title` stays the human label.
   */
  description?: string
```

- [ ] **Step 8.2: esponi i comandi core** — in `commands/core.ts` aggiungi ai QUATTRO comandi `view.switch`, `conversation.open`, `conversation.new`, `artifact.show` (NON `sidebar.toggle`) le due righe dopo `title`:

```ts
    description: 'Switch the main app view to the given route name',
    exposeToAgent: true,
```

con descrizioni rispettivamente:
- `view.switch`: `'Switch the main app view to the given route name'`
- `conversation.open`: `'Open an existing conversation by id and land on the active chat surface'`
- `conversation.new`: `'Create a new conversation and land on the active chat surface'`
- `artifact.show`: `'Open the artifacts board focused on the given artifact id'`

- [ ] **Step 8.3: aggiorna `core.spec.ts`** — sostituisci il test anti-escalation di fase 6 (quello con `expect(def.exposeToAgent ?? false).toBe(false)` su tutti i comandi) con:

```ts
  it('exposes exactly the Fase 7 agent-callable core set', () => {
    const exposed = commandRegistry
      .list()
      .filter((d) => d.exposeToAgent === true)
      .map((d) => d.name)
      .sort()
    expect(exposed).toEqual([
      'artifact.show',
      'conversation.new',
      'conversation.open',
      'view.switch'
    ])
  })

  it('every exposed command carries a machine-facing description', () => {
    for (const def of commandRegistry.list()) {
      if (def.exposeToAgent === true) {
        expect(def.description, `${def.name} needs a description`).toBeTruthy()
      }
    }
  })

  it('keeps sidebar.toggle UI-only (never agent-callable)', () => {
    const def = commandRegistry.list().find((d) => d.name === 'sidebar.toggle')
    expect(def?.exposeToAgent ?? false).toBe(false)
  })
```

- [ ] **Step 8.4: validatore** — crea `commands/validate.ts`:

```ts
/**
 * Minimal JSON-Schema-subset validator for agent-supplied command args
 * (Fase 7). Agent args arrive over the wire as UNTRUSTED JSON: the registry's
 * `execute` does not validate, so the bridge MUST (fase 6 backlog).
 *
 * Deliberately dependency-free: registry schemas only use this subset —
 * object root, `properties` with primitive `type` and optional `enum`,
 * `required`. Unknown args are rejected (mirrors the backend's
 * `extra="forbid"` stance).
 */

type PropertySchema = Record<string, unknown>

/**
 * @returns `null` when `args` conforms to `schema`, else a human-readable
 *   error message (returned to the agent as the command failure).
 */
export function validateCommandArgs(
  schema: Record<string, unknown> | undefined,
  args: Record<string, unknown>
): string | null {
  if (!schema || schema.type !== 'object') return null
  const properties = (schema.properties ?? {}) as Record<string, PropertySchema>
  const required = Array.isArray(schema.required) ? (schema.required as string[]) : []
  for (const key of required) {
    if (!(key in args)) return `Missing required arg: ${key}`
  }
  for (const [key, value] of Object.entries(args)) {
    const prop = properties[key]
    if (!prop) return `Unknown arg: ${key}`
    const error = validateValue(key, value, prop)
    if (error) return error
  }
  return null
}

function validateValue(key: string, value: unknown, prop: PropertySchema): string | null {
  switch (prop.type) {
    case 'string':
      if (typeof value !== 'string') return `Arg '${key}' must be a string`
      break
    case 'number':
      if (typeof value !== 'number') return `Arg '${key}' must be a number`
      break
    case 'integer':
      if (typeof value !== 'number' || !Number.isInteger(value))
        return `Arg '${key}' must be an integer`
      break
    case 'boolean':
      if (typeof value !== 'boolean') return `Arg '${key}' must be a boolean`
      break
    case 'object':
      if (typeof value !== 'object' || value === null || Array.isArray(value))
        return `Arg '${key}' must be an object`
      break
    case 'array':
      if (!Array.isArray(value)) return `Arg '${key}' must be an array`
      break
  }
  const allowed = prop.enum
  if (Array.isArray(allowed) && !allowed.includes(value)) {
    return `Arg '${key}' must be one of: ${allowed.join(', ')}`
  }
  return null
}
```

- [ ] **Step 8.5: spec del validatore** — crea `commands/validate.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { validateCommandArgs } from './validate'

const schema = {
  type: 'object',
  properties: {
    view: { type: 'string', enum: ['board', 'assistant'] },
    count: { type: 'integer' },
    flag: { type: 'boolean' }
  },
  required: ['view']
}

describe('validateCommandArgs', () => {
  it('accepts conforming args', () => {
    expect(validateCommandArgs(schema, { view: 'board', count: 2, flag: true })).toBeNull()
  })

  it('rejects a missing required arg', () => {
    expect(validateCommandArgs(schema, {})).toMatch(/Missing required arg: view/)
  })

  it('rejects an unknown arg', () => {
    expect(validateCommandArgs(schema, { view: 'board', nope: 1 })).toMatch(/Unknown arg: nope/)
  })

  it('rejects a wrong primitive type', () => {
    expect(validateCommandArgs(schema, { view: 42 })).toMatch(/must be a string/)
    expect(validateCommandArgs(schema, { view: 'board', count: 1.5 })).toMatch(
      /must be an integer/
    )
    expect(validateCommandArgs(schema, { view: 'board', flag: 'yes' })).toMatch(
      /must be a boolean/
    )
  })

  it('rejects a value outside the enum', () => {
    expect(validateCommandArgs(schema, { view: 'nope' })).toMatch(/must be one of/)
  })

  it('is permissive without a usable schema', () => {
    expect(validateCommandArgs(undefined, { anything: 1 })).toBeNull()
    expect(validateCommandArgs({ type: 'string' }, { anything: 1 })).toBeNull()
  })
})
```

- [ ] **Step 8.6: bridge FE** — crea `commands/bridge.ts`:

```ts
/**
 * Command Bridge (Fase 7, spec §7) — frontend side of the app_command RPC.
 *
 * Builds the agent-exposable manifest from the Command Registry and executes
 * `command.request` frames from the events WS, replying with `command.result`
 * (correlation_id echoed verbatim). STRUCTURAL anti-escalation: ONLY commands
 * with `exposeToAgent === true` are declared in the manifest AND executable
 * on the agent's behalf — the double check makes a forged request for a
 * guardrail command a clean error, not an execution.
 *
 * The frame sender is injected (instead of importing `sendEventsMessage`) to
 * avoid a module cycle with `useEventsWebSocket` and keep this unit testable.
 */
import { commandRegistry } from './registry'
import { validateCommandArgs } from './validate'
import type {
  CommandManifestEntry,
  EventsClientMessage,
  WsCommandRequest
} from '../types/generated'

export type SendFrame = (frame: EventsClientMessage) => boolean

/** Manifest projection of the registry: exposeToAgent commands only. */
export function buildCommandManifest(): CommandManifestEntry[] {
  return commandRegistry
    .list()
    .filter((def) => def.exposeToAgent === true)
    .map((def) => ({
      name: def.name,
      description: def.description ?? def.title,
      capability: def.capability,
      args_schema: def.argsSchema ?? { type: 'object', properties: {} }
    }))
}

/** Send the current manifest to the backend (on WS open and on changes). */
export function sendCommandManifest(send: SendFrame): boolean {
  return send({ type: 'command.manifest', commands: buildCommandManifest() })
}

/** Execute a backend `command.request` and reply with `command.result`. */
export async function handleCommandRequest(
  msg: WsCommandRequest,
  send: SendFrame
): Promise<void> {
  const reply = (ok: boolean, result?: unknown, error?: string): void => {
    void send({
      type: 'command.result',
      correlation_id: msg.correlation_id,
      ok,
      result: result ?? null,
      error: error ?? null
    })
  }
  const def = commandRegistry.list().find((d) => d.name === msg.name)
  if (!def || def.exposeToAgent !== true) {
    reply(false, undefined, `Command not agent-callable: ${msg.name}`)
    return
  }
  const args = (msg.args ?? {}) as Record<string, unknown>
  const validationError = validateCommandArgs(def.argsSchema, args)
  if (validationError) {
    reply(false, undefined, validationError)
    return
  }
  try {
    const result = await commandRegistry.execute(msg.name, args)
    reply(true, result ?? null)
  } catch (err) {
    reply(false, undefined, err instanceof Error ? err.message : String(err))
  }
}
```

Nota: se il typecheck segnala che i campi generati `result`/`error` non ammettono `null`, allinea le due righe della `reply` alle forme generate (`result: result`, `error`) — i tipi generati vincono, mai il contrario.

- [ ] **Step 8.7: spec del bridge** — crea `commands/bridge.spec.ts`:

```ts
import { afterEach, describe, expect, it } from 'vitest'
import { commandRegistry } from './registry'
import { buildCommandManifest, handleCommandRequest, sendCommandManifest } from './bridge'
import type { EventsClientMessage, WsCommandRequest } from '../types/generated'

function makeSender(): { frames: EventsClientMessage[]; send: (f: EventsClientMessage) => boolean } {
  const frames: EventsClientMessage[] = []
  return { frames, send: (f) => (frames.push(f), true) }
}

function request(name: string, args: Record<string, unknown> = {}): WsCommandRequest {
  return {
    type: 'command.request',
    correlation_id: 'c-1',
    name,
    args
  } as WsCommandRequest
}

afterEach(() => commandRegistry.clear())

describe('buildCommandManifest', () => {
  it('projects only exposeToAgent commands with description fallback', () => {
    commandRegistry.register({
      name: 'a.exposed',
      title: 'Titolo umano',
      capability: 'navigation',
      exposeToAgent: true,
      run: () => 1
    })
    commandRegistry.register({
      name: 'b.hidden',
      title: 'B',
      capability: 'mutate',
      run: () => 2
    })
    const manifest = buildCommandManifest()
    expect(manifest).toHaveLength(1)
    expect(manifest[0].name).toBe('a.exposed')
    expect(manifest[0].description).toBe('Titolo umano')
    expect(manifest[0].capability).toBe('navigation')
  })
})

describe('sendCommandManifest', () => {
  it('sends a command.manifest frame', () => {
    const { frames, send } = makeSender()
    expect(sendCommandManifest(send)).toBe(true)
    expect(frames[0].type).toBe('command.manifest')
  })
})

describe('handleCommandRequest', () => {
  it('executes an exposed command and replies ok with the correlation id', async () => {
    commandRegistry.register<{ x: number }>({
      name: 'a.run',
      title: 'A',
      capability: 'navigation',
      exposeToAgent: true,
      argsSchema: { type: 'object', properties: { x: { type: 'number' } }, required: ['x'] },
      run: ({ x }) => x * 2
    })
    const { frames, send } = makeSender()
    await handleCommandRequest(request('a.run', { x: 21 }), send)
    expect(frames).toHaveLength(1)
    const reply = frames[0] as Extract<EventsClientMessage, { type: 'command.result' }>
    expect(reply.type).toBe('command.result')
    expect(reply.correlation_id).toBe('c-1')
    expect(reply.ok).toBe(true)
    expect(reply.result).toBe(42)
  })

  it('refuses a non-exposed command (structural anti-escalation)', async () => {
    let ran = false
    commandRegistry.register({
      name: 'guard.only',
      title: 'G',
      capability: 'mutate',
      run: () => {
        ran = true
      }
    })
    const { frames, send } = makeSender()
    await handleCommandRequest(request('guard.only'), send)
    const reply = frames[0] as Extract<EventsClientMessage, { type: 'command.result' }>
    expect(ran).toBe(false)
    expect(reply.ok).toBe(false)
    expect(reply.error).toMatch(/not agent-callable/)
  })

  it('refuses an unknown command', async () => {
    const { frames, send } = makeSender()
    await handleCommandRequest(request('ghost.cmd'), send)
    const reply = frames[0] as Extract<EventsClientMessage, { type: 'command.result' }>
    expect(reply.ok).toBe(false)
  })

  it('rejects invalid args before executing', async () => {
    let ran = false
    commandRegistry.register({
      name: 'a.strict',
      title: 'A',
      capability: 'navigation',
      exposeToAgent: true,
      argsSchema: { type: 'object', properties: { v: { type: 'string' } }, required: ['v'] },
      run: () => {
        ran = true
      }
    })
    const { frames, send } = makeSender()
    await handleCommandRequest(request('a.strict', { v: 5 }), send)
    const reply = frames[0] as Extract<EventsClientMessage, { type: 'command.result' }>
    expect(ran).toBe(false)
    expect(reply.ok).toBe(false)
    expect(reply.error).toMatch(/must be a string/)
  })

  it('maps a throwing command to a clean error reply', async () => {
    commandRegistry.register({
      name: 'a.boom',
      title: 'A',
      capability: 'navigation',
      exposeToAgent: true,
      run: () => {
        throw new Error('boom')
      }
    })
    const { frames, send } = makeSender()
    await handleCommandRequest(request('a.boom'), send)
    const reply = frames[0] as Extract<EventsClientMessage, { type: 'command.result' }>
    expect(reply.ok).toBe(false)
    expect(reply.error).toBe('boom')
  })
})
```

- [ ] **Step 8.8: dispatcher + manifest on open** — in `composables/useEventsWebSocket.ts`:

1. Aggiungi l'import (dopo gli import degli store):

```ts
import { handleCommandRequest, sendCommandManifest } from '../commands/bridge'
```

2. Nella mappa `handlers` aggiungi la chiave (accanto agli altri, prima dei `terminal.*`):

```ts
    'command.request': (msg) => void handleCommandRequest(msg, sendEventsMessage),
```

3. In `ws.onopen`, dopo il blocco `pingInterval = setInterval(...)`, aggiungi:

```ts
      // Command Layer (Fase 7): declare the agent-callable manifest on every
      // (re)connect — the backend replaces its copy wholesale.
      sendCommandManifest(sendEventsMessage)
```

4. Aggiorna il barrel `commands/index.ts` esportando i nuovi moduli:

```ts
export { buildCommandManifest, handleCommandRequest, sendCommandManifest } from './bridge'
export type { SendFrame } from './bridge'
export { validateCommandArgs } from './validate'
```

- [ ] **Step 8.9: gate FE completo + commit**

Run (da `frontend/`): `npm run typecheck`
Expected: exit 0 (il tripwire del Task 7 è risolto dall'handler).

Run: `npm test`
Expected: PASS — 162 test preesistenti + i nuovi (validate ~7, bridge ~7, core aggiornati).

Run: `npm run lint`
Expected: exit 0, 0 errori e 0 warning.

Verifica EOL prima del commit: `git diff --stat` — un diff enorme su file non toccati = flip EOL, fermati e ripristina.

```powershell
git add frontend/src/renderer/src/commands/ frontend/src/renderer/src/composables/useEventsWebSocket.ts
git commit -m "feat(fe): Command Bridge - manifest, args validation, command.request execution (spec §7)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: gate finale di fase

- [ ] **Step 9.1: suite mirata backend** (da `backend/`):

```powershell
..\.venv\Scripts\python.exe -m pytest tests/contracts/ tests/test_kernel_tools.py tests/test_command_bridge.py tests/test_command_bridge_route.py tests/test_permission_ui_commands.py tests/test_config.py tests/test_tool_registry.py tests/test_permission_service.py tests/test_permission_tiers.py tests/test_pipeline.py tests/test_tool_loop.py -v
```
Expected: PASS (ricorda: `test_plugins_enabled_list` NON è in questa lista; se compare rosso altrove è l'ereditato 21 vs 20).

- [ ] **Step 9.2: layering + boot** (dalla REPO ROOT):

```powershell
.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(testing=True); print('boot ok')"
```
Expected: contratti import 0 broken; `boot ok`.

- [ ] **Step 9.3: contratti puliti** (dalla REPO ROOT, ad albero committato):

```powershell
.\scripts\check-contracts.ps1
```
Expected: exit 0.

- [ ] **Step 9.4: gate FE** (da `frontend/`): `npm run typecheck`, `npm run lint`, `npm test` — tutti exit 0.

- [ ] **Step 9.5: EOL check**: `git ls-files --eol | Select-String -Pattern "i/mixed"` → vuoto; confronta con lo stato pre-fase (restano i 4 `w/crlf` storici documentati).

- [ ] **Step 9.6: smoke E2E manuale (criterio spec §9 — feature del dominio funzionante)**

Checklist (con backend + `npm run dev` attivi, LM Studio/Ollama su):
1. All'avvio il backend logga `Command Bridge: manifest updated (4 agent-callable commands)`.
2. In chat (tier `auto_edits` o `autopilot`): «apri la board» → l'agente chiama `app_command {name: "view.switch", args: {view: "board"}}` → la vista cambia e il tool result è success.
3. In tier `strict`: «crea una nuova conversazione» → arriva la richiesta di CONFERMA per `app_command` (capability `mutate`); approva → conversazione creata.
4. In tier `plan`: lo stesso comando `conversation.new` viene RIFIUTATO dal gate (plan_mode); `view.switch` invece funziona.
5. Chiudi la finestra frontend (backend vivo), invia un turno via un client WS/voce se disponibile — oppure verifica via test: `call_command` senza connessioni → «UI not available» (già coperto da unit test; lo smoke manuale è opzionale).
6. Riconnetti/riapri: il manifest viene ri-inviato (log backend di nuovo `manifest updated`).

- [ ] **Step 9.7: chiusura** — aggiorna questo piano con gli esiti per task (esito review incluso), aggiorna l'handoff (`docs/superpowers/handoffs/`) e ferma qui: merge/push li decide l'utente.

---

## Fuori scope (registrato, non fare)

- Promozione di `WsSendPayload` a frame tipizzato (il protocollo client→server della CHAT non è toccato da questa fase).
- Migrazione di `useVoice` al pattern tipizzato; bridge `client_tool_call` FE.
- Router-link → comandi; board che consuma `?artifact=`; command palette.
- TriggerService / AttentionService (fase 8).
- Audit ROW dedicata per comando (l'audit passa già dal turn engine come per ogni tool; una tabella dedicata è fase 8 se serve).

## Backlog emerso in pianificazione

1. `commandRegistry.execute` resta non-validante per i call-site UI (la validazione è solo sul percorso agente): valutare estenderla anche alla UI.
2. Manifest non persistito: dopo un riavvio backend con UI già connessa il manifest arriva solo alla riconnessione WS (il reconnect FE lo ri-invia: accettabile; verificare in smoke).
3. `resolve()` accetta il primo `command.result` per `correlation_id`: con più finestre il comando è eseguito da TUTTE (broadcast) — oggi non è un problema (single-window); se arriverà il multi-window servirà un target di sessione (`send_to`).
4. `AvailabilityProbe` speciale-casa l'owner `kernel` dentro `_probe_plugin_status`: se nascesse un plugin chiamato `kernel` andrebbe rinominato (guardia non implementata, solo convenzione).
