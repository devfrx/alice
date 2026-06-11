# Fase 1b — Schema WS tipizzato (envelope piatto + codegen) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ogni messaggio dei due canali WebSocket (chat ed events) diventa un modello Pydantic in `backend/api/ws_schema/`, esportato nello stesso documento OpenAPI della Fase 1a e generato come unione TypeScript discriminata su `type`; `useEventsWebSocket.ts` diventa un dispatcher esaustivo (evento non gestito = errore di compilazione); i gate di contratto girano in una CI minima.

**Architecture:** Envelope **piatto** (`type` Literal discriminante + `origin` + `correlation_id?`, NESSUN wrapper `payload` — deciso in design: stessa garanzia, zero migrazione doppia; `origin`/`correlation_id` hanno default così i frame attuali, che non li portano, validano invariati). I modelli vivono in `backend/api/ws_schema/` (spec §6); le unioni discriminate vengono **iniettate come components nello stesso `openapi.json`** della Fase 1a, così `openapi-typescript` genera i tipi TS senza nuovi tool ("estendere lo script, non duplicarlo"). Enforcement: test di vocabolario congelato + validazione runtime opzionale (warning in prod, raise sotto pytest) iniettata per DI nei chokepoint di invio (mai import `api` da `services`).

**Tech Stack:** Python 3.11+/FastAPI/Pydantic v2/pytest (backend), openapi-typescript v7 (già installato, pin via `npm ci`), PowerShell 5.1, vue-tsc, GitHub Actions (windows runner).

**Riferimento spec:** `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` §6 (WS), §9 (enforcement). Backlog 1a: la CI minima è il Task 1 di questo piano.

**Branch:** `arch/fase1b-ws-schema`, creato da `arch/fase1a-contratti-rest` (la 1a non è mergiata; questo piano dipende dalla sua pipeline di codegen).

**Contesto repo (verificato a mano il 2026-06-11 — inventario completo dei frame):**

- *Canale chat* (`/api/ws/chat`, handler `backend/api/routes/chat/ws.py`):
  - Server→client (27 tipi): legacy streaming `token`, `thinking`, `tool_call`, `error` (da `llm_service`, inoltrati da `direct_executor.py:393-438`; il frame `usage` LLM è consumato internamente e **NON** inoltrato — diventa `turn.usage`); `done` finale costruito SOLO da `_persist.py:34-59`; tool-loop `tool_execution_start` (`pipeline.py:434`), `tool_execution_done` (`tool_loop.py:661`), `tool_progress` (`pipeline.py:536`, payload extra dinamico), `context_info` (con `is_estimated` e `breakdown`, `_assembly.py:678-692`, `tool_loop.py:827-839` manda `breakdown: None`), `context_compression_start/done/failed`, `llm_requery`, `warning`; interazioni `tool_confirmation_required`/`client_tool_call`/`ask_user_required` (mappa `_REQUEST_SPECS` in `services/turn/channel.py:51-55`, payload in `pipeline.py:643-656,694-700,774-787`); canonici `turn.started/llm_step/usage/finished`, `tool.call/result`, `interaction.requested/resolved` (`services/turn/events.py`; `interaction.resolved` usa anche outcome `"failed"`, `pipeline.py:469`); reflective `agent.critic_invoked`, `agent.warning` (`reflective_executor.py:117-133`).
  - Client→server: messaggio utente **senza campo `type`** (`{content, conversation_id?, attachments?, edit_message_id?}`); `cancel`; risposte `tool_confirmation_response`, `client_tool_result` (campi letti: `success`, `result`, `error` — `pipeline.py:721-736`), `ask_user_response` (`answers[].{question_id, selected, free_text}`).
- *Canale events* (`/api/events/ws`, `backend/api/routes/events.py`):
  - Server→client (24 tipi): `pong`, `heartbeat` (route stessa); bridge lifespan `app.py:533-638` (`mcp.server.connected/disconnected`, `email.received/sent`, `note.created/updated/deleted`, `service.status`, `knowledge.status`); `service.model_download_progress` (`model_downloader.py:568-577`: `service, model_id, downloaded_bytes, total_bytes, phase, file, error?`); callback servizi (`artifact.created`, `tasks.updated`, `plan_document.updated`, `scope.updated`, `permission_mode.updated`); terminal (`terminal.session_opened` con snapshot `session.py:157-170`, `terminal.output/closed/renamed/assigned`); `calendar_changed` (**unico nome fuori convenzione**, `api/routes/calendar.py:346,408,438`); `config.changed` (`api/routes/config.py:141-146`).
  - Client→server: `ping`, `terminal.input`, `terminal.resize`.
- *Frontend*: unione `WsMessage` in `types/chat.ts:483-499` (chat); tipi canonici a mano in `types/turn.ts`; tipi events a mano in `types/{tasks,planDocument,scope,permission,terminal,email}.ts`; dispatcher if/else in `composables/useEventsWebSocket.ts:105-179`; `sendEventsMessage` usato solo da `stores/terminalSessions.ts`; manager chat `services/ws.ts` è un emitter per-tipo non tipizzato (resta tale in 1b).
- *Pipeline 1a da riusare*: `backend/api/openapi_export.py` (`build_schema()` + `main()`), `scripts/gen-contracts.ps1`, `scripts/check-contracts.ps1`, alias `ApiSchema` in `frontend/src/renderer/src/types/generated/index.ts`.
- JSON Schema dei modelli WS in modalità **validation** (default di Pydantic): i campi con default risultano opzionali — è la rappresentazione veritiera del filo (oggi `origin` non viene emesso).
- Gate pratici (gotchas 1a): suite backend completa impraticabile → test mirati `tests/contracts/` + domini toccati; `ruff`/`eslint` scoped ai file toccati; `npm run typecheck` exit 0 obbligatorio; `check-contracts.ps1` DOPO il commit; ogni `write_text` destinato al commit usa `newline="\n"`.

---

### Task 1: CI minima per i gate di contratto

I gate diventano reali solo in CI (backlog 1a, punto 1). Workflow su runner Windows: test contratti, freshness dei generati, typecheck FE.

**Files:**
- Create: `.github/workflows/contracts.yml`

- [x] **Step 1: Creare il workflow**

Creare `.github/workflows/contracts.yml` (gli exit-check per riga nello step pip sono un fix di review: sotto `shell: pwsh` GitHub propaga solo l'exit code dell'ULTIMO comando):

```yaml
# FE<->BE contract gates (Fase 1 of the architecture remediation).
# Windows runner: the repo targets Windows first and the codegen scripts
# are PowerShell. Codegen tool versions are pinned by npm ci (lockfile).
name: contracts

on:
  push:
    branches: [main]
  pull_request:

jobs:
  contracts:
    runs-on: windows-latest
    defaults:
      run:
        shell: pwsh
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Create venv and install backend
        run: |
          python -m venv .venv
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          .\.venv\Scripts\python.exe -m pip install --upgrade pip
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          .\.venv\Scripts\python.exe -m pip install -e "backend[dev,memory]"
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          .\.venv\Scripts\python.exe -m pip install sqlite-vec

      - name: Install frontend deps
        working-directory: frontend
        run: npm ci

      - name: Contract tests
        working-directory: backend
        run: |
          ..\.venv\Scripts\python.exe -m pytest tests/contracts/ -v
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

      - name: Generated artifacts are fresh
        run: .\scripts\check-contracts.ps1

      - name: Frontend typecheck
        working-directory: frontend
        run: npm run typecheck
```

- [x] **Step 2: Validare la sintassi YAML in locale**

