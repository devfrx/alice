# Fase 8 — Fondamenta Jarvis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Posare i punti di estensione agentici (spec §8): `TriggerService` (turni autonomi da schedule/eventi bus/manual-hotword, filtro anti-eco su `origin=agent`), `AttentionService` (punto unico e disattivabile dell'iniziativa verso l'utente), task in background osservabili (eventi tipizzati + store FE), voce e subagent ricondotti alla stessa policy di gating del turno normale. Interfacce, non implementazioni ricche.

**Architecture:** Tre nuovi service kernel in `backend/services/` (`background_tasks.py`, `attention_service.py`, `trigger_service.py`) cablati in un nuovo stage bootstrap `stage_jarvis` (decimo, ultimo). Un turno autonomo È un turno normale: `run_headless_turn` (api layer, iniettato nel TriggerService dal composition root) riusa `TurnAssembler` (reso `websocket`-optional) + `create_turn_executor` + `_persist_final_turn`, con `NullEventSink` e `HeadlessInteractionChannel` (ogni richiesta interattiva → `None` → esito pulito, filosofia fase 7). L'osservabilità viaggia su due nuovi frame events-WS (`background_task.updated`, `attention.raised`) emessi via bus (`AliceEvent`) e bridgiati in `stage_surfaces`. Il subagent smette di bypassare il gate: ogni sua tool-call consulta `PermissionService` (nuovo metodo `explain_denial`, conferma = negazione pulita in contesti headless). La voce attiva il seam morto `agent.voice.max_tools` via campo per-messaggio `source` su `WsUserMessage`.

**Tech Stack:** FastAPI + Pydantic (ws_schema), pipeline contratti esistente, asyncio puro (NESSUNA nuova dipendenza — niente APScheduler), Vue 3 + Pinia, vitest, pytest.

**Branch:** `arch/fase8-fondamenta-jarvis` (figlio di `main` @ `5b0cb8b`, già creato).

---

## Contesto e vincoli per l'implementatore (leggere PRIMA di ogni task)

- **Spec normativa**: `docs/superpowers/specs/2026-06-10-risanamento-architetturale-design.md` §8 (righe 177-191) + principio §4.5 («Autonomia sempre dentro i guardrail: nessun percorso privilegiato»).
- **Convenzioni Python**: type hints ovunque, `async def` per I/O, `loguru.logger`, line length 100, Google docstrings (inglese). **Convenzioni TS**: `<script setup lang="ts">`, no `any`, tipi generati mai editati a mano (eccetto `types/generated/index.ts`).
- **Comandi** (PowerShell 5.1, NIENTE `&&`):
  - pytest: da `backend/` → `..\.venv\Scripts\python.exe -m pytest tests/<file> -v`
  - lint-imports: dalla REPO ROOT → `.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml`
  - ruff (scoped sui file toccati): da `backend/` → `..\.venv\Scripts\ruff.exe check <files>`
  - FE: da `frontend/` → `npm run typecheck`, `npm run lint`, `npm test` (NO `npm install`/`npm ci`)
  - regen contratti: dalla REPO ROOT → `.\scripts\gen-contracts.ps1` (SOLO nel Task 10)
- **Gotchas ereditati** (handoff 2026-07-11): suite backend completa impraticabile (test mirati + `tests/contracts/`); `ToolResult.error()` riempie `error_message`, NON `content`; `test_plugins_enabled_list` è rosso ereditato (21 vs 20, non è una regressione); `git ls-files --eol` PRIMA e DOPO ogni commit (flip EOL = incidente ricorrente); mai cmdlet PowerShell su file non-ASCII; `check-contracts.ps1` solo DOPO il commit (untracked = dirty); file "modified since read" → ri-Read prima di Edit.
- **Layering (import-linter)**: services ↛ api e services ↛ plugins (i tre nuovi service NON importano `ws_schema` né plugin: emettono dict raw sul bus, il bridge in `surfaces.py` li trasforma in frame); plugins possono usare i servizi SOLO via `ctx` duck-typed (`getattr`), mai import diretto di classi services; il turn-runner headless vive in api e viene iniettato dal bootstrap (eccezione sancita `backend.core.bootstrap.* -> backend.api.**`).
- **EventBus**: il metodo è `emit(event_name, **kwargs)` (NON `publish`); handler `async def h(**kwargs)`; `subscribe(name, handler)` accetta `str | AliceEvent`.
- Commit convenzionali con trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. MAI push.

## Decisioni di design (registrate qui, non rilitigare durante l'implementazione)

1. **Tre service kernel in `services/`, campi `Any` in `PlatformServices`** (stesso schema minimalista di `command_bridge_service` in `WorkspaceServices`): niente Protocol dedicati in fase 8 (evita cicli core→services); property deleganti in `context.py` + `FLAT_FIELDS`.
2. **Turno autonomo = turno normale** (spec §8): `run_headless_turn` in `backend/api/routes/chat/headless.py` riusa `TurnAssembler` + executor + `_persist_final_turn` — stessa pipeline, stesso permission mode e scope della conversazione. Il seam vive in api perché l'assembly è in api (spostarlo in services = backlog); il TriggerService lo riceve come callable iniettato da `stage_jarvis`.
3. **Superfici mancanti = esiti puliti** (filosofia fase 7): `NullEventSink` scarta gli eventi del turno (l'osservabilità viaggia sui background task), `HeadlessInteractionChannel.request(...)` ritorna sempre `None` → i middleware collassano già a conferma-rifiutata/ask_user-senza-risposta. I tool `client_execution` vengono FILTRATI dal `TurnInput` headless (nessuna UI dove eseguirli).
4. **NESSUNA nuova dipendenza**: schedule = interval loop asyncio (precedente `TimerManager`/calendar reminder loop). Cron/RRULE ricchi, persistenza dei trigger e superficie di registrazione (tool/REST) = backlog post-risanamento.
5. **Anti-eco (spec §7/§8)**: si posa ORA la convenzione del kwarg `origin` sugli eventi bus; i trigger `kind="event"` ignorano di default gli eventi con `origin == "agent"` (`ignore_agent_origin=True` su `TriggerSpec`). Hotword = futuro chiamante di `fire()` (`kind="manual"`): nessun servizio di detection in fase 8.
6. **Osservabilità unificata**: ogni turno autonomo E ogni subagent diventano un background task (`BackgroundTaskService`, in-memory, azzerabile — NON una job-queue persistente). Frame `background_task.updated` porta lo snapshot COMPLETO (fold diretto nello store FE, pattern `tasks.updated`). Niente route REST in fase 8 (idratazione WS-only) = backlog.
7. **AttentionService v1**: enum completo `interrupt|notify|queue|drop` (vocabolario spec), policy minima: disabled → DROP, cooldown (non-urgent) → DROP, altrimenti NOTIFY + evento `attention.raised` → toast FE (`useToast`). `interrupt`/`queue` = valori riservati documentati, mai emessi in v1.
8. **Subagent nella policy centrale**: nuovo metodo `PermissionService.explain_denial(...) -> str | None` (ALLOW → `None`; NEEDS_CONFIRMATION → negazione pulita «requires user confirmation, not available in this context»; DENY → motivo). Il plugin lo chiama via `ctx` duck-typed con mode/scope della conversazione PADRE. Il pre-filtro `_resolve_subagent_tools` resta (difesa in profondità). Conseguenza voluta: in `plan` il subagent non muta più nulla; i tool fs sono confinati allo scope/sandbox.
9. **Voce per-messaggio, non per-connessione**: campo opzionale `source: Literal["text","voice"]` su `WsUserMessage` (la stessa socket chat serve turni testo e voce — un query param sarebbe granularità sbagliata; deviazione motivata dal vecchio appunto `?scope=voice` in docs/agent-rework/PLAN.md). `_assembly.py` applica `agent.voice.max_tools` quando `source == "voice"` (helper `_apply_voice_trim` unit-testabile). Il seam morto si attiva; il gating resta identico (stessa policy, superficie ridotta).
10. **Config**: `triggers.{enabled,max_concurrent_turns}` e `attention.{enabled,cooldown_s}`; default `enabled: true` MA nessun trigger registrato di default ⇒ zero comportamento nuovo out-of-the-box. Flag censiti in `docs/flag-registry.md`.
11. **`origin` dei frame nuovi**: `background_task.updated` → `origin="agent"` (attività dell'agente); `attention.raised` → default `system` (l'iniziativa è del controller di sistema).

---

### Task 1: Contratto WS events — frame `background_task.updated` e `attention.raised`

**Files:**
- Modify: `backend/api/ws_schema/events.py`
- Test: `backend/tests/contracts/test_ws_schema_events.py`

- [ ] **Step 1.1: aggiorna i test di contratto (falliranno)**

In `backend/tests/contracts/test_ws_schema_events.py`:

1. In `EXPECTED_EVENTS_SERVER_TYPES` (dopo `"command.request",`) aggiungi:

```python
    "background_task.updated",
    "attention.raised",
```

2. In `REPRESENTATIVE_SERVER_FRAMES` aggiungi in coda alla lista:

```python
    {
        "type": "background_task.updated",
        "origin": "agent",
        "task_id": "bt-1",
        "kind": "subagent",
        "label": "Research task",
        "status": "running",
        "progress": 0.5,
        "detail": "step 3/6",
        "conversation_id": "conv-1",
        "updated_at": "2026-07-11T12:00:00+00:00",
    },
    {
        "type": "attention.raised",
        "source": "trigger:morning-briefing",
        "message": "Autonomous turn completed",
        "priority": "normal",
        "conversation_id": "conv-1",
    },
```

3. Aggiungi due test negativi in coda al file (pattern degli esistenti):

```python
def test_background_task_status_vocabulary_is_frozen() -> None:
    """The status literal is part of the contract."""
    from backend.api.ws_schema.events import WsBackgroundTaskUpdated

    with pytest.raises(ValidationError):
        WsBackgroundTaskUpdated.model_validate(
            {
                "type": "background_task.updated",
                "task_id": "bt-1",
                "kind": "subagent",
                "label": "x",
                "status": "paused",
                "updated_at": "2026-07-11T12:00:00+00:00",
            },
        )


def test_attention_priority_vocabulary_is_frozen() -> None:
    from backend.api.ws_schema.events import WsAttentionRaised

    with pytest.raises(ValidationError):
        WsAttentionRaised.model_validate(
            {
                "type": "attention.raised",
                "source": "s",
                "message": "m",
                "priority": "screaming",
            },
        )
```

(Verifica che `pytest` e `ValidationError` siano già importati nel file; altrimenti aggiungi gli import mancanti in testa, stile del file.)

- [ ] **Step 1.2: verifica che falliscano**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/contracts/test_ws_schema_events.py -v`
Expected: FAIL su `test_events_server_vocabulary_is_frozen` (i due tipi nuovi non esistono) + i representative frame nuovi + i due test negativi (import error sulle classi).

- [ ] **Step 1.3: aggiungi i modelli a `backend/api/ws_schema/events.py`**

Dopo `WsCommandRequest` (in coda alle classi server, prima delle union):

```python
class WsBackgroundTaskUpdated(EventsServerFrame):
    """A background task was created or changed state (Fase 8, spec §8).

    Carries the FULL task snapshot so the FE store can fold it directly
    (same philosophy as ``tasks.updated``).
    """

    type: Literal["background_task.updated"]
    task_id: str
    kind: str
    label: str
    status: Literal["running", "completed", "failed"]
    progress: float | None = None
    detail: str | None = None
    conversation_id: str | None = None
    updated_at: str


class WsAttentionRaised(EventsServerFrame):
    """The AttentionService decided to surface initiative to the user."""

    type: Literal["attention.raised"]
    source: str
    message: str
    priority: Literal["low", "normal", "urgent"] = "normal"
    conversation_id: str | None = None
```

Poi in `EventsServerMessage` aggiungi i due membri in coda all'unione (dopo `| WsCommandRequest`):

```python
    | WsBackgroundTaskUpdated
    | WsAttentionRaised,
```

- [ ] **Step 1.4: verifica che passino**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/contracts/ -v`
Expected: PASS tutti (i contract test degli altri canali NON devono cambiare).

- [ ] **Step 1.5: ruff sui file toccati e commit**

Run (da `backend/`): `..\.venv\Scripts\ruff.exe check api/ws_schema/events.py tests/contracts/test_ws_schema_events.py`

```bash
git add backend/api/ws_schema/events.py backend/tests/contracts/test_ws_schema_events.py
git commit -m "feat(ws): background_task.updated + attention.raised event frames (fase 8)"
```

NOTA: gli artifact generati committati restano stale fino al Task 10 (atteso: NON eseguire la regen qui).

---

### Task 2: Contratto WS chat — campo `source` su `WsUserMessage`

**Files:**
- Modify: `backend/api/ws_schema/chat.py:352-363`
- Test: `backend/tests/contracts/test_ws_schema_chat.py`

- [ ] **Step 2.1: scrivi il test (fallirà)**

In `backend/tests/contracts/test_ws_schema_chat.py`, dopo `test_user_message_has_no_type_discriminant` (riga ~246):

```python
def test_user_message_accepts_optional_voice_source() -> None:
    """Fase 8: per-message input modality drives the voice tool trim."""
    from backend.api.ws_schema.chat import WsUserMessage

    msg = WsUserMessage.model_validate(
        {"content": "ciao", "conversation_id": "c1", "source": "voice"},
    )
    assert msg.source == "voice"
    assert WsUserMessage.model_validate({"content": "hey"}).source is None
    with pytest.raises(ValidationError):
        WsUserMessage.model_validate({"content": "x", "source": "telepathy"})
```

- [ ] **Step 2.2: verifica che fallisca**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/contracts/test_ws_schema_chat.py -v`
Expected: FAIL (`source` è extra field → `extra='forbid'` lo rifiuta).

- [ ] **Step 2.3: aggiungi il campo**

In `backend/api/ws_schema/chat.py`, classe `WsUserMessage` (riga ~352), dopo `edit_message_id`:

```python
    source: Literal["text", "voice"] | None = None
    """Input modality; ``voice`` turns get a trimmed toolset (Fase 8)."""
```

- [ ] **Step 2.4: verifica che passi**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/contracts/test_ws_schema_chat.py -v`
Expected: PASS.

- [ ] **Step 2.5: commit**

```bash
git add backend/api/ws_schema/chat.py backend/tests/contracts/test_ws_schema_chat.py
git commit -m "feat(ws): optional source field on WsUserMessage for voice turns (fase 8)"
```

---

### Task 3: `AliceEvent` nuovi valori + `BackgroundTaskService` + bridge + campi gruppi

**Files:**
- Modify: `backend/core/event_bus.py` (enum `AliceEvent`, righe ~28-77)
- Create: `backend/services/background_tasks.py`
- Modify: `backend/core/bootstrap/surfaces.py` (bridge in coda a `stage_surfaces`)
- Modify: `backend/core/service_groups.py` (`PlatformServices`)
- Modify: `backend/core/context.py` (property + `FLAT_FIELDS`)
- Test: `backend/tests/test_background_tasks.py`

- [ ] **Step 3.1: enum bus**

In `backend/core/event_bus.py`, in coda a `AliceEvent` (dopo `PLAN_DOCUMENT_UPDATED`):

```python
    # Fase 8 — Fondamenta Jarvis (spec §8)
    BACKGROUND_TASK_UPDATED = "background_task.updated"
    ATTENTION_RAISED = "attention.raised"
    TRIGGER_FIRED = "trigger.fired"
```

- [ ] **Step 3.2: campi gruppo + property + FLAT_FIELDS**

In `backend/core/service_groups.py`, in coda a `PlatformServices`:

```python
    background_task_service: Any = None
    """Observable background-task registry (Fase 8, spec §8)."""
    attention_service: Any = None
    """Single decision point for agent-initiated user attention (Fase 8)."""
    trigger_service: Any = None
    """Autonomous-turn trigger sources: schedule/event/manual (Fase 8)."""
```

In `backend/core/context.py`: aggiungi i tre nomi a `FLAT_FIELDS` (righe ~62-75) e tre coppie property/setter deleganti sul gruppo `platform`, stile esatto di `command_bridge_service` (context.py:252-258), es.:

```python
    @property
    def background_task_service(self) -> Any:
        return self.platform.background_task_service

    @background_task_service.setter
    def background_task_service(self, value: Any) -> None:
        self.platform.background_task_service = value
```

(idem per `attention_service` e `trigger_service`).

- [ ] **Step 3.3: scrivi i test del service (falliranno: modulo inesistente)**

Create `backend/tests/test_background_tasks.py`:

```python
"""Tests for the Fase 8 observable background-task registry."""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.event_bus import AliceEvent, EventBus
from backend.services.background_tasks import BackgroundTaskService


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


def _collect(bus: EventBus) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    async def _handler(**kwargs: Any) -> None:
        seen.append(kwargs)

    bus.subscribe(AliceEvent.BACKGROUND_TASK_UPDATED, _handler)
    return seen


@pytest.mark.asyncio
async def test_lifecycle_start_update_complete(bus: EventBus) -> None:
    seen = _collect(bus)
    svc = BackgroundTaskService(event_bus=bus)

    task_id = await svc.start(kind="subagent", label="Research", conversation_id="c1")
    await svc.update(task_id, progress=0.5, detail="step 3/6")
    await svc.complete(task_id, detail="done")

    assert [e["status"] for e in seen] == ["running", "running", "completed"]
    assert seen[1]["progress"] == 0.5
    assert seen[2]["progress"] == 1.0
    snap = svc.get(task_id)
    assert snap is not None
    assert snap.status == "completed"


@pytest.mark.asyncio
async def test_fail_records_error_detail(bus: EventBus) -> None:
    seen = _collect(bus)
    svc = BackgroundTaskService(event_bus=bus)
    task_id = await svc.start(kind="autonomous_turn", label="Trigger: t1")
    await svc.fail(task_id, error="boom")
    assert seen[-1]["status"] == "failed"
    assert seen[-1]["detail"] == "boom"


@pytest.mark.asyncio
async def test_update_after_terminal_is_noop(bus: EventBus) -> None:
    seen = _collect(bus)
    svc = BackgroundTaskService(event_bus=bus)
    task_id = await svc.start(kind="subagent", label="x")
    await svc.complete(task_id)
    await svc.update(task_id, progress=0.1)
    await svc.fail(task_id, error="late")
    assert [e["status"] for e in seen] == ["running", "completed"]


@pytest.mark.asyncio
async def test_unknown_task_id_is_noop(bus: EventBus) -> None:
    seen = _collect(bus)
    svc = BackgroundTaskService(event_bus=bus)
    await svc.update("nope", progress=0.5)
    await svc.complete("nope")
    assert seen == []


@pytest.mark.asyncio
async def test_finished_tasks_are_pruned(bus: EventBus) -> None:
    svc = BackgroundTaskService(event_bus=bus, max_finished=2)
    ids = []
    for i in range(3):
        task_id = await svc.start(kind="subagent", label=f"t{i}")
        await svc.complete(task_id)
        ids.append(task_id)
    assert svc.get(ids[0]) is None
    assert svc.get(ids[1]) is not None
    assert svc.get(ids[2]) is not None
```

(Se `backend/pyproject.toml` ha `asyncio_mode = "auto"` i marker sono ridondanti ma innocui: lasciali, coerenti coi test esistenti — verifica lo stile di un test asincrono esistente, es. `tests/test_tool_loop.py`.)

- [ ] **Step 3.4: verifica che falliscano**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_background_tasks.py -v`
Expected: FAIL con `ModuleNotFoundError: backend.services.background_tasks`.

- [ ] **Step 3.5: implementa il service**

Create `backend/services/background_tasks.py`:

```python
"""AL\\CE — In-memory registry of observable background tasks (Fase 8, spec §8).

Formalises the "observable background task": every state change is published
on the event bus as ``AliceEvent.BACKGROUND_TASK_UPDATED`` and bridged to the
events WebSocket by the surfaces stage, so the UI folds progress into its
``backgroundTasks`` store. Storage is deliberately in-memory — Fase 8 lays
the interface, not a persistent job queue (data is resettable, spec §2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from loguru import logger

from backend.core.event_bus import AliceEvent, EventBus

TaskStatus = Literal["running", "completed", "failed"]

_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class BackgroundTask:
    """Immutable snapshot of one observable background task."""

    task_id: str
    kind: str
    label: str
    status: TaskStatus
    progress: float | None
    detail: str | None
    conversation_id: str | None
    updated_at: str


class BackgroundTaskService:
    """Registry + event emitter for observable background tasks.

    Args:
        event_bus: Bus the per-change ``background_task.updated`` events are
            emitted on (bridged to the events WS in ``stage_surfaces``).
        max_finished: Cap on retained terminal tasks; oldest pruned first.
    """

    def __init__(self, *, event_bus: EventBus, max_finished: int = 50) -> None:
        self._bus = event_bus
        self._tasks: dict[str, BackgroundTask] = {}
        self._finished_order: list[str] = []
        self._max_finished = max_finished

    async def start(
        self, *, kind: str, label: str, conversation_id: str | None = None,
    ) -> str:
        """Register a new running task and return its id."""
        task = BackgroundTask(
            task_id=str(uuid.uuid4()),
            kind=kind,
            label=label,
            status="running",
            progress=None,
            detail=None,
            conversation_id=conversation_id,
            updated_at=_now_iso(),
        )
        self._tasks[task.task_id] = task
        await self._emit(task)
        return task.task_id

    async def update(
        self,
        task_id: str,
        *,
        progress: float | None = None,
        detail: str | None = None,
    ) -> None:
        """Report progress on a running task; unknown/terminal ids are no-ops."""
        task = self._tasks.get(task_id)
        if task is None or task.status in _TERMINAL_STATUSES:
            return
        task = replace(
            task,
            progress=progress if progress is not None else task.progress,
            detail=detail if detail is not None else task.detail,
            updated_at=_now_iso(),
        )
        self._tasks[task_id] = task
        await self._emit(task)

    async def complete(self, task_id: str, *, detail: str | None = None) -> None:
        """Mark a running task as completed (progress snaps to 1.0)."""
        await self._finish(task_id, status="completed", detail=detail)

    async def fail(self, task_id: str, *, error: str) -> None:
        """Mark a running task as failed with a human-readable error."""
        await self._finish(task_id, status="failed", detail=error)

    def get(self, task_id: str) -> BackgroundTask | None:
        """Return the current snapshot for ``task_id`` (or ``None``)."""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[BackgroundTask]:
        """Return every retained task snapshot."""
        return list(self._tasks.values())

    async def _finish(
        self, task_id: str, *, status: TaskStatus, detail: str | None,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.status in _TERMINAL_STATUSES:
            return
        task = replace(
            task,
            status=status,
            progress=1.0 if status == "completed" else task.progress,
            detail=detail if detail is not None else task.detail,
            updated_at=_now_iso(),
        )
        self._tasks[task_id] = task
        self._finished_order.append(task_id)
        while len(self._finished_order) > self._max_finished:
            oldest = self._finished_order.pop(0)
            self._tasks.pop(oldest, None)
        await self._emit(task)

    async def _emit(self, task: BackgroundTask) -> None:
        try:
            await self._bus.emit(
                AliceEvent.BACKGROUND_TASK_UPDATED,
                task_id=task.task_id,
                kind=task.kind,
                label=task.label,
                status=task.status,
                progress=task.progress,
                detail=task.detail,
                conversation_id=task.conversation_id,
                updated_at=task.updated_at,
                origin="agent",
            )
        except Exception as exc:  # pragma: no cover — bus must never break callers
            logger.error("BackgroundTaskService: emit failed: {}", exc)
```

- [ ] **Step 3.6: verifica che passino**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_background_tasks.py -v`
Expected: PASS 5/5.

- [ ] **Step 3.7: bridge bus→WS in `stage_surfaces`**

In `backend/core/bootstrap/surfaces.py`, in coda a `stage_surfaces` (dopo il subscribe di `knowledge.status`, stile esatto di `_forward_service_status` a surfaces.py:107-120):

```python
    # -- Bridge Fase 8 (Fondamenta Jarvis) events to the events WS -------
    async def _forward_background_task(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "background_task.updated",
                "origin": "agent",
                "task_id": kwargs.get("task_id"),
                "kind": kwargs.get("kind"),
                "label": kwargs.get("label"),
                "status": kwargs.get("status"),
                "progress": kwargs.get("progress"),
                "detail": kwargs.get("detail"),
                "conversation_id": kwargs.get("conversation_id"),
                "updated_at": kwargs.get("updated_at"),
            })

    ctx.event_bus.subscribe(
        AliceEvent.BACKGROUND_TASK_UPDATED, _forward_background_task,
    )

    async def _forward_attention_raised(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "attention.raised",
                "source": kwargs.get("source"),
                "message": kwargs.get("message"),
                "priority": kwargs.get("priority", "normal"),
                "conversation_id": kwargs.get("conversation_id"),
            })

    ctx.event_bus.subscribe(
        AliceEvent.ATTENTION_RAISED, _forward_attention_raised,
    )
```

- [ ] **Step 3.8: gate e commit**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_background_tasks.py tests/contracts/ -v`
Run (da `backend/`): `..\.venv\Scripts\ruff.exe check services/background_tasks.py tests/test_background_tasks.py core/event_bus.py core/service_groups.py core/context.py core/bootstrap/surfaces.py`
Run (dalla REPO ROOT): `.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml`
Expected: tutto verde.

```bash
git add backend/core/event_bus.py backend/core/service_groups.py backend/core/context.py backend/core/bootstrap/surfaces.py backend/services/background_tasks.py backend/tests/test_background_tasks.py
git commit -m "feat(jarvis): BackgroundTaskService - observable background tasks over the event bus (fase 8)"
```

---

### Task 4: `AttentionService` + config `attention.*`

**Files:**
- Create: `backend/services/attention_service.py`
- Modify: `backend/core/config.py` (nuovo `AttentionConfig`, aggancio in `AliceConfig`)
- Modify: `config/default.yaml`
- Modify: `docs/flag-registry.md`
- Test: `backend/tests/test_attention_service.py`

- [ ] **Step 4.1: scrivi i test (falliranno)**

Create `backend/tests/test_attention_service.py`:

```python
"""Tests for the Fase 8 AttentionService (initiative decision point)."""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.event_bus import AliceEvent, EventBus
from backend.services.attention_service import AttentionDecision, AttentionService


def _collect(bus: EventBus) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    async def _handler(**kwargs: Any) -> None:
        seen.append(kwargs)

    bus.subscribe(AliceEvent.ATTENTION_RAISED, _handler)
    return seen


@pytest.mark.asyncio
async def test_disabled_drops_everything() -> None:
    bus = EventBus()
    seen = _collect(bus)
    svc = AttentionService(event_bus=bus, enabled=False, cooldown_s=0.0)
    decision = await svc.request_attention(source="test", message="hi")
    assert decision is AttentionDecision.DROP
    assert seen == []


@pytest.mark.asyncio
async def test_notify_emits_attention_raised() -> None:
    bus = EventBus()
    seen = _collect(bus)
    svc = AttentionService(event_bus=bus, enabled=True, cooldown_s=0.0)
    decision = await svc.request_attention(
        source="trigger:t1", message="done", conversation_id="c1",
    )
    assert decision is AttentionDecision.NOTIFY
    assert seen == [
        {
            "source": "trigger:t1",
            "message": "done",
            "priority": "normal",
            "conversation_id": "c1",
        },
    ]


@pytest.mark.asyncio
async def test_cooldown_drops_non_urgent_but_not_urgent() -> None:
    bus = EventBus()
    seen = _collect(bus)
    svc = AttentionService(event_bus=bus, enabled=True, cooldown_s=3600.0)
    first = await svc.request_attention(source="a", message="1")
    second = await svc.request_attention(source="a", message="2")
    urgent = await svc.request_attention(source="a", message="3", priority="urgent")
    assert first is AttentionDecision.NOTIFY
    assert second is AttentionDecision.DROP
    assert urgent is AttentionDecision.NOTIFY
    assert [e["message"] for e in seen] == ["1", "3"]
```

- [ ] **Step 4.2: verifica che falliscano**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_attention_service.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 4.3: implementa il service**

Create `backend/services/attention_service.py`:

```python
"""AL\\CE — AttentionService: single decision point for agent→user initiative.

Every proactive surface (trigger completions, background alerts, the future
"Jarvis speaks first" behaviours) must ask this service before reaching the
user (spec §8). Fase 8 lays the interface and a minimal policy — the rich
prioritisation arrives after the risanamento. Central and disableable by
design: ``attention.enabled: false`` silences ALL agent-initiated attention.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Literal

from loguru import logger

from backend.core.event_bus import AliceEvent, EventBus

AttentionPriority = Literal["low", "normal", "urgent"]


class AttentionDecision(StrEnum):
    """What the service decided to do with an attention request.

    ``INTERRUPT`` and ``QUEUE`` are part of the vocabulary (spec §8) but the
    v1 policy never returns them — reserved for the rich implementation.
    """

    INTERRUPT = "interrupt"
    NOTIFY = "notify"
    QUEUE = "queue"
    DROP = "drop"


class AttentionService:
    """Minimal v1 policy: disabled → DROP, cooldown → DROP, else NOTIFY.

    Args:
        event_bus: Bus the ``attention.raised`` events are emitted on
            (bridged to the events WS in ``stage_surfaces``).
        enabled: Master switch (``attention.enabled``); off means the
            assistant never takes initiative towards the user.
        cooldown_s: Minimum seconds between two non-urgent notifications
            (anti-spam). ``urgent`` requests bypass the cooldown.
    """

    def __init__(
        self, *, event_bus: EventBus, enabled: bool, cooldown_s: float,
    ) -> None:
        self._bus = event_bus
        self._enabled = enabled
        self._cooldown_s = cooldown_s
        self._last_notify_monotonic: float | None = None

    async def request_attention(
        self,
        *,
        source: str,
        message: str,
        conversation_id: str | None = None,
        priority: AttentionPriority = "normal",
    ) -> AttentionDecision:
        """Decide whether/how to surface ``message`` to the user.

        Returns the decision; on ``NOTIFY`` an ``attention.raised`` event is
        emitted (bridged to the events WS → UI toast).
        """
        if not self._enabled:
            logger.debug("Attention: dropped (disabled): {} — {}", source, message)
            return AttentionDecision.DROP

        now = time.monotonic()
        in_cooldown = (
            self._last_notify_monotonic is not None
            and (now - self._last_notify_monotonic) < self._cooldown_s
        )
        if in_cooldown and priority != "urgent":
            logger.debug("Attention: dropped (cooldown): {} — {}", source, message)
            return AttentionDecision.DROP

        self._last_notify_monotonic = now
        await self._bus.emit(
            AliceEvent.ATTENTION_RAISED,
            source=source,
            message=message,
            priority=priority,
            conversation_id=conversation_id,
        )
        return AttentionDecision.NOTIFY
```

- [ ] **Step 4.4: verifica che passino**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_attention_service.py -v`
Expected: PASS 3/3.

- [ ] **Step 4.5: config**

In `backend/core/config.py`, dopo `CommandsConfig` (riga ~392):

```python
class AttentionConfig(BaseSettings):
    """AttentionService policy (Fase 8, spec §8)."""

    model_config = SettingsConfigDict(env_prefix="ALICE_ATTENTION__")

    enabled: bool = True
    """Master switch for agent-initiated attention towards the user."""
    cooldown_s: float = 30.0
    """Minimum seconds between two non-urgent notifications (anti-spam)."""
```

In `AliceConfig`, dopo il campo `commands` (riga ~1344):

```python
    attention: AttentionConfig = Field(default_factory=AttentionConfig)
    """Agent→user initiative policy (Fase 8)."""
```

In `config/default.yaml`, dopo la sezione `commands`:

```yaml
# Fondamenta Jarvis (spec §8): agent-initiated attention towards the user.
attention:
  enabled: true
  cooldown_s: 30.0                # min seconds between non-urgent notifications
```

In `docs/flag-registry.md`, nuova riga in tabella:

```
| `attention.enabled` | true | `bootstrap/jarvis.py`, `services/attention_service.py` | spegne OGNI iniziativa dell'agente verso l'utente (decision point unico §8) |
```

- [ ] **Step 4.6: gate e commit**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_attention_service.py -v`
Run (da `backend/`): `..\.venv\Scripts\ruff.exe check services/attention_service.py tests/test_attention_service.py core/config.py`
Expected: verde.

```bash
git add backend/services/attention_service.py backend/tests/test_attention_service.py backend/core/config.py config/default.yaml docs/flag-registry.md
git commit -m "feat(jarvis): AttentionService - central disableable initiative decision point (fase 8)"
```

---

### Task 5: Seam del turno headless — sink, channel, assembler opzionale, runner

**Files:**
- Modify: `backend/services/turn/sink.py` (nuova classe `NullEventSink` in coda)
- Modify: `backend/services/turn/channel.py` (nuova classe `HeadlessInteractionChannel` in coda)
- Modify: `backend/api/routes/chat/_assembly.py` (`websocket: WebSocket | None` + guardie)
- Create: `backend/api/routes/chat/headless.py`
- Test: `backend/tests/test_headless_turn.py`

- [ ] **Step 5.1: `NullEventSink`**

In `backend/services/turn/sink.py`, dopo `RecordingEventSink`:

```python
class NullEventSink:
    """Sink for headless (autonomous) turns: no surface, events are dropped.

    Observability of autonomous turns rides the background-task events
    (Fase 8), not the chat stream — there is no client on the other side.
    """

    _ws: None = None  # No real WebSocket — mirrors RecordingEventSink.

    async def send(self, event: dict[str, Any]) -> None:
        """Drop ``event``; a headless turn has no outbound transport."""
        return None

    @property
    def is_connected(self) -> bool:
        """Always ``True`` — the (null) surface can never be lost."""
        return True
```

- [ ] **Step 5.2: `HeadlessInteractionChannel`**

In `backend/services/turn/channel.py`, dopo `ScriptedInteractionChannel`:

```python
class HeadlessInteractionChannel:
    """Interaction channel for autonomous turns (Fase 8, spec §8).

    There is no user on the other side: every interactive request resolves
    to ``None`` immediately, which the middlewares already collapse into
    clean, non-exceptional outcomes (tool confirmation → rejected, ask_user
    → unanswered). Mirrors the Fase 7 "UI not available" philosophy: a
    missing surface is a clean result, never an exception.
    """

    def __init__(self) -> None:
        self._cancel_event = asyncio.Event()

    async def request(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        execution_id: str,
        timeout_s: float,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any] | None:
        """Auto-decline: no user is available to answer ``kind``."""
        logger.debug(
            "Headless turn: interactive request '{}' auto-declined (exec_id={})",
            kind, execution_id,
        )
        return None

    @property
    def cancelled(self) -> bool:
        """Whether the (externally settable) cancel flag is up."""
        return self._cancel_event.is_set()

    @property
    def connected(self) -> bool:
        """Always ``True``: the channel exists, its answers are just ``None``."""
        return True
```

Verifica con un test rapido che soddisfi il Protocol:

```python
# in backend/tests/test_headless_turn.py (vedi step 5.5 per il file completo)
def test_headless_channel_satisfies_protocol() -> None:
    from backend.services.turn.channel import HeadlessInteractionChannel, InteractionChannel

    channel = HeadlessInteractionChannel()
    assert isinstance(channel, InteractionChannel)
    assert channel.connected is True
    assert channel.cancelled is False
```

- [ ] **Step 5.3: `TurnAssembler` websocket-optional**

In `backend/api/routes/chat/_assembly.py`:

1. Cambia la firma di `assemble` (riga ~133): `websocket: WebSocket | None,` e aggiorna il docstring («When ``websocket`` is ``None`` (headless turns) validation-failure frames are skipped and the method just returns ``None``»).
2. Avvolgi OGNI occorrenza di `await websocket.send_json(...)` (grep: sono ~7, righe ~158, ~179, ~189, ~621, ~656, ~669, ~675 pre-edit) in una guardia, preservando il comportamento di ritorno. Esempio del pattern (primo sito):

```python
            except ValueError:
                if websocket is not None:
                    await websocket.send_json(
                        {"type": "error", "content": "Invalid conversation_id"}
                    )
                return None
```

ATTENZIONE: la guardia avvolge SOLO la send; `return None`/`continue`/flusso restano identici fuori dall'`if`.

- [ ] **Step 5.4: runner headless**

Create `backend/api/routes/chat/headless.py`:

```python
"""AL\\CE — Headless (autonomous) turn runner (Fase 8, spec §8).

An autonomous turn IS a normal turn: same assembly, executor, permission
mode and scope of the conversation it belongs to. The only differences are
the missing surfaces: chat-stream events go to a :class:`NullEventSink`
(observability rides the background-task events) and interactive requests
are auto-declined by a :class:`HeadlessInteractionChannel`.

Lives in the api layer because it reuses :class:`TurnAssembler` and
``_persist_final_turn``; the TriggerService (services layer) receives it as
an injected ``turn_runner`` from ``stage_jarvis`` (the composition root is
the sanctioned ``backend.core.bootstrap.* -> backend.api.**`` exception).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.api.routes.chat._assembly import TurnAssembler
from backend.api.routes.chat._persist import _persist_final_turn
from backend.services.turn.channel import HeadlessInteractionChannel
from backend.services.turn.factory import create_turn_executor
from backend.services.turn.sink import NullEventSink

if TYPE_CHECKING:
    from backend.core.context import AppContext
    from backend.services.turn.models import TurnResult


def _strip_client_tools(
    ctx: AppContext, tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Drop client-executed tools: a headless turn has no UI to run them."""
    if not tools:
        return tools
    registry = ctx.tool_registry
    if registry is None:
        return tools
    kept: list[dict[str, Any]] = []
    for entry in tools:
        name = entry.get("function", {}).get("name", "")
        tool_def = registry.get_tool_definition(name)
        if tool_def is not None and tool_def.client_execution:
            continue
        kept.append(entry)
    return kept


async def run_headless_turn(
    ctx: AppContext,
    *,
    conversation_id: str | None,
    prompt: str,
    origin: str = "system",
) -> TurnResult | None:
    """Run one autonomous turn through the normal pipeline and persist it.

    Args:
        ctx: The application context.
        conversation_id: Target conversation (``None`` creates a new one).
        prompt: The user-role content that starts the turn.
        origin: Provenance recorded in logs (``system`` for triggers).

    Returns:
        The :class:`TurnResult`, or ``None`` when the turn could not start
        (no DB / no LLM / assembly validation failure).
    """
    llm = ctx.llm_service
    if ctx.db is None or llm is None:
        logger.warning("Headless turn skipped: DB or LLM service unavailable")
        return None

    assembler = TurnAssembler(ctx, llm, continuum_scope=False, client_ip="headless")
    data: dict[str, Any] = {"content": prompt}
    if conversation_id:
        data["conversation_id"] = conversation_id

    async with ctx.db() as session:
        assembly = await assembler.assemble(
            session=session, websocket=None, data=data, user_content=prompt,
        )
        if assembly is None:
            logger.warning("Headless turn: assembly failed (origin={})", origin)
            return None

        turn = replace(
            assembly.turn, tools=_strip_client_tools(ctx, assembly.turn.tools),
        )
        sink = NullEventSink()
        channel = HeadlessInteractionChannel()
        cancel_event = asyncio.Event()

        executor = create_turn_executor(ctx, llm)
        result = await executor.execute(turn, sink, cancel_event, session, channel)

        await _persist_final_turn(
            session=session,
            conv=assembly.conv,
            conv_id=turn.conv_id,
            user_msg=assembly.user_msg,
            result=result,
            sink=sink,
            ctx=ctx,
            llm=llm,
            user_content=prompt,
            was_compressed=assembly.comp is not None,
            pre_comp=assembly.comp,
            context_window=assembly.context_window,
            tool_tokens=assembly.tool_tokens,
            messages=assembly.messages,
            av_map=assembly.av_map,
            cached_sys_prompt=assembly.cached_sys_prompt,
        )
        return result
```

Inoltre: avvolgi l'`await executor.execute(...)` nell'idle-guard `conversation_active(str(turn.conv_id))` usando LO STESSO import di `ws.py` (cerca `conversation_active` in `backend/api/routes/chat/ws.py` e replica l'import + il `with`), così le mutazioni di scope sono rifiutate anche durante un turno autonomo.

- [ ] **Step 5.5: test del seam**

Create `backend/tests/test_headless_turn.py`. Contenuto: il test del Protocol (step 5.2), un test del sink, un test unit di `_strip_client_tools`, e UN test integrato del runner con LLM mock testo-solo e DB sqlite in-memory:

```python
"""Tests for the Fase 8 headless-turn seam (autonomous turns)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession


def test_headless_channel_satisfies_protocol() -> None:
    from backend.services.turn.channel import (
        HeadlessInteractionChannel,
        InteractionChannel,
    )

    channel = HeadlessInteractionChannel()
    assert isinstance(channel, InteractionChannel)
    assert channel.connected is True
    assert channel.cancelled is False


@pytest.mark.asyncio
async def test_headless_channel_request_returns_none() -> None:
    from backend.services.turn.channel import HeadlessInteractionChannel

    channel = HeadlessInteractionChannel()
    answer = await channel.request(
        "tool_confirmation", {"tool": "x"}, execution_id="e1", timeout_s=1.0,
    )
    assert answer is None


@pytest.mark.asyncio
async def test_null_sink_satisfies_protocol_and_drops() -> None:
    from backend.services.turn.sink import NullEventSink, WSEventSink

    sink = NullEventSink()
    assert isinstance(sink, WSEventSink)
    assert sink.is_connected is True
    await sink.send({"type": "token", "content": "x"})  # must not raise


@pytest.mark.asyncio
async def test_run_headless_turn_persists_a_normal_turn() -> None:
    """An autonomous turn is a normal turn: user+assistant rows persisted."""
    from sqlmodel import select

    from backend.api.routes.chat.headless import run_headless_turn
    from backend.db.models import Message
    from backend.tests._turn_helpers import StreamingMockLLM, make_ctx

    ctx = make_ctx()
    ctx.llm_service = StreamingMockLLM(
        [[{"type": "token", "content": "Autonomous hello"}]],
    )

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    ctx.db = async_sessionmaker(
        engine, class_=SQLModelAsyncSession, expire_on_commit=False,
    )

    result = await run_headless_turn(
        ctx, conversation_id=None, prompt="Daily briefing please",
    )

    assert result is not None
    assert result.finish_reason != "error"
    async with ctx.db() as session:
        rows = (await session.exec(select(Message))).all()
    roles = [r.role for r in rows]
    assert "user" in roles
    assert "assistant" in roles
    await engine.dispose()
```

NOTE per l'implementer: (a) `backend/tests/_turn_helpers.py` fornisce `make_ctx` e `StreamingMockLLM` — se le loro firme differiscono (es. `make_ctx` richiede kwargs, il mock si costruisce diversamente), ADATTA il test allo stile REALE degli helper (guarda `test_direct_executor_streaming.py` come riferimento d'uso) mantenendo le stesse asserzioni; (b) se l'assembler richiede servizi non-None che `make_ctx` non fornisce, aggiungili al ctx nel test (stub minimi), NON indebolire le asserzioni; (c) l'import di `Message` è `backend.db.models`.

- [ ] **Step 5.6: verifica**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_headless_turn.py -v`
Expected: PASS 4/4 (l'integrato può richiedere qualche secondo).

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_direct_executor_streaming.py tests/test_tool_loop.py -v`
Expected: PASS invariati (nessuna regressione dal cambio firma assembler — quei test non usano l'assembler, è una verifica di prudenza sul turn engine).

- [ ] **Step 5.7: gate e commit**

Run (da `backend/`): `..\.venv\Scripts\ruff.exe check services/turn/sink.py services/turn/channel.py api/routes/chat/headless.py tests/test_headless_turn.py`
Run (dalla REPO ROOT): `.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml`
Expected: verde.

```bash
git add backend/services/turn/sink.py backend/services/turn/channel.py backend/api/routes/chat/_assembly.py backend/api/routes/chat/headless.py backend/tests/test_headless_turn.py
git commit -m "feat(jarvis): headless turn seam - NullEventSink, HeadlessInteractionChannel, run_headless_turn (fase 8)"
```

---

### Task 6: `TriggerService` + config `triggers.*`

**Files:**
- Create: `backend/services/trigger_service.py`
- Modify: `backend/core/config.py` (nuovo `TriggersConfig`, aggancio in `AliceConfig`)
- Modify: `config/default.yaml`
- Modify: `docs/flag-registry.md`
- Test: `backend/tests/test_trigger_service.py`

- [ ] **Step 6.1: scrivi i test (falliranno)**

Create `backend/tests/test_trigger_service.py`:

```python
"""Tests for the Fase 8 TriggerService (autonomous-turn trigger sources)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.core.event_bus import AliceEvent, EventBus
from backend.services.trigger_service import TriggerService, TriggerSpec


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raise_error = False

    async def __call__(
        self, *, conversation_id: str | None, prompt: str, origin: str,
    ) -> Any:
        self.calls.append(
            {"conversation_id": conversation_id, "prompt": prompt, "origin": origin},
        )
        if self.raise_error:
            raise RuntimeError("turn failed")
        return None


class FakeBackgroundTasks:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def start(self, *, kind: str, label: str, conversation_id: str | None = None) -> str:
        self.events.append(("start", kind))
        return "bt-1"

    async def complete(self, task_id: str, *, detail: str | None = None) -> None:
        self.events.append(("complete", task_id))

    async def fail(self, task_id: str, *, error: str) -> None:
        self.events.append(("fail", error))


class FakeAttention:
    def __init__(self) -> None:
        self.requests: list[str] = []

    async def request_attention(self, *, source: str, message: str, **kwargs: Any) -> Any:
        self.requests.append(source)


def _service(
    bus: EventBus,
    runner: FakeRunner,
    *,
    enabled: bool = True,
    bts: FakeBackgroundTasks | None = None,
    attention: FakeAttention | None = None,
) -> TriggerService:
    return TriggerService(
        event_bus=bus,
        turn_runner=runner,
        background_tasks=bts,
        attention=attention,
        enabled=enabled,
        max_concurrent_turns=1,
    )


@pytest.mark.asyncio
async def test_manual_fire_runs_turn_and_reports() -> None:
    bus = EventBus()
    runner = FakeRunner()
    bts = FakeBackgroundTasks()
    attention = FakeAttention()
    svc = _service(bus, runner, bts=bts, attention=attention)
    svc.register(
        TriggerSpec(
            trigger_id="t1", kind="manual", conversation_id="c1", prompt="go",
        ),
    )
    await svc.start()
    await svc.fire("t1")
    assert runner.calls == [
        {"conversation_id": "c1", "prompt": "go", "origin": "system"},
    ]
    assert ("start", "autonomous_turn") in bts.events
    assert ("complete", "bt-1") in bts.events
    assert attention.requests == ["trigger:t1"]
    await svc.shutdown()


@pytest.mark.asyncio
async def test_failed_turn_fails_the_background_task() -> None:
    bus = EventBus()
    runner = FakeRunner()
    runner.raise_error = True
    bts = FakeBackgroundTasks()
    attention = FakeAttention()
    svc = _service(bus, runner, bts=bts, attention=attention)
    svc.register(
        TriggerSpec(trigger_id="t1", kind="manual", conversation_id=None, prompt="go"),
    )
    await svc.start()
    await svc.fire("t1")
    assert ("fail", "turn failed") in bts.events
    assert attention.requests == []
    await svc.shutdown()


@pytest.mark.asyncio
async def test_event_trigger_fires_but_ignores_agent_origin() -> None:
    bus = EventBus()
    runner = FakeRunner()
    svc = _service(bus, runner)
    svc.register(
        TriggerSpec(
            trigger_id="t-mail",
            kind="event",
            conversation_id="c1",
            prompt="summarise the new email",
            event_name="email.received",
        ),
    )
    await svc.start()
    await bus.emit("email.received", folder="INBOX", origin="agent")
    assert runner.calls == []
    await bus.emit("email.received", folder="INBOX")
    assert len(runner.calls) == 1
    await svc.shutdown()


@pytest.mark.asyncio
async def test_schedule_trigger_fires_on_interval() -> None:
    bus = EventBus()
    runner = FakeRunner()
    svc = _service(bus, runner)
    svc.register(
        TriggerSpec(
            trigger_id="t-tick",
            kind="schedule",
            conversation_id="c1",
            prompt="tick",
            interval_s=0.05,
        ),
    )
    await svc.start()
    await asyncio.sleep(0.2)
    await svc.shutdown()
    assert len(runner.calls) >= 1


@pytest.mark.asyncio
async def test_disabled_service_never_fires() -> None:
    bus = EventBus()
    runner = FakeRunner()
    svc = _service(bus, runner, enabled=False)
    svc.register(
        TriggerSpec(trigger_id="t1", kind="manual", conversation_id=None, prompt="go"),
    )
    await svc.start()
    await svc.fire("t1")
    assert runner.calls == []
    await svc.shutdown()


@pytest.mark.asyncio
async def test_register_validation_and_duplicates() -> None:
    bus = EventBus()
    svc = _service(bus, FakeRunner())
    with pytest.raises(ValueError):
        svc.register(
            TriggerSpec(trigger_id="bad", kind="schedule", conversation_id=None, prompt="x"),
        )
    with pytest.raises(ValueError):
        svc.register(
            TriggerSpec(trigger_id="bad", kind="event", conversation_id=None, prompt="x"),
        )
    svc.register(
        TriggerSpec(trigger_id="ok", kind="manual", conversation_id=None, prompt="x"),
    )
    with pytest.raises(ValueError):
        svc.register(
            TriggerSpec(trigger_id="ok", kind="manual", conversation_id=None, prompt="y"),
        )
    with pytest.raises(KeyError):
        await svc.fire("missing")


@pytest.mark.asyncio
async def test_fire_emits_trigger_fired_on_bus() -> None:
    bus = EventBus()
    seen: list[dict[str, Any]] = []

    async def _handler(**kwargs: Any) -> None:
        seen.append(kwargs)

    bus.subscribe(AliceEvent.TRIGGER_FIRED, _handler)
    svc = _service(bus, FakeRunner())
    svc.register(
        TriggerSpec(trigger_id="t1", kind="manual", conversation_id=None, prompt="go"),
    )
    await svc.start()
    await svc.fire("t1")
    assert seen and seen[0]["trigger_id"] == "t1"
    await svc.shutdown()
```

- [ ] **Step 6.2: verifica che falliscano**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_trigger_service.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 6.3: implementa il service**

Create `backend/services/trigger_service.py`:

```python
"""AL\\CE — TriggerService: autonomous-turn trigger sources (Fase 8, spec §8).

Starts autonomous turns from (a) simple time schedules, (b) event-bus events
and (c) manual/programmatic fire (the future hotword path). An autonomous
turn IS a normal turn — the injected ``turn_runner`` goes through the
standard assembly/executor/permission pipeline of the conversation the
trigger belongs to (spec §4.5: no privileged path).

Fase 8 lays the interface: rich cron/RRULE schedules, trigger persistence
and a registration surface (tools/REST) arrive after the risanamento.

Anti-echo invariant (spec §7/§8): bus events whose ``origin`` kwarg equals
``"agent"`` never fire an event trigger — the agent must not trigger itself.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from loguru import logger

from backend.core.event_bus import AliceEvent, EventBus


class TurnRunner(Protocol):
    """Callable running one autonomous turn (injected by the composition root)."""

    async def __call__(
        self, *, conversation_id: str | None, prompt: str, origin: str,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class TriggerSpec:
    """Declarative description of one trigger.

    Attributes:
        trigger_id: Unique id (used for unregister / manual fire).
        kind: ``schedule`` (interval loop), ``event`` (bus subscription) or
            ``manual`` (fired programmatically — the future hotword path).
        conversation_id: Conversation the autonomous turn belongs to
            (``None`` starts a fresh conversation per fire).
        prompt: User-role content of the autonomous turn.
        event_name: Bus event to subscribe to (required for ``event``).
        interval_s: Seconds between fires (required for ``schedule``).
        ignore_agent_origin: Drop bus events carrying ``origin == "agent"``
            (anti-echo default, spec §8).
    """

    trigger_id: str
    kind: Literal["schedule", "event", "manual"]
    conversation_id: str | None
    prompt: str
    event_name: str | None = None
    interval_s: float | None = None
    ignore_agent_origin: bool = True


class TriggerService:
    """Registry + activation of autonomous-turn triggers.

    Args:
        event_bus: Bus used both to subscribe event triggers and to emit
            ``trigger.fired`` observability events.
        turn_runner: The headless turn runner (``None`` disables firing —
            triggers register but never run, e.g. in unit tests).
        background_tasks: Optional ``BackgroundTaskService`` (duck-typed);
            every fire becomes an observable ``autonomous_turn`` task.
        attention: Optional ``AttentionService`` (duck-typed); completions
            are surfaced through the central initiative decision point.
        enabled: Master switch (``triggers.enabled``).
        max_concurrent_turns: Autonomous turns allowed at once; extra fires
            are skipped with a warning (no queueing in Fase 8).
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        turn_runner: TurnRunner | None,
        background_tasks: Any = None,
        attention: Any = None,
        enabled: bool = True,
        max_concurrent_turns: int = 1,
    ) -> None:
        self._bus = event_bus
        self._turn_runner = turn_runner
        self._background_tasks = background_tasks
        self._attention = attention
        self._enabled = enabled
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent_turns))
        self._triggers: dict[str, TriggerSpec] = {}
        self._schedule_tasks: dict[str, asyncio.Task[None]] = {}
        self._event_handlers: dict[str, Any] = {}
        self._started = False

    # -- Registry ---------------------------------------------------------

    def register(self, spec: TriggerSpec) -> None:
        """Register ``spec``; sources activate immediately when started."""
        if spec.trigger_id in self._triggers:
            raise ValueError(f"Trigger '{spec.trigger_id}' already registered")
        if spec.kind == "schedule" and not (spec.interval_s and spec.interval_s > 0):
            raise ValueError("schedule triggers require a positive interval_s")
        if spec.kind == "event" and not spec.event_name:
            raise ValueError("event triggers require event_name")
        self._triggers[spec.trigger_id] = spec
        if self._started:
            self._activate(spec)
        logger.info("Trigger registered: {} ({})", spec.trigger_id, spec.kind)

    def unregister(self, trigger_id: str) -> None:
        """Remove a trigger and deactivate its source (idempotent)."""
        spec = self._triggers.pop(trigger_id, None)
        if spec is None:
            return
        task = self._schedule_tasks.pop(trigger_id, None)
        if task is not None:
            task.cancel()
        handler = self._event_handlers.pop(trigger_id, None)
        if handler is not None and spec.event_name:
            self._bus.unsubscribe(spec.event_name, handler)

    def list_triggers(self) -> list[TriggerSpec]:
        """Return every registered trigger spec."""
        return list(self._triggers.values())

    # -- Lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Activate all registered triggers (idempotent)."""
        if self._started:
            return
        self._started = True
        for spec in self._triggers.values():
            self._activate(spec)

    async def shutdown(self) -> None:
        """Cancel schedule loops and unsubscribe event handlers."""
        self._started = False
        tasks = list(self._schedule_tasks.values())
        self._schedule_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for trigger_id, handler in list(self._event_handlers.items()):
            spec = self._triggers.get(trigger_id)
            if spec is not None and spec.event_name:
                self._bus.unsubscribe(spec.event_name, handler)
        self._event_handlers.clear()

    # -- Firing -----------------------------------------------------------

    async def fire(self, trigger_id: str) -> None:
        """Fire a registered trigger programmatically (manual/hotword seam)."""
        spec = self._triggers.get(trigger_id)
        if spec is None:
            raise KeyError(trigger_id)
        await self._fire(spec)

    def _activate(self, spec: TriggerSpec) -> None:
        if spec.kind == "schedule":
            task = asyncio.create_task(
                self._schedule_loop(spec), name=f"trigger-{spec.trigger_id}",
            )
            self._schedule_tasks[spec.trigger_id] = task
        elif spec.kind == "event":

            async def _on_event(**kwargs: Any) -> None:
                if spec.ignore_agent_origin and kwargs.get("origin") == "agent":
                    logger.debug(
                        "Trigger '{}': ignored agent-origin event", spec.trigger_id,
                    )
                    return
                await self._fire(spec)

            self._event_handlers[spec.trigger_id] = _on_event
            assert spec.event_name is not None  # validated in register()
            self._bus.subscribe(spec.event_name, _on_event)

    async def _schedule_loop(self, spec: TriggerSpec) -> None:
        interval = spec.interval_s or 0.0
        while True:
            await asyncio.sleep(interval)
            await self._fire(spec)

    async def _fire(self, spec: TriggerSpec) -> None:
        if not self._enabled:
            logger.debug("Trigger '{}' skipped: triggers disabled", spec.trigger_id)
            return
        if self._turn_runner is None:
            logger.warning(
                "Trigger '{}' skipped: no turn runner wired", spec.trigger_id,
            )
            return
        if self._semaphore.locked():
            logger.warning(
                "Trigger '{}' skipped: autonomous turn already running",
                spec.trigger_id,
            )
            return
        async with self._semaphore:
            await self._bus.emit(
                AliceEvent.TRIGGER_FIRED,
                trigger_id=spec.trigger_id,
                kind=spec.kind,
                origin="system",
            )
            task_id: str | None = None
            if self._background_tasks is not None:
                task_id = await self._background_tasks.start(
                    kind="autonomous_turn",
                    label=f"Trigger: {spec.trigger_id}",
                    conversation_id=spec.conversation_id,
                )
            try:
                await self._turn_runner(
                    conversation_id=spec.conversation_id,
                    prompt=spec.prompt,
                    origin="system",
                )
            except Exception as exc:
                logger.exception(
                    "Trigger '{}': autonomous turn failed", spec.trigger_id,
                )
                if self._background_tasks is not None and task_id is not None:
                    await self._background_tasks.fail(task_id, error=str(exc))
                return
            if self._background_tasks is not None and task_id is not None:
                await self._background_tasks.complete(task_id)
            if self._attention is not None:
                await self._attention.request_attention(
                    source=f"trigger:{spec.trigger_id}",
                    message=(
                        f"Autonomous turn for trigger '{spec.trigger_id}' completed"
                    ),
                    conversation_id=spec.conversation_id,
                )