Run (da repo root): `.\.venv\Scripts\python.exe -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/contracts.yml').read_text(encoding='utf-8')); print('YAML OK')"`
Expected: `YAML OK` (PyYAML è una dipendenza transitiva del backend nel venv; se mancasse, verificare l'indentazione a mano — non installare nulla solo per questo).

Nota: il workflow non può essere eseguito end-to-end in locale; la verifica completa avverrà al primo push. Non è un criterio di uscita bloccante di questo task.

- [x] **Step 3: Commit**

```powershell
git add .github/workflows/contracts.yml
git commit -m "ci(contracts): minimal Windows workflow - contract tests, codegen freshness, FE typecheck"
```

> Eseguito @ 677ae6d; fix di review (exit-check per riga) @ 2cc996c.

---

### Task 2: Rinomina `calendar_changed` → `calendar.changed`

Unico evento fuori convenzione `dominio.azione` (spec §6). Va fatto PRIMA dei modelli, così lo schema nasce col nome finale. Cambio sincronizzato BE+FE nello stesso commit.

**Files:**
- Modify: `backend/api/routes/calendar.py:346,408,438`
- Modify: `frontend/src/renderer/src/composables/useEventsWebSocket.ts:113`

- [x] **Step 1: Rinominare nel backend**

In `backend/api/routes/calendar.py`, sostituire in TUTTE e tre le occorrenze (righe ~346, ~408, ~438):

```python
            "type": "calendar_changed",
```

con:

```python
            "type": "calendar.changed",
```

- [x] **Step 2: Rinominare nel frontend**

In `frontend/src/renderer/src/composables/useEventsWebSocket.ts` riga ~113, sostituire:

```ts
        if (data.type === 'calendar_changed') {
```

con:

```ts
        if (data.type === 'calendar.changed') {
```

- [x] **Step 3: Verificare che non restino riferimenti**

Run (da repo root): `git grep -n "calendar_changed" -- backend frontend/src`
Expected: nessun risultato (exit code 1). Se compaiono altri riferimenti (test, store), aggiornarli allo stesso modo e annotarlo qui.

- [x] **Step 4: Lint e typecheck mirati**

Run (da `backend/`): `ruff check api/routes/calendar.py`
Run (da `frontend/`): `npx eslint src/renderer/src/composables/useEventsWebSocket.ts; npm run typecheck`
Expected: typecheck exit 0. Nota a posteriori: `calendar.py` ha 11 errori ruff PRE-ESISTENTI (verificato sul commit parent: nessuno introdotto dal rename) — vale il gate "ruff scoped alle righe toccate".

- [x] **Step 5: Commit**

```powershell
git add backend/api/routes/calendar.py frontend/src/renderer/src/composables/useEventsWebSocket.ts
git commit -m "refactor(ws)!: rename calendar_changed to calendar.changed (dominio.azione convention)"
```

> Eseguito @ 1ef6f4f (review: nessun consumatore nascosto del vecchio nome; unico emettitore confermato `api/routes/calendar.py`; nessun rischio replay — WS manager fire-and-forget).

---

### Task 3: Pacchetto `ws_schema` — envelope + canale events

**Files:**
- Create: `backend/api/ws_schema/__init__.py`
- Create: `backend/api/ws_schema/_base.py`
- Create: `backend/api/ws_schema/events.py`
- Test: `backend/tests/contracts/test_ws_schema_events.py`

- [ ] **Step 1: Scrivere il test che fallisce**

Creare `backend/tests/contracts/test_ws_schema_events.py`:

```python
"""Contract tests: events-channel WS frames validate against ws_schema.

The representative frames below are copied VERBATIM from the emit sites
(app.py lifespan bridges, service callbacks, terminal manager, calendar
and config routes). If one stops validating, either the emitter drifted
(fix the emitter) or the contract changed intentionally (update model,
frame here, and the frozen vocabulary).
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.api.ws_schema import (
    EVENTS_CLIENT_TYPES,
    EVENTS_SERVER_TYPES,
    validate_events_client,
    validate_events_server,
)
from pydantic import ValidationError

EXPECTED_EVENTS_SERVER_TYPES = frozenset({
    "pong",
    "heartbeat",
    "mcp.server.connected",
    "mcp.server.disconnected",
    "email.received",
    "email.sent",
    "note.created",
    "note.updated",
    "note.deleted",
    "service.status",
    "service.model_download_progress",
    "knowledge.status",
    "artifact.created",
    "tasks.updated",
    "plan_document.updated",
    "scope.updated",
    "permission_mode.updated",
    "calendar.changed",
    "config.changed",
    "terminal.session_opened",
    "terminal.output",
    "terminal.closed",
    "terminal.renamed",
    "terminal.assigned",
})

EXPECTED_EVENTS_CLIENT_TYPES = frozenset({
    "ping",
    "terminal.input",
    "terminal.resize",
})

REPRESENTATIVE_SERVER_FRAMES: list[dict[str, Any]] = [
    {"type": "pong"},
    {"type": "heartbeat"},
    {"type": "mcp.server.connected", "server": "fs"},
    {"type": "mcp.server.disconnected", "server": "fs", "reason": "eof"},
    {"type": "email.received", "folder": "INBOX"},
    {"type": "email.sent", "message_id": "abc"},
    {"type": "note.created", "note_id": "n1", "title": "t"},
    {"type": "note.updated", "note_id": "n1"},
    {"type": "note.deleted", "note_id": "n1"},
    {
        "type": "service.status",
        "service": "qdrant",
        "status": "ready",
        "detail": None,
        "timestamp": 1718000000.0,
    },
    {
        "type": "service.model_download_progress",
        "service": "stt",
        "model_id": "whisper-small",
        "downloaded_bytes": 10,
        "total_bytes": 100,
        "phase": "downloading",
        "file": "model.bin",
    },
    {
        "type": "knowledge.status",
        "ready": True,
        "reason": None,
        "memory_enabled": True,
        "tool_rag_enabled": False,
    },
    {
        "type": "artifact.created",
        "artifact_id": "a1",
        "kind": "cad_3d_text",
        "conversation_id": "c1",
        "title": "tiny cube",
    },
    {
        "type": "tasks.updated",
        "conversation_id": "c1",
        "steps": [{"step": "do x", "status": "pending"}],
    },
    {
        "type": "plan_document.updated",
        "conversation_id": "c1",
        "title": "",
        "body": "",
        "updated_at": None,
    },
    {"type": "scope.updated", "conversation_id": "c1", "folders": ["C:/ws"]},
    {"type": "permission_mode.updated", "conversation_id": "c1", "mode": "strict"},
    {"type": "calendar.changed", "action": "created", "event_id": "e1"},
    {"type": "config.changed", "path": "llm.temperature", "value": 0.2, "layer": "user"},
    {
        "type": "terminal.session_opened",
        "conversation_id": "c1",
        "session": {
            "id": "s1",
            "conversation_id": "c1",
            "title": "shell",
            "cwd": "C:/ws",
            "rows": 24,
            "cols": 80,
            "agent_assigned": False,
            "created_at": "2026-06-11T00:00:00",
            "pid": 1234,
            "alive": True,
        },
    },
    {"type": "terminal.output", "conversation_id": "c1", "session_id": "s1", "data": "$ "},
    {"type": "terminal.closed", "conversation_id": "c1", "session_id": "s1", "exit_code": None},
    {"type": "terminal.renamed", "conversation_id": "c1", "session_id": "s1", "title": "t"},
    {"type": "terminal.assigned", "conversation_id": "c1", "session_id": "s1"},
]

REPRESENTATIVE_CLIENT_FRAMES: list[dict[str, Any]] = [
    {"type": "ping"},
    {"type": "terminal.input", "conversation_id": "c1", "session_id": "s1", "data": "ls\r"},
    {"type": "terminal.resize", "conversation_id": "c1", "session_id": "s1", "rows": 40, "cols": 120},
]


def test_events_server_vocabulary_is_frozen() -> None:
    """Adding/removing a frame type must be a conscious, reviewed change."""
    assert EVENTS_SERVER_TYPES == EXPECTED_EVENTS_SERVER_TYPES


def test_events_client_vocabulary_is_frozen() -> None:
    assert EVENTS_CLIENT_TYPES == EXPECTED_EVENTS_CLIENT_TYPES


@pytest.mark.parametrize(
    "frame", REPRESENTATIVE_SERVER_FRAMES, ids=lambda f: str(f["type"]),
)
def test_representative_server_frames_validate(frame: dict[str, Any]) -> None:
    validate_events_server(frame)


@pytest.mark.parametrize(
    "frame", REPRESENTATIVE_CLIENT_FRAMES, ids=lambda f: str(f["type"]),
)
def test_representative_client_frames_validate(frame: dict[str, Any]) -> None:
    validate_events_client(frame)


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_events_server({"type": "no.such.event"})


def test_extra_field_is_rejected() -> None:
    """extra='forbid' makes silent payload drift loud."""
    with pytest.raises(ValidationError):
        validate_events_server({"type": "pong", "surprise": 1})
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run (da `backend/`): `pytest tests/contracts/test_ws_schema_events.py -v`
Expected: ERROR con `ModuleNotFoundError: No module named 'backend.api.ws_schema'`

- [ ] **Step 3: Implementare l'envelope**

Creare `backend/api/ws_schema/_base.py`:

```python
"""AL\\CE — Flat WS envelope shared by every WebSocket message (spec §6).

Every WS frame on both channels is a Pydantic model carrying:

* ``type`` — the Literal discriminant (declared per message);
* ``origin`` — who caused the frame (``user`` | ``agent`` | ``system``);
* ``correlation_id`` — reserved for request/response correlation in the
  Command Layer RPC (spec §7); interaction frames keep their existing
  ``execution_id`` field unchanged.

The envelope is FLAT — no ``payload`` wrapper. The current wire format is
flat and wrapping would force a synchronized FE+BE migration for zero
added guarantee (design decision, 2026-06-10).

``origin`` and ``correlation_id`` have defaults so today's frames (which
do not carry them yet) validate unchanged: the schema documents the
target envelope while staying truthful about the wire.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Origin = Literal["user", "agent", "system"]


class WsFrame(BaseModel):
    """Base class for every WS message; ``extra='forbid'`` keeps drift loud."""

    model_config = ConfigDict(extra="forbid")

    origin: Origin = "system"
    correlation_id: str | None = None


class EventsServerFrame(WsFrame):
    """Server→client frame on the events channel (background push)."""


class ChatServerFrame(WsFrame):
    """Server→client frame on the chat channel (turn streaming)."""

    origin: Origin = "agent"


class ClientFrame(WsFrame):
    """Client→server frame on either channel."""

    origin: Origin = "user"
```

- [ ] **Step 4: Implementare i modelli del canale events**

Creare `backend/api/ws_schema/events.py`:

```python
"""AL\\CE — Typed schema of the events WebSocket channel (``/api/events/ws``).

One Pydantic model per frame. Field shapes were audited from the actual
emit sites on 2026-06-11:

* route keep-alives — ``api/routes/events.py``;
* lifespan bus bridges — ``core/app.py`` (mcp/email/note/service/knowledge);
* model downloads — ``services/model_downloader.py`` (dynamic payload);
* service callbacks — artifacts registry, plan/plan-document/scope/
  permission-mode services, terminal manager;
* REST side-effects — ``api/routes/calendar.py``, ``api/routes/config.py``.

Bridges forward ``kwargs.get(...)`` values, so most payload fields are
typed Optional with ``None`` defaults: absent-on-the-wire must validate.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from backend.api.ws_schema._base import ClientFrame, EventsServerFrame

# ---------------------------------------------------------------------------
# Keep-alives
# ---------------------------------------------------------------------------


class WsPong(EventsServerFrame):
    """Reply to a client ``ping``."""

    type: Literal["pong"]


class WsHeartbeat(EventsServerFrame):
    """Periodic liveness frame pushed when the client is idle."""

    type: Literal["heartbeat"]


# ---------------------------------------------------------------------------
# MCP / email / notes / services (lifespan bus bridges)
# ---------------------------------------------------------------------------


class WsMcpServerConnected(EventsServerFrame):
    type: Literal["mcp.server.connected"]
    server: str | None = None


class WsMcpServerDisconnected(EventsServerFrame):
    type: Literal["mcp.server.disconnected"]
    server: str | None = None
    reason: str | None = None


class WsEmailReceived(EventsServerFrame):
    type: Literal["email.received"]
    folder: str = "INBOX"


class WsEmailSent(EventsServerFrame):
    type: Literal["email.sent"]
    message_id: str | None = None


class WsNoteCreated(EventsServerFrame):
    type: Literal["note.created"]
    note_id: str | None = None
    title: str | None = None


class WsNoteUpdated(EventsServerFrame):
    type: Literal["note.updated"]
    note_id: str | None = None


class WsNoteDeleted(EventsServerFrame):
    type: Literal["note.deleted"]
    note_id: str | None = None


class WsServiceStatus(EventsServerFrame):
    type: Literal["service.status"]
    service: str
    status: str
    detail: str | None = None
    timestamp: float | str | None = None


class WsKnowledgeStatus(EventsServerFrame):
    type: Literal["knowledge.status"]
    ready: bool | None = None
    reason: str | None = None
    memory_enabled: bool | None = None
    tool_rag_enabled: bool | None = None


class WsModelDownloadProgress(EventsServerFrame):
    """Model-download progress; payload is forwarded verbatim from the bus.

    ``extra='allow'``: the downloader may add fields without a synchronized
    schema bump (explicitly accepted dynamic payload, see model_downloader).
    """

    model_config = ConfigDict(extra="allow")

    type: Literal["service.model_download_progress"]
    service: str | None = None
    model_id: str | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    phase: str | None = None
    file: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Content / agent surfaces (service callbacks)
# ---------------------------------------------------------------------------


class WsArtifactCreated(EventsServerFrame):
    type: Literal["artifact.created"]
    artifact_id: str
    kind: str
    conversation_id: str
    title: str | None = None


class WsTaskStep(BaseModel):
    """One ordered step of a conversation task list (``update_plan``).

    Nested payload, not a frame: no envelope. ``extra='allow'`` because the
    step dicts come from the agent's ``update_plan`` tool and may grow.
    """

    model_config = ConfigDict(extra="allow")

    step: str
    status: str


class WsTasksUpdated(EventsServerFrame):
    type: Literal["tasks.updated"]
    conversation_id: str
    steps: list[WsTaskStep]


class WsPlanDocumentUpdated(EventsServerFrame):
    type: Literal["plan_document.updated"]
    conversation_id: str
    title: str
    body: str
    updated_at: str | None = None


class WsScopeUpdated(EventsServerFrame):
    type: Literal["scope.updated"]
    conversation_id: str
    folders: list[str]


class WsPermissionModeUpdated(EventsServerFrame):
    """Tier change push.

    ``mode`` is a Literal (not the ``PermissionMode`` enum) to avoid a
    ``$defs`` name collision with the REST component of the same name;
    ``test_mode_literal_matches_enum`` pins the two in sync.
    """

    type: Literal["permission_mode.updated"]
    conversation_id: str
    mode: Literal["strict", "auto_edits", "plan", "autopilot"]


class WsCalendarChanged(EventsServerFrame):
    type: Literal["calendar.changed"]
    action: Literal["created", "updated", "deleted"]
    event_id: str


class WsConfigChanged(EventsServerFrame):
    type: Literal["config.changed"]
    path: str
    value: Any = None
    layer: str


# ---------------------------------------------------------------------------
# Terminal (PTY sessions)
# ---------------------------------------------------------------------------


class WsTerminalSession(BaseModel):
    """JSON snapshot of a live terminal session (``session.snapshot()``).

    Nested payload, not a frame: no envelope.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    conversation_id: str
    title: str
    cwd: str
    rows: int
    cols: int
    agent_assigned: bool
    created_at: str
    pid: int | None = None
    alive: bool


class WsTerminalSessionOpened(EventsServerFrame):
    type: Literal["terminal.session_opened"]
    conversation_id: str
    session: WsTerminalSession


class WsTerminalOutput(EventsServerFrame):
    type: Literal["terminal.output"]
    conversation_id: str
    session_id: str
    data: str


class WsTerminalClosed(EventsServerFrame):
    type: Literal["terminal.closed"]
    conversation_id: str
    session_id: str
    exit_code: int | None = None


class WsTerminalRenamed(EventsServerFrame):
    type: Literal["terminal.renamed"]
    conversation_id: str
    session_id: str
    title: str


class WsTerminalAssigned(EventsServerFrame):
    type: Literal["terminal.assigned"]
    conversation_id: str
    session_id: str


# ---------------------------------------------------------------------------
# Client→server control frames
# ---------------------------------------------------------------------------


class WsPing(ClientFrame):
    type: Literal["ping"]


class WsTerminalInput(ClientFrame):
    type: Literal["terminal.input"]
    conversation_id: str
    session_id: str
    data: str


class WsTerminalResize(ClientFrame):
    type: Literal["terminal.resize"]
    conversation_id: str
    session_id: str
    rows: int
    cols: int


# ---------------------------------------------------------------------------
# Channel unions (discriminated on ``type``)
# ---------------------------------------------------------------------------

EventsServerMessage = Annotated[
    Union[
        WsPong,
        WsHeartbeat,
        WsMcpServerConnected,
        WsMcpServerDisconnected,
        WsEmailReceived,
        WsEmailSent,
        WsNoteCreated,
        WsNoteUpdated,
        WsNoteDeleted,
        WsServiceStatus,
        WsKnowledgeStatus,
        WsModelDownloadProgress,
        WsArtifactCreated,
        WsTasksUpdated,
        WsPlanDocumentUpdated,
        WsScopeUpdated,
        WsPermissionModeUpdated,
        WsCalendarChanged,
        WsConfigChanged,
        WsTerminalSessionOpened,
        WsTerminalOutput,
        WsTerminalClosed,
        WsTerminalRenamed,
        WsTerminalAssigned,
    ],
    Field(discriminator="type"),
]

EventsClientMessage = Annotated[
    Union[WsPing, WsTerminalInput, WsTerminalResize],
    Field(discriminator="type"),
]
```

- [ ] **Step 5: Implementare `__init__.py` con unioni, vocabolari e validatori**

Creare `backend/api/ws_schema/__init__.py`:

```python
"""AL\\CE — Typed WebSocket contract (spec §6).

Every message on the two WS channels (``chat``, ``events``) is a Pydantic
model with a flat envelope (``type`` discriminant + ``origin`` +
``correlation_id?``). The channel unions are injected into the OpenAPI
export (``backend/api/openapi_export.py``) so the frontend consumes them
as generated discriminated TS unions.
"""

from __future__ import annotations

import typing
from typing import Any

from pydantic import TypeAdapter

from backend.api.ws_schema.events import (
    EventsClientMessage,
    EventsServerMessage,
)


def _union_member_types(union: Any) -> frozenset[str]:
    """Extract the ``type`` Literal of every member of a discriminated union."""
    members = typing.get_args(typing.get_args(union)[0])
    found: set[str] = set()
    for member in members:
        literal = member.model_fields["type"].annotation
        found.add(typing.get_args(literal)[0])
    return frozenset(found)


_EVENTS_SERVER_ADAPTER: TypeAdapter[Any] = TypeAdapter(EventsServerMessage)
_EVENTS_CLIENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(EventsClientMessage)

EVENTS_SERVER_TYPES: frozenset[str] = _union_member_types(EventsServerMessage)
EVENTS_CLIENT_TYPES: frozenset[str] = _union_member_types(EventsClientMessage)

#: Union name -> adapter; consumed by the OpenAPI export to inject the WS
#: contract as named components (Task 5 extends this dict for the chat channel).
WS_CONTRACT_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "EventsServerMessage": _EVENTS_SERVER_ADAPTER,
    "EventsClientMessage": _EVENTS_CLIENT_ADAPTER,
}


def validate_events_server(frame: dict[str, Any]) -> Any:
    """Validate a server→client events frame; raises ``ValidationError``."""
    return _EVENTS_SERVER_ADAPTER.validate_python(frame)


def validate_events_client(frame: dict[str, Any]) -> Any:
    """Validate a client→server events frame; raises ``ValidationError``."""
    return _EVENTS_CLIENT_ADAPTER.validate_python(frame)


__all__ = [
    "EVENTS_CLIENT_TYPES",
    "EVENTS_SERVER_TYPES",
    "EventsClientMessage",
    "EventsServerMessage",
    "WS_CONTRACT_ADAPTERS",
    "validate_events_client",
    "validate_events_server",
]
```

- [ ] **Step 6: Eseguire il test e verificare che passi**

Run (da `backend/`): `pytest tests/contracts/test_ws_schema_events.py -v`
Expected: tutti PASS. Se un frame rappresentativo non valida, NON piegare il test: ricontrollare il sito di emissione citato nel contesto e correggere il modello (o, se l'emettitore è buggato, fermarsi e segnalarlo).

- [ ] **Step 7: Test di coerenza Literal/enum per il permission mode**

Aggiungere in coda a `backend/tests/contracts/test_ws_schema_events.py`:

```python
def test_mode_literal_matches_enum() -> None:
    """The WS Literal must track the PermissionMode enum exactly."""
    import typing

    from backend.api.ws_schema.events import WsPermissionModeUpdated
    from backend.services.permission_mode_service import PermissionMode

    literal = WsPermissionModeUpdated.model_fields["mode"].annotation
    assert set(typing.get_args(literal)) == {m.value for m in PermissionMode}
```

Run (da `backend/`): `pytest tests/contracts/test_ws_schema_events.py -v`
Expected: tutti PASS.

- [ ] **Step 8: Lint e typecheck**

Run (da `backend/`): `ruff check api/ws_schema/ tests/contracts/test_ws_schema_events.py; mypy api/ws_schema/ tests/contracts/test_ws_schema_events.py`
Expected: nessun errore.

- [ ] **Step 9: Commit**

```powershell
git add backend/api/ws_schema backend/tests/contracts/test_ws_schema_events.py
git commit -m "feat(contracts): typed ws_schema package - flat envelope + events channel"
```

---

### Task 4: `ws_schema` — canale chat

**Files:**
- Create: `backend/api/ws_schema/chat.py`
- Modify: `backend/api/ws_schema/__init__.py`
- Test: `backend/tests/contracts/test_ws_schema_chat.py`

- [ ] **Step 1: Scrivere il test che fallisce**

Creare `backend/tests/contracts/test_ws_schema_chat.py`:

```python
"""Contract tests: chat-channel WS frames validate against ws_schema.

Representative frames copied VERBATIM from the emit sites (llm_service
stream forwarding, tool_loop/pipeline, chat _persist/_assembly, turn
events builders, reflective executor, interaction channel).
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.api.ws_schema import (
    CHAT_CLIENT_TYPES,
    CHAT_SERVER_TYPES,
    validate_chat_client,
    validate_chat_server,
)
from pydantic import ValidationError

EXPECTED_CHAT_SERVER_TYPES = frozenset({
    "token",
    "thinking",
    "tool_call",
    "done",
    "error",
    "tool_execution_start",
    "tool_execution_done",
    "tool_progress",
    "context_info",
    "context_compression_start",
    "context_compression_done",
    "context_compression_failed",
    "llm_requery",
    "warning",
    "tool_confirmation_required",
    "client_tool_call",
    "ask_user_required",
    "turn.started",
    "turn.llm_step",
    "tool.call",
    "tool.result",
    "interaction.requested",
    "interaction.resolved",
    "turn.usage",
    "turn.finished",
    "agent.critic_invoked",
    "agent.warning",
})

EXPECTED_CHAT_CLIENT_TYPES = frozenset({
    "cancel",
    "tool_confirmation_response",
    "client_tool_result",
    "ask_user_response",
})

REPRESENTATIVE_SERVER_FRAMES: list[dict[str, Any]] = [
    {"type": "token", "content": "ciao"},
    {"type": "thinking", "content": "hmm"},
    {
        "type": "tool_call",
        "id": "call_1",
        "function": {"name": "web_search", "arguments": "{\"q\": \"x\"}"},
    },
    {
        "type": "done",
        "conversation_id": "c1",
        "message_id": "m2",
        "user_message_id": "m1",
        "finish_reason": "stop",
        "version_group_id": None,
        "version_index": 0,
    },
    {"type": "error", "content": "boom"},
    {"type": "tool_execution_start", "tool_name": "web_search", "execution_id": "e1"},
    {
        "type": "tool_execution_done",
        "tool_name": "web_search",
        "result": "ok",
        "execution_id": "e1",
        "success": True,
    },
    {
        "type": "tool_progress",
        "tool_name": "cad_generate",
        "execution_id": "e1",
        "phase": "sampling",
        "step": 3,
        "total": 10,
    },
    {
        "type": "context_info",
        "used": 1000,
        "available": 7000,
        "context_window": 8192,
        "percentage": 0.12,
        "was_compressed": False,
        "messages_summarized": 0,
        "is_estimated": True,
        "breakdown": {
            "system": 1,
            "tools": 2,
            "messages": 3,
            "files": 0,
            "tool_results": 0,
            "other": 0,
        },
    },
    {
        "type": "context_info",
        "used": 1,
        "available": 2,
        "context_window": 3,
        "percentage": 0.5,
        "was_compressed": True,
        "messages_summarized": 4,
        "is_estimated": False,
        "breakdown": None,
    },
    {"type": "context_compression_start"},
    {"type": "context_compression_done", "messages_summarized": 4},
    {"type": "context_compression_done", "messages_summarized": 4, "summary_message_id": "m9"},
    {"type": "context_compression_failed"},
    {"type": "llm_requery", "iteration": 2},
    {"type": "warning", "content": "budget exceeded"},
    {
        "type": "tool_confirmation_required",
        "execution_id": "e1",
        "tool_name": "write_file",
        "args": {"path": "x"},
        "risk_level": "medium",
        "description": "Writes a file",
        "reasoning": None,
        "allow_remember": True,
    },
    {"type": "client_tool_call", "execution_id": "e1", "tool_name": "ui_tool", "args": {}},
    {
        "type": "ask_user_required",
        "execution_id": "e1",
        "questions": [
            {
                "id": "q1",
                "text": "Quale?",
                "type": "radio",
                "options": ["a", "b"],
                "allow_free_text": False,
            },
        ],
    },
    {"type": "turn.started", "turn_id": "t1", "conversation_id": "c1"},
    {"type": "turn.llm_step", "turn_id": "t1", "step": 1},
    {
        "type": "tool.call",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "web_search",
        "args": {"q": "x"},
    },
    {
        "type": "tool.result",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "web_search",
        "success": True,
        "result": "ok",
    },
    {
        "type": "interaction.requested",
        "turn_id": "t1",
        "execution_id": "e1",
        "kind": "tool_confirmation",
        "tool_name": "write_file",
    },
    {
        "type": "interaction.resolved",
        "turn_id": "t1",
        "execution_id": "e1",
        "kind": "client_tool_call",
        "outcome": "failed",
    },
    {
        "type": "turn.usage",
        "turn_id": "t1",
        "step": 1,
        "input_tokens": 10,
        "output_tokens": 5,
        "tool_calls": 1,
        "max_steps": 24,
    },
    {
        "type": "turn.finished",
        "turn_id": "t1",
        "finish_reason": None,
        "input_tokens": 10,
        "output_tokens": 5,
        "steps": 1,
    },
    {"type": "agent.critic_invoked", "run_id": None, "step_index": 0, "source": "llm"},
    {"type": "agent.warning", "run_id": None, "code": "degenerated_output", "message": "..."},
]

REPRESENTATIVE_CLIENT_FRAMES: list[dict[str, Any]] = [
    {"type": "cancel"},
    {"type": "tool_confirmation_response", "execution_id": "e1", "approved": True},
    {
        "type": "tool_confirmation_response",
        "execution_id": "e1",
        "approved": True,
        "remember": "session",
    },
    {"type": "client_tool_result", "execution_id": "e1", "success": True, "result": "ok"},
    {"type": "client_tool_result", "execution_id": "e1", "success": False, "error": "nope"},
    {
        "type": "ask_user_response",
        "execution_id": "e1",
        "answers": [{"question_id": "q1", "selected": ["a"], "free_text": ""}],
    },
]


def test_chat_server_vocabulary_is_frozen() -> None:
    assert CHAT_SERVER_TYPES == EXPECTED_CHAT_SERVER_TYPES


def test_chat_client_vocabulary_is_frozen() -> None:
    assert CHAT_CLIENT_TYPES == EXPECTED_CHAT_CLIENT_TYPES


@pytest.mark.parametrize(
    "frame", REPRESENTATIVE_SERVER_FRAMES,
    ids=lambda f: f"{f['type']}-{REPRESENTATIVE_SERVER_FRAMES.index(f)}",
)
def test_representative_server_frames_validate(frame: dict[str, Any]) -> None:
    validate_chat_server(frame)


@pytest.mark.parametrize(
    "frame", REPRESENTATIVE_CLIENT_FRAMES,
    ids=lambda f: f"{f['type']}-{REPRESENTATIVE_CLIENT_FRAMES.index(f)}",
)
def test_representative_client_frames_validate(frame: dict[str, Any]) -> None:
    validate_chat_client(frame)


def test_user_message_has_no_type_discriminant() -> None:
    """A plain user message is the UNTAGGED chat frame (legacy wire shape)."""
    from backend.api.ws_schema.chat import WsUserMessage

    msg = WsUserMessage.model_validate({"content": "ciao", "conversation_id": "c1"})
    assert msg.content == "ciao"
    assert "type" not in WsUserMessage.model_fields


def test_unknown_chat_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_chat_server({"type": "usage", "input_tokens": 1, "output_tokens": 2})
```

(L'ultimo test pinna un fatto verificato: il frame `usage` dell'LLM è consumato in `direct_executor.py:423` e NON è parte del contratto chat.)

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run (da `backend/`): `pytest tests/contracts/test_ws_schema_chat.py -v`
Expected: ERROR con `ImportError` (manca `CHAT_SERVER_TYPES` / `backend.api.ws_schema.chat`).

- [ ] **Step 3: Implementare i modelli del canale chat**

Creare `backend/api/ws_schema/chat.py`:

```python
"""AL\\CE — Typed schema of the chat WebSocket channel (``/api/ws/chat``).

One Pydantic model per frame. Field shapes audited from the emit sites on
2026-06-11: LLM stream forwarding (``services/turn/direct_executor.py`` —
``usage`` and the LLM-level ``done`` are consumed internally and never
reach the client), tool loop (``tool_loop.py``/``pipeline.py``), turn
persistence (``api/routes/chat/_persist.py`` builds the final ``done``),
canonical turn events (``services/turn/events.py``), interaction frames
(``services/turn/channel.py`` ``_REQUEST_SPECS``), reflective executor.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from backend.api.ws_schema._base import ChatServerFrame, ClientFrame

RiskLevel = Literal["safe", "medium", "dangerous", "forbidden"]
InteractionKind = Literal["tool_confirmation", "client_tool_call", "ask_user"]
InteractionOutcome = Literal[
    "approved",
    "rejected",
    "answered",
    "executed",
    "timeout",
    "cancelled",
    "disconnected",
    "failed",
]
RememberChoice = Literal["none", "session", "persistent"]

# ---------------------------------------------------------------------------
# Legacy streaming (forwarded from the LLM stream)
# ---------------------------------------------------------------------------


class WsToken(ChatServerFrame):
    type: Literal["token"]
    content: str


class WsThinking(ChatServerFrame):
    type: Literal["thinking"]
    content: str


class WsToolCallFunction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: str


class WsToolCallStream(ChatServerFrame):
    """LLM requested a tool (raw stream forward, pre-execution)."""

    type: Literal["tool_call"]
    id: str
    function: WsToolCallFunction


class WsError(ChatServerFrame):
    type: Literal["error"]
    content: str


class WsDone(ChatServerFrame):
    """Final turn frame (built in chat ``_persist`` after the DB commit)."""

    type: Literal["done"]
    conversation_id: str
    message_id: str
    user_message_id: str
    finish_reason: str
    version_group_id: str | None = None
    version_index: int


# ---------------------------------------------------------------------------
# Tool loop
# ---------------------------------------------------------------------------


class WsToolExecutionStart(ChatServerFrame):
    type: Literal["tool_execution_start"]
    tool_name: str
    execution_id: str


class WsToolExecutionDone(ChatServerFrame):
    type: Literal["tool_execution_done"]
    tool_name: str
    result: str
    execution_id: str
    success: bool
    content_type: str | None = None
    artifact_id: str | None = None


class WsToolProgress(ChatServerFrame):
    """Incremental progress; tools merge arbitrary extra keys (extra=allow)."""

    model_config = ConfigDict(extra="allow")

    type: Literal["tool_progress"]
    tool_name: str
    execution_id: str
    phase: str | None = None
    label: str | None = None
    step: int | None = None
    total: int | None = None
    percent: float | None = None
    elapsed_s: float | None = None


class WsContextBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: int
    tools: int
    messages: int
    files: int
    tool_results: int
    other: int


class WsContextInfo(ChatServerFrame):
    type: Literal["context_info"]
    used: int
    available: int
    context_window: int
    percentage: float
    was_compressed: bool
    messages_summarized: int
    is_estimated: bool = False
    breakdown: WsContextBreakdown | None = None


class WsContextCompressionStart(ChatServerFrame):
    type: Literal["context_compression_start"]


class WsContextCompressionDone(ChatServerFrame):
    type: Literal["context_compression_done"]
    messages_summarized: int
    summary_message_id: str | None = None


class WsContextCompressionFailed(ChatServerFrame):
    type: Literal["context_compression_failed"]


class WsLlmRequery(ChatServerFrame):
    type: Literal["llm_requery"]
    iteration: int


class WsWarning(ChatServerFrame):
    type: Literal["warning"]
    content: str


# ---------------------------------------------------------------------------
# Interaction requests (round-trips driven by services/turn/channel.py)
# ---------------------------------------------------------------------------


class WsToolConfirmationRequired(ChatServerFrame):
    type: Literal["tool_confirmation_required"]
    execution_id: str
    tool_name: str
    args: dict[str, Any]
    risk_level: RiskLevel
    description: str
    reasoning: str | None = None
    allow_remember: bool = True


class WsClientToolCall(ChatServerFrame):
    """Delegate a UI-side tool execution to the connected client."""

    type: Literal["client_tool_call"]
    execution_id: str
    tool_name: str
    args: dict[str, Any]


class WsAskUserQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    type: Literal["radio", "checkbox"]
    options: list[str] = Field(default_factory=list)
    allow_free_text: bool = False


class WsAskUserRequired(ChatServerFrame):
    type: Literal["ask_user_required"]
    execution_id: str
    questions: list[WsAskUserQuestion]


# ---------------------------------------------------------------------------
# Canonical turn events (services/turn/events.py)
# ---------------------------------------------------------------------------


class WsTurnStarted(ChatServerFrame):
    type: Literal["turn.started"]
    turn_id: str
    conversation_id: str


class WsTurnLlmStep(ChatServerFrame):
    type: Literal["turn.llm_step"]
    turn_id: str
    step: int


class WsTurnToolCall(ChatServerFrame):
    type: Literal["tool.call"]
    turn_id: str
    execution_id: str
    tool_name: str
    args: dict[str, Any]


class WsTurnToolResult(ChatServerFrame):
    type: Literal["tool.result"]
    turn_id: str
    execution_id: str
    tool_name: str
    success: bool
    result: str
    content_type: str | None = None
    artifact_id: str | None = None


class WsInteractionRequested(ChatServerFrame):
    type: Literal["interaction.requested"]
    turn_id: str
    execution_id: str
    kind: InteractionKind
    tool_name: str | None = None


class WsInteractionResolved(ChatServerFrame):
    type: Literal["interaction.resolved"]
    turn_id: str
    execution_id: str
    kind: InteractionKind
    outcome: InteractionOutcome


class WsTurnUsage(ChatServerFrame):
    type: Literal["turn.usage"]
    turn_id: str
    step: int
    input_tokens: int
    output_tokens: int
    tool_calls: int
    max_steps: int


class WsTurnFinished(ChatServerFrame):
    type: Literal["turn.finished"]
    turn_id: str
    finish_reason: str | None = None
    input_tokens: int
    output_tokens: int
    steps: int


# ---------------------------------------------------------------------------
# Reflective executor
# ---------------------------------------------------------------------------


class WsAgentCriticInvoked(ChatServerFrame):
    type: Literal["agent.critic_invoked"]
    run_id: str | None = None
    step_index: int = 0
    source: str


class WsAgentWarning(ChatServerFrame):
    type: Literal["agent.warning"]
    run_id: str | None = None
    code: str
    message: str


# ---------------------------------------------------------------------------
# Client→server frames
# ---------------------------------------------------------------------------


class WsUserMessage(ClientFrame):
    """A plain user message — the UNTAGGED chat frame.

    Deliberately NOT part of :data:`ChatClientMessage`: the wire format has
    no ``type`` key (the channel pump treats any unrecognized frame as a
    user message). Exported as a named component for the FE send payload.
    """

    content: str
    conversation_id: str | None = None
    attachments: list[str] | None = None
    edit_message_id: str | None = None


class WsCancel(ClientFrame):
    type: Literal["cancel"]


class WsToolConfirmationResponse(ClientFrame):
    type: Literal["tool_confirmation_response"]
    execution_id: str
    approved: bool
    remember: RememberChoice = "none"


class WsClientToolResult(ClientFrame):
    type: Literal["client_tool_result"]
    execution_id: str
    success: bool = False
    result: str | list[Any] | dict[str, Any] | None = None
    error: str | None = None


class WsAskUserAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    selected: list[str] = Field(default_factory=list)
    free_text: str | None = None


class WsAskUserResponse(ClientFrame):
    type: Literal["ask_user_response"]
    execution_id: str
    answers: list[WsAskUserAnswer]


# ---------------------------------------------------------------------------
# Channel unions (discriminated on ``type``)
# ---------------------------------------------------------------------------

ChatServerMessage = Annotated[
    Union[
        WsToken,
        WsThinking,
        WsToolCallStream,
        WsError,
        WsDone,
        WsToolExecutionStart,
        WsToolExecutionDone,
        WsToolProgress,
        WsContextInfo,
        WsContextCompressionStart,
        WsContextCompressionDone,
        WsContextCompressionFailed,
        WsLlmRequery,
        WsWarning,
        WsToolConfirmationRequired,
        WsClientToolCall,
        WsAskUserRequired,
        WsTurnStarted,
        WsTurnLlmStep,
        WsTurnToolCall,
        WsTurnToolResult,
        WsInteractionRequested,
        WsInteractionResolved,
        WsTurnUsage,
        WsTurnFinished,
        WsAgentCriticInvoked,
        WsAgentWarning,
    ],
    Field(discriminator="type"),
]

ChatClientMessage = Annotated[
    Union[
        WsCancel,
        WsToolConfirmationResponse,
        WsClientToolResult,
        WsAskUserResponse,
    ],
    Field(discriminator="type"),
]
```

- [ ] **Step 4: Estendere `__init__.py`**

In `backend/api/ws_schema/__init__.py`:

1. Aggiungere dopo l'import da `events`:

```python
from backend.api.ws_schema.chat import (
    ChatClientMessage,
    ChatServerMessage,
    WsUserMessage,
)
```

2. Aggiungere dopo i due adapter events:

```python
_CHAT_SERVER_ADAPTER: TypeAdapter[Any] = TypeAdapter(ChatServerMessage)
_CHAT_CLIENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(ChatClientMessage)

CHAT_SERVER_TYPES: frozenset[str] = _union_member_types(ChatServerMessage)
CHAT_CLIENT_TYPES: frozenset[str] = _union_member_types(ChatClientMessage)
```

3. Estendere `WS_CONTRACT_ADAPTERS` a:

```python
WS_CONTRACT_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "ChatServerMessage": _CHAT_SERVER_ADAPTER,
    "ChatClientMessage": _CHAT_CLIENT_ADAPTER,
    "WsUserMessage": TypeAdapter(WsUserMessage),
    "EventsServerMessage": _EVENTS_SERVER_ADAPTER,
    "EventsClientMessage": _EVENTS_CLIENT_ADAPTER,
}
```

4. Aggiungere i validatori:

```python
def validate_chat_server(frame: dict[str, Any]) -> Any:
    """Validate a server→client chat frame; raises ``ValidationError``."""
    return _CHAT_SERVER_ADAPTER.validate_python(frame)


def validate_chat_client(frame: dict[str, Any]) -> Any:
    """Validate a client→server chat frame; raises ``ValidationError``."""
    return _CHAT_CLIENT_ADAPTER.validate_python(frame)
```

5. Estendere `__all__` con: `"CHAT_CLIENT_TYPES"`, `"CHAT_SERVER_TYPES"`, `"ChatClientMessage"`, `"ChatServerMessage"`, `"WsUserMessage"`, `"validate_chat_client"`, `"validate_chat_server"` (mantenere l'ordinamento alfabetico).

- [ ] **Step 5: Eseguire i test e verificare che passino**

Run (da `backend/`): `pytest tests/contracts/test_ws_schema_chat.py tests/contracts/test_ws_schema_events.py -v`
Expected: tutti PASS.

- [ ] **Step 6: Lint e typecheck**

Run (da `backend/`): `ruff check api/ws_schema/ tests/contracts/; mypy api/ws_schema/ tests/contracts/test_ws_schema_chat.py`
Expected: nessun errore.

- [ ] **Step 7: Commit**

```powershell
git add backend/api/ws_schema backend/tests/contracts/test_ws_schema_chat.py
git commit -m "feat(contracts): typed ws_schema for the chat channel (27 server + 4 client frames)"
```

---

### Task 5: Iniezione del contratto WS nell'export OpenAPI

Le unioni WS diventano components con nome nello stesso `openapi.json`; `openapi-typescript` le genera come unioni TS senza nuovi tool.

**Files:**
- Modify: `backend/api/openapi_export.py`
- Test: `backend/tests/contracts/test_openapi_export.py` (estendere)

- [ ] **Step 1: Estendere il test esistente (fallisce)**

Aggiungere in coda a `backend/tests/contracts/test_openapi_export.py`:

```python
def test_ws_contract_injected_as_components() -> None:
    """The WS channel unions ride the same OpenAPI document (spec §6)."""
    schema = build_schema()
    components = schema["components"]["schemas"]
    for union_name in (
        "ChatServerMessage",
        "ChatClientMessage",
        "WsUserMessage",
        "EventsServerMessage",
        "EventsClientMessage",
    ):
        assert union_name in components, union_name
    # Discriminated member schemas land as named components too.
    assert "WsToken" in components
    assert "WsCalendarChanged" in components
    # The discriminator survives so openapi-typescript emits a tagged union.
    assert components["EventsServerMessage"]["discriminator"]["propertyName"] == "type"
```

Run (da `backend/`): `pytest tests/contracts/test_openapi_export.py -v`
Expected: il nuovo test FAIL con `KeyError`/`AssertionError` (gli altri due restano PASS).

- [ ] **Step 2: Implementare l'iniezione**

In `backend/api/openapi_export.py`:

1. Aggiungere dopo `build_schema` (o prima di `main`):

```python
def _inject_ws_schemas(schema: dict[str, Any]) -> None:
    """Inject the WS channel unions into ``components.schemas``.

    The WS contract rides the same OpenAPI document so the existing
    ``openapi-typescript`` pipeline generates the TS unions with no extra
    tooling. Pydantic emits validation-mode JSON Schema (fields with
    defaults are optional — truthful about today's wire, where ``origin``
    is not emitted yet). A name collision with a REST component (or a
    mismatched duplicate between adapters) is a hard error: rename the
    Pydantic model rather than silently overwrite.
    """
    from backend.api.ws_schema import WS_CONTRACT_ADAPTERS

    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for union_name, adapter in WS_CONTRACT_ADAPTERS.items():
        sub = adapter.json_schema(
            ref_template="#/components/schemas/{model}",
        )
        for def_name, def_schema in sub.pop("$defs", {}).items():
            existing = components.get(def_name)
            if existing is not None and existing != def_schema:
                raise ValueError(
                    f"WS schema component collision: {def_name!r}",
                )
            components[def_name] = def_schema
        if union_name in components:
            raise ValueError(
                f"WS schema component collision: {union_name!r}",
            )
        components[union_name] = sub
```

2. In `build_schema`, sostituire:

```python
    app = create_app(testing=True)
    return app.openapi()
```

con:

```python
    app = create_app(testing=True)
    schema = app.openapi()
    _inject_ws_schemas(schema)
    return schema
```

3. Aggiornare la docstring di modulo: la frase sul contenuto deve menzionare che il documento contiene anche il contratto WS iniettato (una riga, es. aggiungere alla fine del primo paragrafo: `The exported document also carries the WS channel unions from backend/api/ws_schema as named components.`).

- [ ] **Step 3: Eseguire i test e verificare che passino**

Run (da `backend/`): `pytest tests/contracts/ -v`
Expected: tutti PASS (incluso il determinismo di `main` — l'iniezione è ordinata e `json.dumps(sort_keys=True)` la stabilizza).

- [ ] **Step 4: Lint e typecheck**

Run (da `backend/`): `ruff check api/openapi_export.py tests/contracts/test_openapi_export.py; mypy api/openapi_export.py tests/contracts/test_openapi_export.py`
Expected: nessun errore.

- [ ] **Step 5: Commit**

```powershell
git add backend/api/openapi_export.py backend/tests/contracts/test_openapi_export.py
git commit -m "feat(contracts): inject WS channel unions into the OpenAPI export"
```

---

### Task 6: Rigenerazione e consumo FE dei tipi WS generati

I file di tipi FE scritti a mano diventano re-export dei generati (stessa mossa del Task 4 di 1a). I nomi locali restano invariati: i consumatori non cambiano import.

**Files:**
- Regenerate: `frontend/src/renderer/src/types/generated/{openapi.json,api.d.ts}`
- Modify: `frontend/src/renderer/src/types/generated/index.ts`
- Modify: `frontend/src/renderer/src/types/tasks.ts`
- Modify: `frontend/src/renderer/src/types/planDocument.ts`
- Modify: `frontend/src/renderer/src/types/scope.ts`
- Modify: `frontend/src/renderer/src/types/permission.ts`
- Modify: `frontend/src/renderer/src/types/terminal.ts`
- Modify: `frontend/src/renderer/src/types/email.ts`
- Modify: `frontend/src/renderer/src/types/turn.ts`
- Modify: `frontend/src/renderer/src/types/chat.ts`

- [ ] **Step 1: Rigenerare i contratti**

Run: `.\scripts\gen-contracts.ps1`
Expected: `Contracts regenerated.`; in `api.d.ts` esistono `EventsServerMessage`, `ChatServerMessage`, `WsToken`, `WsCalendarChanged` dentro `components['schemas']`.

- [ ] **Step 2: Estendere l'alias module generato**

In `frontend/src/renderer/src/types/generated/index.ts`, aggiungere in coda:

```typescript
/** Discriminated unions of the two WS channels (generated from ws_schema). */
export type ChatServerMessage = ApiSchema<'ChatServerMessage'>
export type ChatClientMessage = ApiSchema<'ChatClientMessage'>
export type EventsServerMessage = ApiSchema<'EventsServerMessage'>
export type EventsClientMessage = ApiSchema<'EventsClientMessage'>
```

- [ ] **Step 3: Re-export nei file di dominio events**

In `frontend/src/renderer/src/types/tasks.ts` sostituire le interfacce `TaskStep` e `WsTasksUpdatedMessage` con:

```typescript
import type { ApiSchema } from './generated'

/** Generated from the backend WS contract — do not redefine locally. */
export type TaskStep = ApiSchema<'WsTaskStep'>
export type WsTasksUpdatedMessage = ApiSchema<'WsTasksUpdated'>
```

(`TasksResponse` resta scritto a mano: il burn-down REST è nelle fasi 2-6.)

In `frontend/src/renderer/src/types/planDocument.ts` sostituire l'interfaccia `WsPlanDocumentUpdatedMessage` con:

```typescript
import type { ApiSchema } from './generated'

/** Generated from the backend WS contract — do not redefine locally. */
export type WsPlanDocumentUpdatedMessage = ApiSchema<'WsPlanDocumentUpdated'>
```

In `frontend/src/renderer/src/types/scope.ts` sostituire l'interfaccia `WsScopeUpdatedMessage` con (l'import `ApiSchema` esiste già dalla 1a):

```typescript
/** Generated from the backend WS contract — do not redefine locally. */
export type WsScopeUpdatedMessage = ApiSchema<'WsScopeUpdated'>
```

In `frontend/src/renderer/src/types/permission.ts` sostituire l'interfaccia `WsPermissionModeUpdatedMessage` con (idem, import già presente):

```typescript
/** Generated from the backend WS contract — do not redefine locally. */
export type WsPermissionModeUpdatedMessage = ApiSchema<'WsPermissionModeUpdated'>
```

In `frontend/src/renderer/src/types/terminal.ts` sostituire `TerminalSession` e le cinque interfacce `WsTerminal*Message` + i due frame di controllo con:

```typescript
import type { ApiSchema } from './generated'

/** Generated from the backend WS contract — do not redefine locally. */
export type TerminalSession = ApiSchema<'WsTerminalSession'>

// --- Events-WS frames (server → client) ------------------------------------
export type WsTerminalSessionOpenedMessage = ApiSchema<'WsTerminalSessionOpened'>
export type WsTerminalOutputMessage = ApiSchema<'WsTerminalOutput'>
export type WsTerminalClosedMessage = ApiSchema<'WsTerminalClosed'>
export type WsTerminalRenamedMessage = ApiSchema<'WsTerminalRenamed'>
export type WsTerminalAssignedMessage = ApiSchema<'WsTerminalAssigned'>

// --- Control frames (client → server, over the events WS) ------------------
export type WsTerminalInputFrame = ApiSchema<'WsTerminalInput'>
export type WsTerminalResizeFrame = ApiSchema<'WsTerminalResize'>
```

(le interfacce REST `TerminalListResponse`/`TerminalCreateRequest`/`TerminalUpdateRequest` restano invariate).

In `frontend/src/renderer/src/types/email.ts` sostituire `WsEmailReceivedMessage` e `WsEmailSentMessage` con:

```typescript
import type { ApiSchema } from './generated'

/** Generated from the backend WS contract — do not redefine locally. */
export type WsEmailReceivedMessage = ApiSchema<'WsEmailReceived'>
export type WsEmailSentMessage = ApiSchema<'WsEmailSent'>
```

- [ ] **Step 4: Re-export dei tipi canonici di turno**

In `frontend/src/renderer/src/types/turn.ts` sostituire le otto interfacce `Ws*Message` (e i tipi alias `InteractionKind`/`InteractionOutcome` se definiti localmente) con re-export; mantenere INVARIATI i view-model camelCase presenti nel file:

```typescript
import type { ApiSchema } from './generated'

/** Generated from the backend WS contract — do not redefine locally. */
export type WsTurnStartedMessage = ApiSchema<'WsTurnStarted'>
export type WsTurnLlmStepMessage = ApiSchema<'WsTurnLlmStep'>
export type WsToolCallMessage = ApiSchema<'WsTurnToolCall'>
export type WsToolResultMessage = ApiSchema<'WsTurnToolResult'>
export type WsInteractionRequestedMessage = ApiSchema<'WsInteractionRequested'>
export type WsInteractionResolvedMessage = ApiSchema<'WsInteractionResolved'>
export type WsTurnUsageMessage = ApiSchema<'WsTurnUsage'>
export type WsTurnFinishedMessage = ApiSchema<'WsTurnFinished'>
export type InteractionKind = WsInteractionRequestedMessage['kind']
```

(Se il file definiva anche un tipo per l'outcome, ricavarlo allo stesso modo: `WsInteractionResolvedMessage['outcome']`.)

- [ ] **Step 5: Re-export dei tipi chat**

In `frontend/src/renderer/src/types/chat.ts`:

1. Aggiungere in testa al blocco WS (prima di `WsSendPayload`):

```typescript
import type { ApiSchema, ChatServerMessage } from './generated'
```

2. Sostituire le sedici interfacce `Ws*Message` server→client (`WsTokenMessage`, `WsThinkingMessage`, `WsDoneMessage`, `WsErrorMessage`, `WsToolExecutionStartMessage`, `WsToolExecutionDoneMessage`, `WsToolConfirmationRequiredMessage`, `WsAskUserRequiredMessage`, `WsLlmRequeryMessage`, `WsWarningMessage`, `WsContextInfoMessage`, `WsContextCompressionStartMessage`, `WsContextCompressionDoneMessage`, `WsContextCompressionFailedMessage`, `WsToolCallMessage`, `WsToolProgressMessage`) e i payload client (`WsCancelPayload`, `WsToolConfirmationResponsePayload`, `WsAskUserResponsePayload`, `WsSendPayload`) e i tipi di supporto (`RememberChoice`, `AskUserQuestion`, `AskUserAnswer`, `ContextBreakdown`) con:

```typescript
/** Generated from the backend WS contract — do not redefine locally. */
export type WsSendPayload = ApiSchema<'WsUserMessage'>
export type WsTokenMessage = ApiSchema<'WsToken'>
export type WsThinkingMessage = ApiSchema<'WsThinking'>
export type WsDoneMessage = ApiSchema<'WsDone'>
export type WsCancelPayload = ApiSchema<'WsCancel'>
export type WsErrorMessage = ApiSchema<'WsError'>
export type WsToolCallMessage = ApiSchema<'WsToolCallStream'>
export type WsToolExecutionStartMessage = ApiSchema<'WsToolExecutionStart'>
export type WsToolExecutionDoneMessage = ApiSchema<'WsToolExecutionDone'>
export type WsToolProgressMessage = ApiSchema<'WsToolProgress'>
export type RememberChoice = NonNullable<
  ApiSchema<'WsToolConfirmationResponse'>['remember']
>
export type WsToolConfirmationRequiredMessage = ApiSchema<'WsToolConfirmationRequired'>
export type WsToolConfirmationResponsePayload = ApiSchema<'WsToolConfirmationResponse'>
export type AskUserQuestion = ApiSchema<'WsAskUserQuestion'>
export type WsAskUserRequiredMessage = ApiSchema<'WsAskUserRequired'>
export type AskUserAnswer = ApiSchema<'WsAskUserAnswer'>
export type WsAskUserResponsePayload = ApiSchema<'WsAskUserResponse'>
export type WsLlmRequeryMessage = ApiSchema<'WsLlmRequery'>
export type WsWarningMessage = ApiSchema<'WsWarning'>
export type ContextBreakdown = ApiSchema<'WsContextBreakdown'>
export type WsContextInfoMessage = ApiSchema<'WsContextInfo'>
export type WsContextCompressionStartMessage = ApiSchema<'WsContextCompressionStart'>
export type WsContextCompressionDoneMessage = ApiSchema<'WsContextCompressionDone'>
export type WsContextCompressionFailedMessage = ApiSchema<'WsContextCompressionFailed'>
```

3. Sostituire la definizione dell'unione `WsMessage` (righe ~483-499) con:

```typescript
/** Discriminated union of all server→client chat frames (generated). */
export type WsMessage = ChatServerMessage
```

4. NON toccare i tipi non-WS del file (payload CAD/chart/whiteboard, `ToolExecution`, `ConfirmationRequest`, `AskUserRequest`, `ContextInfo`, export/import, ecc.).

- [ ] **Step 6: Typecheck e fix dei drift**

Run (da `frontend/`): `npm run typecheck`
Expected: probabili errori nei consumatori (es. campi ora `string | null` invece di `string | undefined`, `version_index` ora obbligatorio, accessi a campi su unioni più ampie). Sono drift veri trovati dal compilatore: **allineare i consumatori al contratto generato, non viceversa**. Tipici interventi: narrowing con `?? undefined`, guardie sul discriminante prima dell'accesso, aggiornare le firme degli store (`servicesStore.onServiceStatus` ecc.) ai tipi generati. Iterare fino a exit 0. Se un errore rivela un VERO disallineamento di contratto backend (campo che il BE non manda), fermarsi e segnalarlo.

- [ ] **Step 7: Lint sui file toccati e test FE**

Run (da `frontend/`): `npx eslint src/renderer/src/types/ src/renderer/src/composables/ src/renderer/src/stores/; npm run test`
Expected: exit 0; vitest verde (gli spec di `agentRun` usano i tipi di `turn.ts`).

- [ ] **Step 8: Commit, poi gate di staleness**

```powershell
git add frontend/src/renderer/src/types frontend/src/renderer/src/composables frontend/src/renderer/src/stores frontend/src/renderer/src/components
git commit -m "feat(contracts): FE consumes generated WS types (chat + events channels)"
.\scripts\check-contracts.ps1
```

Expected: commit creato; poi `Contracts are up to date.` (Aggiungere al commit ogni altro file FE toccato dai fix di drift dello Step 6.)

---

### Task 7: Dispatcher tipizzato esaustivo per il canale events

`useEventsWebSocket.ts` passa dalla catena if/else a una mappa esaustiva `type → handler`: un tipo non gestito è un errore di compilazione (spec §6).

**Files:**
- Modify: `frontend/src/renderer/src/composables/useEventsWebSocket.ts`

- [ ] **Step 1: Tipizzare il modulo e costruire la mappa**

In `frontend/src/renderer/src/composables/useEventsWebSocket.ts`:

1. Aggiungere agli import:

```typescript
import type { EventsServerMessage } from '../types/generated'
```

2. Aggiungere sotto gli import (livello modulo):

```typescript
/**
 * Exhaustive map of events-WS frame types to handlers. Adding a frame to
 * the backend ws_schema and regenerating the contracts makes this object
 * FAIL TO COMPILE until the new frame is handled (or explicitly no-op'd).
 */
type EventsHandlerMap = {
  [K in EventsServerMessage['type']]: (
    msg: Extract<EventsServerMessage, { type: K }>
  ) => void
}
```

3. Dentro `useEventsWebSocket()`, dopo le dichiarazioni degli store, aggiungere:

```typescript
  const noop = (): void => {}
  const handlers: EventsHandlerMap = {
    pong: noop,
    heartbeat: noop,
    'calendar.changed': () => void calendarStore.refresh(),
    'mcp.server.connected': () => void mcpStore.loadServers(),
    'mcp.server.disconnected': () => void mcpStore.loadServers(),
    'email.received': (msg) => emailStore.handleEmailReceived(msg.folder ?? 'INBOX'),
    'email.sent': noop,
    'note.created': noop,
    'note.updated': noop,
    'note.deleted': noop,
    'service.status': (msg) => servicesStore.onServiceStatus(msg),
    'service.model_download_progress': (msg) => servicesStore.onDownloadProgress(msg),
    'knowledge.status': (msg) => servicesStore.onKnowledgeStatus(msg),
    'artifact.created': (msg) => void artifactsStore.fetchById(msg.artifact_id),
    'tasks.updated': (msg) => tasksStore.applyTasksUpdated(msg),
    'plan_document.updated': (msg) => planDocumentStore.applyPlanDocumentUpdated(msg),
    'scope.updated': (msg) => scopeStore.applyScopeUpdated(msg),
    'permission_mode.updated': (msg) => permissionModeStore.applyModeUpdated(msg),
    'config.changed': noop,
    'terminal.session_opened': (msg) => terminalStore.applySessionOpened(msg),
    'terminal.output': (msg) => terminalStore.applyOutput(msg),
    'terminal.closed': (msg) => terminalStore.applyClosed(msg),
    'terminal.renamed': (msg) => terminalStore.applyRenamed(msg),
    'terminal.assigned': (msg) => terminalStore.applyAssigned(msg),
  }
```

4. Sostituire l'intero corpo di `ws.onmessage` (la catena if/else, righe ~105-183) con:

```typescript
    ws.onmessage = (event: MessageEvent): void => {
      let data: EventsServerMessage
      try {
        data = JSON.parse(event.data as string) as EventsServerMessage
      } catch {
        console.warn('[ALICE Events WS] Failed to parse message')
        return
      }
      const handler = handlers[data.type] as
        | ((msg: EventsServerMessage) => void)
        | undefined
      if (handler) {
        handler(data)
      } else {
        // Runtime safety net for frames newer than the bundled contract.
        console.warn('[ALICE Events WS] Unhandled frame type:', (data as { type?: string }).type)
      }
    }
```

5. Rimuovere gli import dei tipi `Ws*Message` divenuti inutilizzati nel file (il dispatcher passa `msg` già narrowed; gli store tipizzano i parametri).

- [ ] **Step 2: Verifica di esaustività (il typecheck è il test)**

Run (da `frontend/`): `npm run typecheck`
Expected: exit 0. Controprova dell'esaustività: commentare temporaneamente la riga `'email.sent': noop,` → `npm run typecheck` DEVE fallire con "Property 'email.sent' is missing"; ripristinare la riga e riverificare exit 0.

Se gli handler degli store hanno firme incompatibili coi tipi generati (es. `onServiceStatus` si aspetta un tipo locale), aggiornare la firma dello store al tipo generato — mai cast `as` per zittire.

- [ ] **Step 3: Lint sui file toccati**

Run (da `frontend/`): `npx eslint src/renderer/src/composables/useEventsWebSocket.ts src/renderer/src/stores/`
Expected: exit 0.

- [ ] **Step 4: Commit**

```powershell
git add frontend/src/renderer/src/composables/useEventsWebSocket.ts frontend/src/renderer/src/stores
git commit -m "feat(fe): exhaustive typed dispatcher for the events WebSocket"
```

---

### Task 8: Wire guard runtime (validazione outbound opzionale)

Difesa in profondità oltre i test: i chokepoint di invio validano i frame in uscita contro lo schema. In produzione la violazione è un `logger.warning`; sotto pytest (env `ALICE_WS_STRICT_CONTRACTS=1`) è un raise. Il validator è **iniettato per DI** dai layer `api`/composition-root: `services` non importa mai `api` (spec §4).

Limiti dichiarati (non nasconderli in review): molti emettitori del canale events passano per callback "best-effort, never raises" (es. `permission_mode_service._emit_event`) o per il bus con `return_exceptions=True` — lì il raise strict viene assorbito e resta solo il log. L'enforcement primario sono i test di contratto dei Task 3-4; il guard aggiunge visibilità runtime e fallisce davvero nei test d'integrazione che attraversano i sink di produzione.

**Files:**
- Create: `backend/api/ws_schema/guard.py`
- Modify: `backend/services/ws_connection_manager.py`
- Modify: `backend/services/turn/sink.py` (`WebSocketEventSink.__init__`/`send`)
- Modify: `backend/services/turn/channel.py` (`WebSocketInteractionChannel.__init__`/`_send`)
- Modify: `backend/api/routes/chat/ws.py:107,164`
- Modify: `backend/core/app.py:529-531`
- Modify: `backend/tests/conftest.py` (strict env)
- Test: `backend/tests/contracts/test_ws_guard.py`

- [ ] **Step 1: Scrivere il test che fallisce**

Creare `backend/tests/contracts/test_ws_guard.py`:

```python
"""Contract tests: the runtime WS wire guard (warn in prod, raise in tests)."""

from __future__ import annotations

import pytest
from backend.api.ws_schema.guard import (
    WsContractViolation,
    chat_frame_validator,
    events_frame_validator,
)


def test_valid_frames_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALICE_WS_STRICT_CONTRACTS", "1")
    events_frame_validator({"type": "heartbeat"})
    chat_frame_validator({"type": "token", "content": "x"})


def test_strict_mode_raises_on_unknown_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALICE_WS_STRICT_CONTRACTS", "1")
    with pytest.raises(WsContractViolation):
        events_frame_validator({"type": "no.such.event"})


def test_strict_mode_raises_on_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALICE_WS_STRICT_CONTRACTS", "1")
    with pytest.raises(WsContractViolation):
        chat_frame_validator({"type": "token"})  # missing content


def test_lax_mode_only_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALICE_WS_STRICT_CONTRACTS", raising=False)
    events_frame_validator({"type": "no.such.event"})  # must not raise
```

Run (da `backend/`): `pytest tests/contracts/test_ws_guard.py -v`
Expected: ERROR con `ModuleNotFoundError` su `backend.api.ws_schema.guard`.

- [ ] **Step 2: Implementare il guard**

Creare `backend/api/ws_schema/guard.py`:

```python
"""AL\\CE — Runtime wire guard for outbound WS frames.

Validates outgoing frames against the typed contract. Outside tests a
violation only logs a warning (a malformed push must never take down a
turn); under ``ALICE_WS_STRICT_CONTRACTS=1`` (set by the test suite) it
raises so drift fails loudly.

The validators are plain callables meant to be INJECTED into the send
chokepoints (``WSConnectionManager``, ``WebSocketEventSink``,
``WebSocketInteractionChannel``) by the api layer / composition root —
``services`` modules must never import this package (spec §4).
"""

from __future__ import annotations

import os
from typing import Any, Literal

from loguru import logger
from pydantic import ValidationError

from backend.api.ws_schema import validate_chat_server, validate_events_server

_STRICT_ENV = "ALICE_WS_STRICT_CONTRACTS"


class WsContractViolation(AssertionError):
    """An outbound WS frame does not match the typed contract."""


def _validate(channel: Literal["chat", "events"], frame: dict[str, Any]) -> None:
    try:
        if channel == "chat":
            validate_chat_server(frame)
        else:
            validate_events_server(frame)
    except ValidationError as exc:
        message = f"WS contract violation on '{channel}' channel: {exc}"
        if os.environ.get(_STRICT_ENV) == "1":
            raise WsContractViolation(message) from exc
        logger.warning(message)


def chat_frame_validator(frame: dict[str, Any]) -> None:
    """Validate a server→client chat frame (inject into chat send paths)."""
    _validate("chat", frame)


def events_frame_validator(frame: dict[str, Any]) -> None:
    """Validate a server→client events frame (inject into the WS manager)."""
    _validate("events", frame)


__all__ = [
    "WsContractViolation",
    "chat_frame_validator",
    "events_frame_validator",
]
```

- [ ] **Step 3: Eseguire il test del guard**

Run (da `backend/`): `pytest tests/contracts/test_ws_guard.py -v`
Expected: 4 PASS.

- [ ] **Step 4: Punto di aggancio — WSConnectionManager (events)**

In `backend/services/ws_connection_manager.py`:

1. In `__init__`, aggiungere:

```python
        self._frame_validator: Callable[[dict[str, Any]], None] | None = None
```

(aggiungere `Callable` all'import da `typing` o `collections.abc` secondo lo stile del file).

2. Aggiungere il setter dopo `__init__`:

```python
    def set_frame_validator(
        self, validator: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        """Install an outbound frame validator (injected by the app wiring).

        The manager itself stays contract-agnostic: ``services`` must not
        import ``backend.api.ws_schema`` (layering, spec §4).
        """
        self._frame_validator = validator
```

3. In testa a `broadcast` (prima dello snapshot delle connessioni):

```python
        if self._frame_validator is not None:
            self._frame_validator(event)
```

4. In `backend/core/app.py`, dopo la riga 529-530 (`ws_connection_manager = WSConnectionManager()` / assegnazione a ctx), aggiungere:

```python
    from backend.api.ws_schema.guard import events_frame_validator

    ws_connection_manager.set_frame_validator(events_frame_validator)
```

- [ ] **Step 5: Punto di aggancio — sink e channel (chat)**

In `backend/services/turn/sink.py`, classe `WebSocketEventSink`:

1. Sostituire `__init__`:

```python
    def __init__(
        self,
        ws: WebSocket,
        frame_validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._ws = ws
        self._closed = False
        self._validate = frame_validator
```

(aggiungere `from typing import ... Callable` o `collections.abc.Callable` coerente col file; aggiornare la docstring della classe: nuovo arg `frame_validator`, iniettato dal layer api.)

2. In `send`, prima del `try` di invio:

```python
        if self._validate is not None:
            self._validate(event)
```

In `backend/services/turn/channel.py`, classe `WebSocketInteractionChannel`:

3. Sostituire `__init__` (riga ~142) aggiungendo il parametro e l'attributo:

```python
    def __init__(
        self,
        ws: WebSocket,
        frame_validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._ws = ws
        self._validate = frame_validator
        ...
```

(lasciare invariato il resto del corpo; aggiornare la docstring con il nuovo arg).

4. Nel metodo `_send` (riga ~358, firma `async def _send(self, frame: dict[str, Any]) -> bool:`), aggiungere come prima istruzione del corpo, prima del `from fastapi import WebSocketDisconnect`:

```python
        if self._validate is not None:
            self._validate(frame)
```

In `backend/api/routes/chat/ws.py`:

5. Aggiungere all'import block:

```python
from backend.api.ws_schema.guard import chat_frame_validator
```

6. Riga ~107: `channel = WebSocketInteractionChannel(websocket)` → `channel = WebSocketInteractionChannel(websocket, frame_validator=chat_frame_validator)`
7. Riga ~164: `sink = WebSocketEventSink(websocket)` → `sink = WebSocketEventSink(websocket, frame_validator=chat_frame_validator)`

- [ ] **Step 6: Strict mode nella suite**

In `backend/tests/conftest.py`, aggiungere subito dopo gli import di modulo (prima di qualunque fixture):

```python
# WS wire guard: violations raise inside the test suite (warn-only in prod).
os.environ.setdefault("ALICE_WS_STRICT_CONTRACTS", "1")
```

(aggiungere `import os` se assente).

- [ ] **Step 7: Test mirati dei moduli toccati**

Run (da `backend/`): `pytest tests/contracts/ tests/test_interaction_channel.py tests/test_tool_loop.py -v`
Expected: tutti PASS. Se un test fallisce per una violazione strict, è un frame reale fuori contratto: correggere il MODELLO se l'inventario era incompleto (aggiornando anche il vocabolario congelato e questo piano), oppure fermarsi e segnalare se l'emettitore è buggato.

- [ ] **Step 8: Lint e typecheck**

Run (da `backend/`): `ruff check api/ws_schema/guard.py services/ws_connection_manager.py services/turn/sink.py services/turn/channel.py api/routes/chat/ws.py tests/contracts/test_ws_guard.py; mypy api/ws_schema/guard.py services/ws_connection_manager.py services/turn/sink.py services/turn/channel.py tests/contracts/test_ws_guard.py`
Expected: nessun errore nuovo (eventuali errori pre-esistenti dei file `services/` vanno lasciati, non corretti qui: ruff/mypy scoped valgono per le RIGHE toccate).

- [ ] **Step 9: Commit**

```powershell
git add backend/api/ws_schema/guard.py backend/services/ws_connection_manager.py backend/services/turn/sink.py backend/services/turn/channel.py backend/api/routes/chat/ws.py backend/core/app.py backend/tests/conftest.py backend/tests/contracts/test_ws_guard.py
git commit -m "feat(contracts): runtime WS wire guard - DI-injected validators, strict in tests"
```

---

### Task 9: Documentazione e verifica finale

**Files:**
- Modify: `CLAUDE.md` (sezione Conventions)

- [ ] **Step 0: Aggiornare l'handoff stale**

In `docs/superpowers/handoffs/2026-06-11-risanamento-handoff.md`: la riga 19 ("oggi convivono `calendar_changed` e `mcp.server.connected`") e la riga 31 (inventario con `calendar_changed`) sono diventate false col Task 2 — aggiornare entrambe a `calendar.changed` con nota "(rinominato in 1b)".

- [ ] **Step 1: Aggiornare la convenzione contratti in CLAUDE.md**

In `CLAUDE.md`, sezione `## Conventions`, sostituire il bullet che inizia con `- **Contracts are generated**:` con:

```markdown
- **Contracts are generated**: new/changed REST endpoints must declare a Pydantic `response_model` (ratchet test in `backend/tests/contracts/`); every WebSocket frame on both channels is a Pydantic model in `backend/api/ws_schema/` (flat envelope: `type` discriminant + `origin` + `correlation_id?`; frozen vocabulary tests in `backend/tests/contracts/`). Any contract change requires regenerating (`.\scripts\gen-contracts.ps1`). Files in `frontend/src/renderer/src/types/generated/` are build artifacts — never edit them by hand (except `index.ts`) and never hand-merge them on conflicts: regenerate instead. The events-WS frontend dispatcher (`useEventsWebSocket.ts`) is an exhaustive `type → handler` map: adding a frame without handling it is a compile error. CI runs these gates in `.github/workflows/contracts.yml` (codegen pinned via `npm ci`).
```

- [ ] **Step 2: Verifica finale completa**

Nota: la suite backend completa resta impraticabile (difetto pre-esistente della fixture `app`, ~25s di setup per test, tracciato come task separato); la verifica usa i test mirati.

```powershell
cd backend; ..\.venv\Scripts\python.exe -m pytest tests/contracts/ tests/test_interaction_channel.py tests/test_tool_loop.py -v   # Expected: tutti PASS
cd backend; ..\.venv\Scripts\python.exe -m ruff check api/ws_schema/ api/openapi_export.py tests/contracts/
cd backend; ..\.venv\Scripts\python.exe -m mypy api/ws_schema/ api/openapi_export.py tests/contracts/
.\scripts\check-contracts.ps1         # Expected: "Contracts are up to date."
cd frontend; npm run typecheck        # Expected: exit 0
cd frontend; npm run test             # Expected: vitest verde
```

- [ ] **Step 3: Commit**

```powershell
git add CLAUDE.md
git commit -m "docs: WS contract conventions (ws_schema, exhaustive dispatcher, CI gates)"
```

---

## Criteri di uscita della fase (dalla spec §9)

1. Test mirati backend verdi (`tests/contracts/` + canali/domini toccati), `npm run typecheck` e `npm run test` verdi.
2. `.\scripts\check-contracts.ps1` verde su working tree pulito.
3. App avviabile (`.\scripts\start-dev.ps1`) e feature esemplari funzionanti end-to-end: (a) un evento events (es. cambio permission mode da Horizon) arriva e aggiorna la UI attraverso il dispatcher tipizzato; (b) un turno chat con tool streamma normalmente (il payload sul filo è invariato: verifica di regressione).
4. Enforcement consegnato (§9): vocabolari congelati + frame rappresentativi validati + wire guard strict nei test + dispatcher FE esaustivo + CI minima che esegue i gate.

## Fuori scope / backlog per le fasi successive

- **Emissione di `origin` sul filo**: i modelli lo dichiarano (default), gli emettitori non lo mandano ancora; la compilazione degli emettitori sui modelli (costruire `WsX(...)` invece di dict) è burn-down delle fasi 2-6, dominio per dominio.
- **`services/ws.ts` (canale chat FE)** resta un emitter string-keyed: il dispatcher tipizzato del canale chat ha senso insieme al rework Horizon (Fase 6).
- **`correlation_id`** è riservato al Command Layer (Fase 7); nessun consumo in 1b.
- Request-side enum su `PermissionModeUpdateRequest.mode`; `AgentTier` duplicato in `types/settings.ts:171`; burn-down baseline ratchet REST (94 voci) — invariati dal backlog 1a.
- **Il plugin calendar non emette `calendar.changed`** (finding review Task 2, pre-esistente): i tool LLM `create_event`/`update_event`/`delete_event` del plugin mutano la stessa tabella delle route REST ma non broadcastano — le modifiche agent-driven arrivano alla UI solo via polling. Da chiudere quando si tocca il dominio calendar (principio §4: stessa implementazione per route e tool).
- **Stabilità del gate di freshness vs dipendenze backend non pinnate** (finding review Task 1): `openapi.json` dipende dalle versioni di fastapi/pydantic risolte all'install (`>=`, nessun lockfile); un major upgrade può rendere "stale" gli artefatti su ogni PR. Valutare constraints file / parità di versione Python (CI 3.11 vs dev 3.13) quando il gate inizia a flappare.