```

- [ ] **Step 6.4: verifica che passino**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_trigger_service.py -v`
Expected: PASS 7/7.

- [ ] **Step 6.5: config**

In `backend/core/config.py`, dopo `AttentionConfig`:

```python
class TriggersConfig(BaseSettings):
    """TriggerService policy (Fase 8, spec §8)."""

    model_config = SettingsConfigDict(env_prefix="ALICE_TRIGGERS__")

    enabled: bool = True
    """Master switch for autonomous-turn triggers (none registered by default)."""
    max_concurrent_turns: int = 1
    """Autonomous turns that may run at once; extra fires are skipped."""
```

In `AliceConfig`, dopo il campo `attention`:

```python
    triggers: TriggersConfig = Field(default_factory=TriggersConfig)
    """Autonomous-turn trigger policy (Fase 8)."""
```

In `config/default.yaml`, dopo la sezione `attention`:

```yaml
# Fondamenta Jarvis (spec §8): autonomous-turn trigger sources.
triggers:
  enabled: true
  max_concurrent_turns: 1         # extra fires are skipped, not queued
```

In `docs/flag-registry.md`, nuova riga:

```
| `triggers.enabled` | true | `bootstrap/jarvis.py`, `services/trigger_service.py` | spegne i turni autonomi (nessun trigger registrato di default) |
```

- [ ] **Step 6.6: gate e commit**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_trigger_service.py -v`
Run (da `backend/`): `..\.venv\Scripts\ruff.exe check services/trigger_service.py tests/test_trigger_service.py core/config.py`
Run (dalla REPO ROOT): `.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml`
Expected: verde.

```bash
git add backend/services/trigger_service.py backend/tests/test_trigger_service.py backend/core/config.py config/default.yaml docs/flag-registry.md
git commit -m "feat(jarvis): TriggerService - schedule/event/manual autonomous turns with agent-origin anti-echo (fase 8)"
```

---

### Task 7: Bootstrap `stage_jarvis` + shutdown

**Files:**
- Create: `backend/core/bootstrap/jarvis.py`
- Modify: `backend/core/bootstrap/__init__.py` (export)
- Modify: `backend/core/app.py` (chiamata stage, dopo `stage_workspace`)
- Modify: `backend/core/bootstrap/shutdown.py` (blocco trigger, PRIMO della sequenza)
- Test: gate = boot dell'app (`tests/test_app.py`)

- [ ] **Step 7.1: stage**

Create `backend/core/bootstrap/jarvis.py`:

```python
"""Stage: Fondamenta Jarvis — background tasks, attention, triggers (Fase 8)."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from backend.core.context import AppContext


async def stage_jarvis(ctx: AppContext) -> None:
    """Create the Fase 8 kernel services and wire the autonomous-turn seam.

    Runs LAST: it needs the event bus (platform), the events-WS bridges
    (surfaces) and the fully-wired turn pipeline (workspace) already up.
    The headless turn runner lives in the api layer; injecting it here is
    the sanctioned composition-root exception
    (``backend.core.bootstrap.* -> backend.api.**``).
    """
    from backend.api.routes.chat.headless import run_headless_turn
    from backend.services.attention_service import AttentionService
    from backend.services.background_tasks import BackgroundTaskService
    from backend.services.trigger_service import TriggerService

    ctx.background_task_service = BackgroundTaskService(event_bus=ctx.event_bus)

    ctx.attention_service = AttentionService(
        event_bus=ctx.event_bus,
        enabled=ctx.config.attention.enabled,
        cooldown_s=ctx.config.attention.cooldown_s,
    )

    trigger_service = TriggerService(
        event_bus=ctx.event_bus,
        turn_runner=partial(run_headless_turn, ctx),
        background_tasks=ctx.background_task_service,
        attention=ctx.attention_service,
        enabled=ctx.config.triggers.enabled,
        max_concurrent_turns=ctx.config.triggers.max_concurrent_turns,
    )
    ctx.trigger_service = trigger_service
    await trigger_service.start()

    logger.info(
        "Jarvis foundations ready (triggers={}, attention={})",
        ctx.config.triggers.enabled,
        ctx.config.attention.enabled,
    )
```

- [ ] **Step 7.2: wiring**

1. In `backend/core/bootstrap/__init__.py`: aggiungi `stage_jarvis` all'export, stile degli altri stage.
2. In `backend/core/app.py`, dopo `await stage_workspace(ctx)` (riga ~59):

```python
        await stage_jarvis(ctx)
```

(aggiorna anche l'import degli stage in testa al lifespan, stesso stile).

3. In `backend/core/bootstrap/shutdown.py`, PRIMO blocco della sequenza (prima dell'orchestrator — i turni autonomi si fermano prima di tutto):

```python
    if ctx.trigger_service is not None:
        try:
            await ctx.trigger_service.shutdown()
        except Exception as exc:
            logger.error("Trigger service shutdown error: {}", exc)
```

- [ ] **Step 7.3: gate boot**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_app.py -v`
Expected: PASS (il boot include ora `stage_jarvis`; NESSUN trigger registrato = nessun comportamento nuovo). NON killare il run se lento (fixture app ~25s).

Run (dalla REPO ROOT): `.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml`
Expected: verde (l'import api dentro `stage_jarvis` è nella whitelist `backend.core.bootstrap.* -> backend.api.**`).

- [ ] **Step 7.4: commit**

```bash
git add backend/core/bootstrap/jarvis.py backend/core/bootstrap/__init__.py backend/core/app.py backend/core/bootstrap/shutdown.py
git commit -m "feat(jarvis): stage_jarvis bootstrap - wire background tasks, attention, triggers (fase 8)"
```

---

### Task 8: Subagent nella policy centrale + osservabilità

**Files:**
- Modify: `backend/services/permission_service.py` (nuovo metodo `explain_denial`)
- Modify: `backend/plugins/agent/_subagent.py` (gate per-call + `progress_cb`)
- Modify: `backend/plugins/agent/plugin.py` (`_spawn_subagent`: background task)
- Test: `backend/tests/test_permission_service.py` (esistente), `backend/tests/test_agent_plugin.py` (esistente — contiene già i test di `run_subagent` con gli helper `_make_ctx_with_services`/`_tool_entry`)

- [ ] **Step 8.1: test `explain_denial` (fallirà)**

In coda a `backend/tests/test_permission_service.py` aggiungi (gli import di `PermissionService`, `PermissionMode` e `ToolDefinition` esistono già in testa al file — verifica e riusa quelli; costruttori keyword come nei test vicini):

```python
def test_explain_denial_allow_returns_none() -> None:
    svc = PermissionService()
    assert (
        svc.explain_denial(
            tool_name="calendar_list",
            args={},
            tool_def=None,
            conversation_id="c1",
            mode=PermissionMode.AUTOPILOT,
        )
        is None
    )


def test_explain_denial_needs_confirmation_is_clean_denial() -> None:
    """A confirmation verdict is a denial on surfaces with no user to ask."""
    svc = PermissionService()
    tool_def = ToolDefinition(
        name="danger_tool",
        description="Confirmation-gated test tool",
        requires_confirmation=True,
        risk_level="dangerous",
    )
    message = svc.explain_denial(
        tool_name="danger_tool",
        args={},
        tool_def=tool_def,
        conversation_id="c1",
        mode=PermissionMode.STRICT,
    )
    assert message is not None
    assert "confirmation" in message


def test_explain_denial_forbidden_is_denied_with_reason() -> None:
    svc = PermissionService()
    tool_def = ToolDefinition(
        name="forbidden_tool",
        description="Forbidden test tool",
        risk_level="forbidden",
    )
    message = svc.explain_denial(
        tool_name="forbidden_tool",
        args={},
        tool_def=tool_def,
        conversation_id="c1",
        mode=PermissionMode.AUTOPILOT,
    )
    assert message is not None
    assert "denied" in message


def test_explain_denial_none_mode_falls_back_to_strict() -> None:
    svc = PermissionService()
    tool_def = ToolDefinition(
        name="danger_tool",
        description="Confirmation-gated test tool",
        requires_confirmation=True,
        risk_level="dangerous",
    )
    # None mode is coerced to STRICT (fail-conservative) → clean denial.
    message = svc.explain_denial(
        tool_name="danger_tool",
        args={},
        tool_def=tool_def,
        conversation_id="c1",
        mode=None,
    )
    assert message is not None
```

(Se `ToolDefinition` richiede altri campi obbligatori, replica ESATTAMENTE la factory di `backend/tests/test_confirmation_toggle.py:47-52`.)

- [ ] **Step 8.2: implementa `explain_denial`**

In `backend/services/permission_service.py`, dopo `decide` (il metodo usa `GateAction` e `PermissionMode`, già importati/nel modulo):

```python
    def explain_denial(
        self,
        *,
        tool_name: str,
        args: dict[str, object],
        tool_def: ToolDefinition | None,
        conversation_id: str,
        mode: PermissionMode | None,
    ) -> str | None:
        """Gate one call for surfaces that have no confirmation UI (Fase 8).

        Same policy as a normal turn (spec §4.5: no privileged path), but a
        ``NEEDS_CONFIRMATION`` verdict is a *denial* here: headless surfaces
        (sub-agents, autonomous turns) have no user to ask — the Fase 7
        clean-result philosophy.

        Returns:
            ``None`` when the call may run, else a human-readable reason.
        """
        if mode is None:
            mode = PermissionMode.STRICT
        decision = self.decide(
            tool_name=tool_name,
            args=args,
            tool_def=tool_def,
            conversation_id=conversation_id,
            mode=mode,
        )
        if decision.action is GateAction.ALLOW:
            return None
        if decision.action is GateAction.NEEDS_CONFIRMATION:
            return (
                f"Tool '{tool_name}' requires user confirmation, which is "
                "not available in this context."
            )
        reason = f" ({decision.reason})" if decision.reason else ""
        return f"Tool '{tool_name}' denied by permission policy{reason}."
```

(Se `PermissionMode` non è già importato in `permission_service.py`, aggiungi l'import esistente usato dalla firma di `decide` — è già lì per il tipo del parametro `mode`.)

Run: i test dello step 8.1 → PASS.

- [ ] **Step 8.3: gate nel runner subagent + progress_cb (test first)**

In coda alla classe di test del subagent in `backend/tests/test_agent_plugin.py` (quella che contiene `test_subagent_uses_tool_then_answers`), aggiungi — riusando ESATTAMENTE gli helper del file (`_make_ctx_with_services`, `_tool_entry`, `_make_exec_ctx`, `run_subagent` già importato a riga ~36):

```python
    @pytest.mark.asyncio
    async def test_subagent_denied_tool_is_not_executed(self):
        """A gate denial becomes an ERROR tool-result; execute_tool never runs."""
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {
                        "type": "tool_call",
                        "id": "call_1",
                        "function": {"name": "system_info_get", "arguments": "{}"},
                    },
                    {"type": "done", "finish_reason": "tool_calls"},
                ],
                [
                    {"type": "token", "content": "could not use the tool"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            ],
            tools=[_tool_entry("system_info_get")],
        )

        class _DenyingGate:
            calls: list[str] = []

            def explain_denial(self, *, tool_name, args, tool_def,
                               conversation_id, mode):
                self.calls.append(tool_name)
                return f"Tool '{tool_name}' denied by permission policy (test)."

        ctx.permission_service = _DenyingGate()
        executed: list[str] = []
        original_execute = ctx.tool_registry.execute_tool

        async def _spy_execute(name, args, exec_ctx):
            executed.append(name)
            return await original_execute(name, args, exec_ctx)

        ctx.tool_registry.execute_tool = _spy_execute  # type: ignore[method-assign]

        result = await run_subagent(
            ctx=ctx,
            task="get system info",
            context=None,
            allowed_tools=None,
            max_steps=3,
            max_output_tokens=128,
            timeout_seconds=10.0,
            max_tools=8,
            conversation_id="c",
            session_id="s",
        )
        assert result.stop_reason == "completed"
        assert executed == []
        assert _DenyingGate.calls == ["system_info_get"]

    @pytest.mark.asyncio
    async def test_subagent_allowed_by_gate_executes(self):
        """explain_denial → None lets the call through to execute_tool."""
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {
                        "type": "tool_call",
                        "id": "call_1",
                        "function": {"name": "system_info_get", "arguments": "{}"},
                    },
                    {"type": "done", "finish_reason": "tool_calls"},
                ],
                [
                    {"type": "token", "content": "done"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            ],
            tools=[_tool_entry("system_info_get")],
        )

        class _AllowingGate:
            def explain_denial(self, **kwargs):
                return None

        ctx.permission_service = _AllowingGate()
        result = await run_subagent(
            ctx=ctx,
            task="get system info",
            context=None,
            allowed_tools=None,
            max_steps=3,
            max_output_tokens=128,
            timeout_seconds=10.0,
            max_tools=8,
            conversation_id="c",
            session_id="s",
        )
        assert result.tools_called == ["system_info_get"]

    @pytest.mark.asyncio
    async def test_subagent_progress_cb_called_per_step(self):
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {"type": "token", "content": "the answer"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            ],
        )
        progress: list[tuple[int, int, str]] = []

        async def _cb(step: int, total: int, note: str) -> None:
            progress.append((step, total, note))

        result = await run_subagent(
            ctx=ctx,
            task="quick",
            context=None,
            allowed_tools=None,
            max_steps=3,
            max_output_tokens=128,
            timeout_seconds=10.0,
            max_tools=8,
            conversation_id="c",
            session_id="s",
            progress_cb=_cb,
        )
        assert result.stop_reason == "completed"
        assert progress == [(1, 3, "step 1/3")]
```

NOTE: (a) se `_make_ctx_with_services` costruisce un ctx senza attributo assegnabile `permission_service`, assegna via `ctx.workspace.permission_service = ...` (il ctx reale delega al gruppo); (b) `_DenyingGate.calls` è di classe: azzerala a inizio test se il runner la riusa; (c) verifica il nome esatto della classe di test contenitore e l'indentazione dei metodi.

- [ ] **Step 8.4: implementa nel runner**

In `backend/plugins/agent/_subagent.py`:

1. Aggiungi in testa (dopo gli import esistenti):

```python
from collections.abc import Awaitable, Callable
import contextlib

ProgressCallback = Callable[[int, int, str], Awaitable[None]]
"""(step, max_steps, note) — reports sub-agent progress (Fase 8)."""
```

2. Nuovo helper modulo-level (dopo `_resolve_subagent_tools`):

```python
def _gate_tool_call(
    ctx: AppContext, name: str, args: dict[str, Any], conversation_id: str,
) -> str | None:
    """Consult the central permission gate for one sub-agent tool call.

    Same policy as a normal turn (spec §4.5/§8: no privileged path): the
    PARENT conversation's permission mode and scope apply. Accessed via
    ``ctx`` duck-typed — plugins never import services classes directly.

    Returns:
        ``None`` when allowed, else the human-readable denial.
    """
    permission_service = getattr(ctx, "permission_service", None)
    if permission_service is None:
        return None
    registry = ctx.tool_registry
    tool_def = registry.get_tool_definition(name) if registry is not None else None
    mode_service = getattr(ctx, "permission_mode_service", None)
    mode = mode_service.get_mode(conversation_id) if mode_service is not None else None
    denial: str | None = permission_service.explain_denial(
        tool_name=name,
        args=args,
        tool_def=tool_def,
        conversation_id=conversation_id,
        mode=mode,
    )
    return denial
```

3. In `_run_loop`: aggiungi il parametro `progress_cb: ProgressCallback | None = None` alla firma; a inizio di ogni iterazione del `for step in range(max_steps):` (subito dopo `result.steps_used = step + 1`):

```python
        if progress_cb is not None:
            with contextlib.suppress(Exception):
                await progress_cb(step + 1, max_steps, f"step {step + 1}/{max_steps}")
```

4. Sempre in `_run_loop`, nel ciclo dei tool_calls, PRIMA di `exec_ctx = ExecutionContext(...)` (riga ~195):

```python
            denial = _gate_tool_call(ctx, name, args, conversation_id)
            if denial is not None:
                result.tools_called.append(name)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": f"ERROR: {denial}",
                    },
                )
                continue
```

5. In `run_subagent`: aggiungi `progress_cb: ProgressCallback | None = None` alla firma (documentalo nel docstring Args) e passalo a `_run_loop(...)`.

- [ ] **Step 8.5: osservabilità in `_spawn_subagent`**

In `backend/plugins/agent/plugin.py`, dentro `_spawn_subagent` (riga ~438), sostituisci il blocco da `start = time.perf_counter()` fino alla chiamata `run_subagent(...)` inclusa con:

```python
        start = time.perf_counter()
        logger.info("spawn_subagent: delegating task: {}", task[:120])

        bts = getattr(self._ctx, "background_task_service", None)
        bg_task_id: str | None = None
        if bts is not None:
            bg_task_id = await bts.start(
                kind="subagent",
                label=task[:80],
                conversation_id=context.conversation_id,
            )

        async def _report(step: int, total: int, note: str) -> None:
            if bts is not None and bg_task_id is not None:
                await bts.update(
                    bg_task_id, progress=step / max(total, 1), detail=note,
                )

        result = await run_subagent(
            ctx=self._ctx,
            task=task,
            context=extra_context,
            allowed_tools=allowed_tools,
            max_steps=cfg.max_steps,
            max_output_tokens=cfg.max_output_tokens,
            timeout_seconds=cfg.timeout_seconds,
            max_tools=cfg.max_tools,
            conversation_id=context.conversation_id,
            session_id=context.session_id,
            progress_cb=_report if bts is not None else None,
        )
```

e subito dopo `elapsed = ...` aggiungi:

```python
        if bts is not None and bg_task_id is not None:
            if result.stop_reason == "error":
                await bts.fail(bg_task_id, error=result.error or "unknown")
            else:
                await bts.complete(bg_task_id, detail=result.stop_reason)
```

- [ ] **Step 8.6: verifica**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_agent_plugin.py tests/test_permission_service.py -v`
Expected: PASS tutti, inclusi i test pre-esistenti del subagent (il gate con `permission_service` assente/None è un no-op → i vecchi test non devono rompersi).

- [ ] **Step 8.7: gate e commit**

Run (da `backend/`): `..\.venv\Scripts\ruff.exe check plugins/agent/_subagent.py plugins/agent/plugin.py services/permission_service.py` (+ i file di test toccati)
Run (dalla REPO ROOT): `.\.venv\Scripts\lint-imports.exe --config backend/pyproject.toml`
Expected: verde (il plugin NON importa moduli services: accesso solo via `ctx`).

```bash
git add backend/services/permission_service.py backend/plugins/agent/_subagent.py backend/plugins/agent/plugin.py <file di test toccati>
git commit -m "feat(jarvis): subagent tool calls pass the central permission gate + observable progress (fase 8)"
```

---

### Task 9: Voce — attivazione del seam `agent.voice.max_tools`

**Files:**
- Modify: `backend/api/routes/chat/_assembly.py` (helper `_apply_voice_trim` + chiamata)
- Modify: `docs/flag-registry.md`
- Test: `backend/tests/test_voice_trim.py`

- [ ] **Step 9.1: test (fallirà)**

Create `backend/tests/test_voice_trim.py`:

```python
"""Tests for the Fase 8 voice toolset trim (agent.voice.max_tools)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.api.routes.chat._assembly import _apply_voice_trim


def _tools(n: int) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": f"tool_{i}", "parameters": {}}}
        for i in range(n)
    ]


class _FakeRegistry:
    def limit_tools(
        self,
        tools: list[dict[str, Any]],
        *,
        max_tools: int,
        priority_plugins: list[str],
    ) -> list[dict[str, Any]]:
        return tools[:max_tools]


def _ctx(voice_cap: int) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(
            agent=SimpleNamespace(voice=SimpleNamespace(max_tools=voice_cap)),
            llm=SimpleNamespace(priority_plugins=[]),
        ),
        tool_registry=_FakeRegistry(),
    )


def test_voice_source_trims_toolset() -> None:
    trimmed = _apply_voice_trim(_ctx(3), _tools(10), source="voice")
    assert trimmed is not None
    assert len(trimmed) == 3


def test_text_source_is_untouched() -> None:
    tools = _tools(10)
    assert _apply_voice_trim(_ctx(3), tools, source="text") is tools
    assert _apply_voice_trim(_ctx(3), tools, source=None) is tools


def test_zero_cap_disables_trim() -> None:
    tools = _tools(10)
    assert _apply_voice_trim(_ctx(0), tools, source="voice") is tools


def test_small_toolset_is_untouched() -> None:
    tools = _tools(2)
    assert _apply_voice_trim(_ctx(3), tools, source="voice") is tools


def test_none_tools_pass_through() -> None:
    assert _apply_voice_trim(_ctx(3), None, source="voice") is None
```

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_voice_trim.py -v`
Expected: FAIL (`_apply_voice_trim` non esiste).

- [ ] **Step 9.2: implementa**

In `backend/api/routes/chat/_assembly.py`, funzione modulo-level (vicino agli altri helper del modulo):

```python
def _apply_voice_trim(
    ctx: Any, tools: list[dict[str, Any]] | None, *, source: str | None,
) -> list[dict[str, Any]] | None:
    """Trim the toolset for voice turns (Fase 8, ``agent.voice.max_tools``).

    Voice favours a fast first token over broad tool coverage; the gating
    policy stays identical — only the offered surface shrinks. ``0``
    disables the trim.
    """
    if source != "voice" or not tools:
        return tools
    voice_cap = ctx.config.agent.voice.max_tools
    if voice_cap <= 0 or len(tools) <= voice_cap:
        return tools
    if ctx.tool_registry is None:
        return tools
    return ctx.tool_registry.limit_tools(
        tools,
        max_tools=voice_cap,
        priority_plugins=ctx.config.llm.priority_plugins,
    )
```

Poi in `assemble`, nel blocco di tool selection, SUBITO DOPO il cap generico `ctx.config.llm.max_tools` (righe ~410-415) e PRIMA di `apply_mode_policy`:

```python
                # Fase 8: voice turns get a trimmed toolset for latency
                # (same gating policy, smaller offered surface).
                tools = _apply_voice_trim(ctx, tools, source=data.get("source"))
```

(Attenzione all'indentazione reale del blocco: allineala al codice circostante.)

In `docs/flag-registry.md` aggiorna la riga di `agent.voice.max_tools` (oggi segnata come seam non letto): letto da `api/routes/chat/_assembly.py`, nota «trim del toolset per turni voce (source=voice), attivato in fase 8».

- [ ] **Step 9.3: verifica, gate e commit**

Run (da `backend/`): `..\.venv\Scripts\python.exe -m pytest tests/test_voice_trim.py tests/contracts/ -v`
Run (da `backend/`): `..\.venv\Scripts\ruff.exe check api/routes/chat/_assembly.py tests/test_voice_trim.py`
Expected: verde.

```bash
git add backend/api/routes/chat/_assembly.py backend/tests/test_voice_trim.py docs/flag-registry.md
git commit -m "feat(voice): activate agent.voice.max_tools - per-message source drives the voice tool trim (fase 8)"
```

---

### Task 10: Regen contratti (task del CONTROLLER — gate auto-verificante)

**Files:**
- Regenerate: `frontend/src/renderer/src/types/generated/openapi.json`, `frontend/src/renderer/src/types/generated/api.d.ts`

- [ ] **Step 10.1: regen**

Run (dalla REPO ROOT): `.\scripts\gen-contracts.ps1`
Expected: "Contracts regenerated." — il diff mostra i due frame events nuovi + `source` su `WsUserMessage`.

- [ ] **Step 10.2: commit + check**

```bash
git add frontend/src/renderer/src/types/generated/openapi.json frontend/src/renderer/src/types/generated/api.d.ts
git commit -m "chore(contracts): regenerate for fase 8 frames (background_task, attention, voice source)"
```

Run (dalla REPO ROOT): `.\scripts\check-contracts.ps1`
Expected: "Contracts are up to date."

NOTA: da questo momento `npm run typecheck` nel FE FALLISCE (il dispatcher esaustivo non gestisce i 2 frame nuovi) — è il compile-error di design che il Task 11 risolve. Non eseguire gate FE tra Task 10 e Task 11.

---

### Task 11: Frontend — store `backgroundTasks`, handler dispatcher, toast attention, source voce

**Files:**
- Create: `frontend/src/renderer/src/stores/backgroundTasks.ts`
- Modify: `frontend/src/renderer/src/composables/useEventsWebSocket.ts` (2 handler)
- Modify: `frontend/src/renderer/src/composables/useChat.ts` (param `options.source`)
- Modify: `frontend/src/renderer/src/views/HorizonView.vue` (transcript → source voice)
- Test: vitest per lo store (posizionalo accanto ai test store esistenti — trova la convenzione con `Glob frontend/**/*.spec.ts` / `*.test.ts`)

- [ ] **Step 11.1: store**

Create `frontend/src/renderer/src/stores/backgroundTasks.ts` (per il tipo del frame usa lo stesso helper di tipi generati usato da `stores/tasks.ts`/`types/chat.ts` — es. `ApiSchema<'WsBackgroundTaskUpdated'>`; verifica l'import esatto in `types/chat.ts:139`):

```typescript
/**
 * AL\CE — Observable background tasks (Fase 8, spec §8).
 *
 * Fed exclusively by `background_task.updated` frames on the events WS;
 * frames carry the FULL task snapshot, so applying one is a plain fold.
 * In-memory only: the backend registry is ephemeral by design.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ApiSchema } from '../types/api'

export type BackgroundTaskInfo = ApiSchema<'WsBackgroundTaskUpdated'>

export const useBackgroundTasksStore = defineStore('backgroundTasks', () => {
  /** Latest snapshot per task id. */
  const byId = ref<Record<string, BackgroundTaskInfo>>({})

  /** Every known task, unordered. */
  const all = computed(() => Object.values(byId.value))

  /** Tasks still running (subagents, autonomous turns). */
  const active = computed(() => all.value.filter((t) => t.status === 'running'))

  function applyBackgroundTaskUpdated(msg: BackgroundTaskInfo): void {
    byId.value = { ...byId.value, [msg.task_id]: msg }
  }

  function reset(): void {
    byId.value = {}
  }

  return { byId, all, active, applyBackgroundTaskUpdated, reset }
})
```

(L'import `from '../types/api'` è INDICATIVO: usa il modulo reale da cui `types/chat.ts` importa `ApiSchema` — riga 139 di quel file.)

- [ ] **Step 11.2: handler dispatcher**

In `frontend/src/renderer/src/composables/useEventsWebSocket.ts`:

1. Import in testa (stile esistente):

```typescript
import { useBackgroundTasksStore } from '../stores/backgroundTasks'
import { useToast } from './useToast'
```

2. Istanzia lo store accanto agli altri (righe ~65-74): `const backgroundTasksStore = useBackgroundTasksStore()`.
3. Nuove entry nel map `handlers` (righe ~84-114):

```typescript
    'background_task.updated': (msg) => backgroundTasksStore.applyBackgroundTaskUpdated(msg),
    'attention.raised': (msg) => {
      const toast = useToast()
      if (msg.priority === 'urgent') toast.warning(msg.message)
      else toast.info(msg.message)
    },
```

(Se il tipo `Extract<...>` del frame e `BackgroundTaskInfo` divergono nominalmente, tipizza il parametro dello store col tipo del frame generato — sono lo stesso schema.)

- [ ] **Step 11.3: source voce**

In `frontend/src/renderer/src/composables/useChat.ts`:

1. Firma di `sendMessage` (riga ~360):

```typescript
  async function sendMessage(
    content: string,
    conversationId?: string,
    attachments?: File[],
    options?: { source?: 'text' | 'voice' }
  ): Promise<void> {
```

2. Payload (riga ~416):

```typescript
    const payload: WsSendPayload = {
      content: trimmed,
      conversation_id: convId,
      attachments: uploaded?.map((a) => a.file_id),
      ...(options?.source ? { source: options.source } : {})
    }
```

In `frontend/src/renderer/src/views/HorizonView.vue`, nel watcher del transcript STT (riga ~317), cambia `send(spoken).catch(console.error)` in:

```typescript
      send(spoken, undefined, undefined, { source: 'voice' }).catch(console.error)
```

(Verifica che `send` sia l'alias di `sendMessage` di useChat — se la destrutturazione lo rinomina, adegua la chiamata mantenendo il 4° argomento.)

- [ ] **Step 11.4: vitest dello store**

Crea il test accanto ai test store esistenti (stessa cartella/naming — scoprila con Glob; contenuto):

```typescript
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useBackgroundTasksStore } from '<path-relativo-reale>/stores/backgroundTasks'

function frame(overrides: Record<string, unknown> = {}) {
  return {
    type: 'background_task.updated' as const,
    origin: 'agent' as const,
    task_id: 'bt-1',
    kind: 'subagent',
    label: 'Research',
    status: 'running' as const,
    progress: 0.5,
    detail: 'step 3/6',
    conversation_id: 'c1',
    updated_at: '2026-07-11T12:00:00+00:00',
    ...overrides
  }
}

describe('backgroundTasks store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('folds full snapshots by task id', () => {
    const store = useBackgroundTasksStore()
    store.applyBackgroundTaskUpdated(frame())
    store.applyBackgroundTaskUpdated(frame({ status: 'completed', progress: 1 }))
    expect(store.all).toHaveLength(1)
    expect(store.byId['bt-1'].status).toBe('completed')
  })

  it('active filters running tasks', () => {
    const store = useBackgroundTasksStore()
    store.applyBackgroundTaskUpdated(frame())
    store.applyBackgroundTaskUpdated(frame({ task_id: 'bt-2', status: 'failed' }))
    expect(store.active.map((t) => t.task_id)).toEqual(['bt-1'])
  })

  it('reset clears everything', () => {
    const store = useBackgroundTasksStore()
    store.applyBackgroundTaskUpdated(frame())
    store.reset()
    expect(store.all).toHaveLength(0)
  })
})
```

(Adatta l'import del frame al tipo generato se il typecheck lo richiede — cast `as BackgroundTaskInfo` accettabile nel test.)

- [ ] **Step 11.5: gate FE completo**

Run (da `frontend/`): `npm run typecheck`
Expected: 0 errori (il dispatcher torna esaustivo).
Run (da `frontend/`): `npm run lint`
Expected: 0 errors / 0 warnings.
Run (da `frontend/`): `npm test`
Expected: tutti verdi (301 pre-esistenti + i nuovi).

- [ ] **Step 11.6: commit**

```bash
git add frontend/src/renderer/src/stores/backgroundTasks.ts frontend/src/renderer/src/composables/useEventsWebSocket.ts frontend/src/renderer/src/composables/useChat.ts frontend/src/renderer/src/views/HorizonView.vue <file vitest nuovo>
git commit -m "feat(fe): backgroundTasks store + attention toast + voice source on send (fase 8)"
```

---

### Task 12: Documentazione

**Files:**
- Modify: `CLAUDE.md` (sezione "Backend architecture")
- Modify: `docs/flag-registry.md` (verifica finale delle 3 righe nuove: attention.enabled, triggers.enabled, agent.voice.max_tools aggiornata)

- [ ] **Step 12.1: CLAUDE.md**

In `CLAUDE.md`, nella sezione "Backend architecture (the big picture)", dopo il punto sul Command Bridge (dentro il punto 3), aggiungi un punto:

```markdown
   - **Fondamenta Jarvis (spec §8)** — tre service kernel posati in fase 8 (interfacce, non implementazioni ricche): `services/trigger_service.py` (`TriggerService`: turni autonomi da schedule/eventi bus/manual, filtro anti-eco sugli eventi con `origin="agent"`; il turno autonomo è un turno NORMALE via `api/routes/chat/headless.py::run_headless_turn` — stesso assembly/executor/permission/scope, `NullEventSink` + `HeadlessInteractionChannel` che auto-declina le richieste interattive), `services/attention_service.py` (`AttentionService`: punto unico e disattivabile dell'iniziativa agente→utente, `attention.raised` → toast), `services/background_tasks.py` (`BackgroundTaskService`: task in background osservabili, frame `background_task.updated` → store FE `backgroundTasks`). Wiring in `bootstrap/jarvis.py` (ultimo stage). Il subagent passa dal gate centrale (`PermissionService.explain_denial`, conferma = negazione pulita); i turni voce (frame `source: "voice"`) attivano il trim `agent.voice.max_tools`. Config `triggers.*`, `attention.*`.
```

Aggiorna anche l'elenco store Pinia nella sezione Frontend architecture: aggiungi `backgroundTasks`.

- [ ] **Step 12.2: commit**

```bash
git add CLAUDE.md docs/flag-registry.md
git commit -m "docs: fondamenta Jarvis in CLAUDE.md + flag registry (fase 8)"
```

---

## Gate finale di fase (criteri §9)

- [ ] Test mirati fase 8 tutti verdi: `tests/test_background_tasks.py tests/test_attention_service.py tests/test_trigger_service.py tests/test_headless_turn.py tests/test_voice_trim.py tests/test_agent_plugin.py tests/test_permission_service.py tests/contracts/` (da `backend/`).
- [ ] `tests/test_app.py` verde (app avviabile con stage_jarvis).
- [ ] `lint-imports` verde dalla repo root.
- [ ] FE: `npm run typecheck` + `npm run lint` (0/0) + `npm test` verdi.
- [ ] `check-contracts.ps1` verde DOPO l'ultimo commit.
- [ ] `git ls-files --eol` senza flip EOL sui file toccati.
- [ ] Review FINALE di fase (modello top, range intero `main..HEAD`, angolo cross-task) — SEMPRE, anche se i task-review sono verdi.
- [ ] Smoke funzionale interattivo (`npm run dev`): PENDENTE anche per fasi 6 e 7 — alla prima apertura eseguire le TRE checklist (gate finale piano 6, step 9.6 piano 7, e per la fase 8: toast attention visibile forzando un `attention.raised` dal backend, store backgroundTasks popolato da uno spawn_subagent, turno voce con toolset ridotto nei log).

## Backlog fase 8 (fuori scope, registrare nell'handoff)

1. Superficie di registrazione trigger (tool agent + REST CRUD + persistenza DB) e cron/RRULE reali.
2. Route REST `GET /api/background-tasks` per idratazione iniziale dello store (oggi WS-only).
3. Campo provenance/origin su `Message` (DB) per distinguere i turni autonomi nella UI.
4. Spostare `TurnAssembler`/`_persist_final_turn` da `api/` a `services/turn/` (il runner headless smette di vivere in api).
5. AttentionService ricco: code con drain, INTERRUPT reale (voce/focus), preferenze per-sorgente.
6. UI Horizon dedicata per i background task (oggi solo store + toast).
7. Ereditati fase 7: grant per-comando, capability nel frame di conferma, esenzione dedup ui_command, hook change-notification manifest, cap usage_guidance, clamp rpc_timeout_s.
