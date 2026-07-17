# Agent v2 Fase 1 — Mossa 1: Motore greenfield + parità + swap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Costruire `AgentEngine` greenfield in `backend/services/agent/`, provarne la
parità comportamentale col motore legacy tramite parity adapter, swappare il default e
demolire `backend/services/turn/` per intero.

**Architecture:** Motore a loop unificato (nessun caso speciale per il primo step) che
parla SOLO attraverso 7 porte (`Protocol`); adapter separati collegano le porte alla
piattaforma (LLMService, PermissionService, ToolRegistry, ContextManager, SQLModel, WS).
Un parity adapter throwaway traduce gli eventi interni nel wire attuale, così la parità si
prova confrontando gli stream frame v1/v2 sugli stessi scenari scriptati.

**Tech Stack:** Python 3.11+ (target ruff py313), FastAPI/Starlette WS, SQLModel/aiosqlite,
pydantic v2, pytest (asyncio_mode=auto), loguru.

**Spec:** `docs/superpowers/specs/2026-07-17-agent-engine-fase1-design.md` (leggerla PRIMA
di ogni task). Programma: `docs/superpowers/specs/2026-07-16-agent-v2-program-design.md`.

## Global Constraints

- **PRINCIPIO PILASTRO:** zero import da `backend/services/turn/` dentro
  `backend/services/agent/` e `backend/tests/agent/` (contratto import-linter dal Task 1).
  Non leggere i file di `services/turn/` come modello di design; l'unico input dal legacy
  è la checklist invarianti (spec §6). Vale anche per i test double.
- Type hints su tutti i parametri e ritorni; `async def` per ogni I/O; `loguru.logger`;
  `pathlib.Path`; docstring Google-style; riga max 100; mypy strict a parità.
- I modelli evento/DTO sono **pydantic v2 `frozen=True`** o dataclass `frozen=True, slots=True`.
- pytest: SEMPRE in foreground nei dispatch subagent; mai due pytest concorrenti; mai la
  suite integrale come gate (AUD-008) — solo i sottoinsiemi indicati nei task.
- Commit frequenti sul branch `feat/agent-engine-fase1`; messaggi in italiano stile repo
  (`feat(engine): …`, `test(engine): …`).
- Nessuna modifica ai contratti WS in Mossa 1: il wire resta IDENTICO (il vocabolario v2
  arriva in Mossa 2, piano separato).
- `finish_reason` mantiene il vocabolario legacy: `"stop" | "length" | "cancelled" |
  "disconnected" | "error"` (l'eval `finished_ok` controlla `stop`).

## File Structure (Mossa 1)

```
backend/services/agent/
  __init__.py          # export pubblici: AgentEngine, TurnRequest, TurnOutcome
  models.py            # TurnRequest, TurnOutcome, ToolInvocation, ToolMeta, TurnSource, StopReason
  events.py            # AgentEvent: modelli evento interni tipizzati (vocabolario v2 + diagnostici)
  ports.py             # 7 Protocol: LLMPort, PermissionPort, InteractionPort, EventPort,
                       #   PersistencePort, ContextPort, ExecutionPort (+ tipi di supporto)
  dedup.py             # hash normalizzato + DedupRegistry cross-step
  retry.py             # RetryPolicy (empty-response nudge, transient vs fail-fast)
  stop.py              # BudgetTracker + StopReason → finish_reason
  engine.py            # AgentEngine: il loop unificato
  adapters/
    __init__.py
    llm.py             # LLMService.chat → LLMPort (chunk dict → eventi tipizzati)
    permission.py      # PermissionService/mode/rules/scope → PermissionPort (mode per-call)
    execution.py       # ToolRegistry.execute_tool → ExecutionPort (+ ToolMeta dal catalogo)
    context.py         # ContextManager → ContextPort
    db.py              # PersistencePort su AsyncSession (unit-of-work, audit, artifact)
    ws.py              # EventPort + InteractionPort su WebSocket (read-pump nuovo)
    parity.py          # THROWAWAY: AgentEvent → frame wire attuali (legacy + canonici)
backend/tests/agent/
  __init__.py, conftest.py
  doubles.py           # ScriptedLLMPort, RecordingEventPort, InMemoryPersistence,
                       #   StaticPermissionPort, ScriptedInteractionPort, NoopContextPort,
                       #   MapExecutionPort
  test_models.py, test_events.py, test_dedup.py, test_retry.py, test_stop.py
  test_engine_single_step.py, test_engine_tools.py, test_engine_loop.py,
  test_engine_compaction.py
  test_adapter_llm.py, test_adapter_permission.py, test_adapter_db.py,
  test_adapter_ws.py, test_parity.py
  invariants_map.md    # checklist spec §6 → test (Task 17)
```

## Interfacce condivise (fonte di verità per tutti i task)

Ogni task cita da qui. Definite nel Task 2 (models), Task 3 (events), Task 4 (ports).

```python
# models.py
class TurnSource(StrEnum):
    CHAT = "chat"; VOICE = "voice"; HEADLESS = "headless"

class StopReason(StrEnum):
    COMPLETED = "completed"; MAX_STEPS = "max_steps"; CANCELLED = "cancelled"
    DISCONNECTED = "disconnected"; ERROR = "error"; LENGTH = "length"

@dataclass(frozen=True, slots=True)
class ToolInvocation:
    call_id: str           # sempre normalizzato non-vuoto (call_<uuid> se mancante)
    name: str
    args: dict[str, Any]   # {} se il JSON era invalido (raw preservato in raw_args)
    raw_args: str
    parse_error: str | None = None   # messaggio se args non parsabili

@dataclass(frozen=True, slots=True)
class ToolMeta:
    exists: bool
    client_executed: bool = False
    interactive: str | None = None   # "ask_user" per il meta-tool wizard, altrimenti None
    timeout_s: float | None = None

@dataclass(frozen=True, slots=True)
class TurnRequest:
    conversation_id: str
    system_prompt: str
    history: list[dict[str, Any]]        # messaggi formato OpenAI, GIÀ assemblati
    tools: list[dict[str, Any]]          # tool definitions formato OpenAI
    source: TurnSource
    max_steps: int                       # budget step (LLM step, non tool)
    context_window: int
    resolved_max_tokens: int | None
    client_ip: str | None
    version_group_id: str | None
    version_index: int | None

@dataclass(frozen=True, slots=True)
class TurnOutcome:
    content: str
    thinking: str
    finish_reason: str                   # vocabolario legacy (Global Constraints)
    stop_reason: StopReason
    steps: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    final_assistant_message_id: str | None
```

```python
# ports.py — tipi di supporto
@dataclass(frozen=True, slots=True)
class LLMTextDelta:      text: str
@dataclass(frozen=True, slots=True)
class LLMThinkingDelta:  text: str
@dataclass(frozen=True, slots=True)
class LLMToolCallDelta:  payload: dict[str, Any]      # chunk raw, solo diagnostica/parity
@dataclass(frozen=True, slots=True)
class LLMUsage:          input_tokens: int; output_tokens: int; cost: float
@dataclass(frozen=True, slots=True)
class LLMStepDone:       finish_reason: str; tool_calls: tuple[ToolInvocation, ...]
@dataclass(frozen=True, slots=True)
class LLMFailure:        message: str; status_code: int | None; retryable: bool
LLMEvent = LLMTextDelta | LLMThinkingDelta | LLMToolCallDelta | LLMUsage | LLMStepDone | LLMFailure

class GateAction(StrEnum):
    EXECUTE = "execute"; DENY = "deny"; CONFIRM = "confirm"

@dataclass(frozen=True, slots=True)
class GateVerdict:
    action: GateAction
    outcome: str                  # etichetta audit/disposition (es. "allow", "scope_denied")
    reason: str | None = None
    risk_level: str | None = None
    description: str | None = None

class InteractionOutcome(StrEnum):
    APPROVED = "approved"; REJECTED = "rejected"; TIMEOUT = "timeout"
    CANCELLED = "cancelled"; DISCONNECTED = "disconnected"

@dataclass(frozen=True, slots=True)
class ToolExecutionOutput:
    ok: bool
    content: str                  # contenuto tool response (già shaped/troncato)
    error: str | None = None
    images: tuple[dict[str, str], ...] = ()
    payload: dict[str, Any] | None = None   # risultato strutturato per artifact registry

@dataclass(frozen=True, slots=True)
class CompactionResult:
    performed: bool
    summary_text: str | None
    tokens_before: int
    tokens_after: int
    error: str | None = None
```

```python
# ports.py — le 7 porte (Protocol, runtime_checkable NON necessario)
class LLMPort(Protocol):
    def stream_step(
        self, *, system_prompt: str, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]], max_tokens: int | None,
        cancel: asyncio.Event,
    ) -> AsyncIterator[LLMEvent]: ...

class PermissionPort(Protocol):
    async def decide(
        self, call: ToolInvocation, *, conversation_id: str,
    ) -> GateVerdict: ...        # risolve mode/scope/rules PER-CALL (invariante §6.9)

class InteractionPort(Protocol):
    async def confirm_tool(
        self, call: ToolInvocation, *, verdict: GateVerdict, timeout_s: float,
        cancel: asyncio.Event,
    ) -> InteractionOutcome: ...
    async def run_client_tool(
        self, call: ToolInvocation, *, timeout_s: float, cancel: asyncio.Event,
    ) -> ToolExecutionOutput: ...   # DISCONNECTED → solleva EngineDisconnected
    async def ask_user(
        self, call: ToolInvocation, *, timeout_s: float, cancel: asyncio.Event,
    ) -> ToolExecutionOutput: ...

class EventPort(Protocol):
    async def emit(self, event: AgentEvent) -> None: ...   # MAI solleva; best-effort

class PersistencePort(Protocol):
    async def save_assistant_step(
        self, *, content: str, thinking: str,
        tool_calls: tuple[ToolInvocation, ...],
    ) -> str: ...                                          # → message_id
    async def save_tool_result(
        self, *, call: ToolInvocation, content: str, status: str,
    ) -> None: ...
    async def save_audit(
        self, *, call: ToolInvocation, verdict: GateVerdict,
        interaction: InteractionOutcome | None,
    ) -> None: ...
    async def register_artifacts(
        self, *, call: ToolInvocation, output: ToolExecutionOutput,
    ) -> str | None: ...                                   # → artifact_id
    async def checkpoint(self) -> None: ...                # commit boundary (§6.15)
    async def load_history(self) -> list[dict[str, Any]]: ...  # esclude context_excluded
    async def archive_compacted(
        self, *, summary_text: str, upto_message_ids: list[str],
    ) -> None: ...

class ContextPort(Protocol):
    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int: ...
    def should_compact(self, *, tokens: int, context_window: int) -> bool: ...
    async def compact(
        self, *, messages: list[dict[str, Any]], context_window: int,
    ) -> CompactionResult: ...

class ExecutionPort(Protocol):
    def describe(self, name: str) -> ToolMeta: ...
    async def execute(
        self, call: ToolInvocation, *, client_ip: str | None,
        conversation_id: str,
    ) -> ToolExecutionOutput: ...   # timeout per-tool DENTRO l'adapter
```

```python
# engine.py — costruttore e entry point
class EngineDisconnected(Exception): ...   # segnale interno: client WS caduto

class AgentEngine:
    def __init__(
        self, *, llm: LLMPort, permissions: PermissionPort,
        interaction: InteractionPort, events: EventPort,
        persistence: PersistencePort, context: ContextPort,
        execution: ExecutionPort, retry: RetryPolicy,
        confirmation_timeout_s: float = 120.0,
    ) -> None: ...

    async def run(
        self, request: TurnRequest, *, cancel: asyncio.Event,
    ) -> TurnOutcome: ...
```

Eccezioni: l'engine NON lascia trapelare eccezioni — ogni fallimento diventa
`TurnOutcome` con `finish_reason` appropriato. `EngineDisconnected` (sollevata dalle porte
interaction/event su socket caduto) è catturata nel loop → `finish_reason="disconnected"`.

---

### Task 1: Branch, package skeleton, contratto import-linter `agent ↛ turn`

**Files:**
- Create: `backend/services/agent/__init__.py`, `backend/services/agent/adapters/__init__.py`
- Create: `backend/tests/agent/__init__.py`, `backend/tests/agent/conftest.py`
- Modify: `backend/pyproject.toml` (sezione `[tool.importlinter]`)

**Interfaces:**
- Produces: il package importabile `backend.services.agent` e il contratto lint che i task
  successivi non possono violare.

- [ ] **Step 1: Crea il branch**

```bash
git checkout main && git pull --ff-only && git checkout -b feat/agent-engine-fase1
```

- [ ] **Step 2: Package skeleton**

`backend/services/agent/__init__.py`:
```python
"""AL\\CE — AgentEngine: motore agentico greenfield (Agent v2, Fase 1).

Progettato da principi primi (riferimento: architettura Claude Code).
PRINCIPIO PILASTRO: nessun import da ``backend.services.turn``; il legacy
entra solo come checklist di invarianti (spec Fase 1 §6).
"""
```

`backend/services/agent/adapters/__init__.py`:
```python
"""Adapter delle porte del motore verso la piattaforma (LLM, permessi, DB, WS)."""
```

`backend/tests/agent/__init__.py` vuoto; `backend/tests/agent/conftest.py`:
```python
"""Fixture condivise per la suite del motore greenfield."""
```

- [ ] **Step 3: Contratto import-linter**

In `backend/pyproject.toml`, nella sezione import-linter esistente (cerca
`[tool.importlinter]`; i contratti sono elencati come `[[tool.importlinter.contracts]]`),
aggiungi in coda:

```toml
[[tool.importlinter.contracts]]
name = "agent engine independent from legacy turn path"
type = "forbidden"
source_modules = ["backend.services.agent"]
forbidden_modules = ["backend.services.turn"]
```

- [ ] **Step 4: Verifica gate**

Run (da repo root): `lint-imports --config backend/pyproject.toml`
Expected: tutti i contratti `KEPT` (ora 7).

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent backend/tests/agent backend/pyproject.toml
git commit -m "feat(engine): package agent greenfield + contratto import-linter agent-non-importa-turn"
```

---

### Task 2: `models.py` — DTO del motore

**Files:**
- Create: `backend/services/agent/models.py`
- Test: `backend/tests/agent/test_models.py`

**Interfaces:**
- Produces: `TurnSource`, `StopReason`, `ToolInvocation`, `ToolMeta`, `TurnRequest`,
  `TurnOutcome` ESATTAMENTE come nella sezione "Interfacce condivise" (copiale da lì,
  incluse le annotazioni). In più: `normalize_tool_invocations(raw: list[dict]) →
  tuple[ToolInvocation, ...]` e `STOP_TO_FINISH: dict[StopReason, str]`.

- [ ] **Step 1: Test fallenti**

`backend/tests/agent/test_models.py`:
```python
"""DTO del motore: normalizzazione tool call e mapping finish_reason."""

from backend.services.agent.models import (
    STOP_TO_FINISH, StopReason, ToolInvocation, normalize_tool_invocations,
)


def test_normalize_assigns_missing_call_ids() -> None:
    raw = [{"function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}]
    calls = normalize_tool_invocations(raw)
    assert len(calls) == 1
    assert calls[0].call_id.startswith("call_") and len(calls[0].call_id) > 10
    assert calls[0].name == "read_file"
    assert calls[0].args == {"path": "a.txt"}
    assert calls[0].parse_error is None


def test_normalize_preserves_existing_id_and_bad_json() -> None:
    raw = [{"id": "call_abc", "function": {"name": "t", "arguments": "{oops"}}]
    calls = normalize_tool_invocations(raw)
    assert calls[0].call_id == "call_abc"
    assert calls[0].args == {}
    assert calls[0].raw_args == "{oops"
    assert calls[0].parse_error is not None


def test_normalize_missing_name_yields_parse_error() -> None:
    raw = [{"id": "call_x", "function": {"arguments": "{}"}}]
    calls = normalize_tool_invocations(raw)
    assert calls[0].name == ""
    assert calls[0].parse_error is not None


def test_stop_reason_maps_to_legacy_finish_vocabulary() -> None:
    assert STOP_TO_FINISH[StopReason.COMPLETED] == "stop"
    assert STOP_TO_FINISH[StopReason.MAX_STEPS] == "stop"
    assert STOP_TO_FINISH[StopReason.CANCELLED] == "cancelled"
    assert STOP_TO_FINISH[StopReason.DISCONNECTED] == "disconnected"
    assert STOP_TO_FINISH[StopReason.ERROR] == "error"
    assert STOP_TO_FINISH[StopReason.LENGTH] == "length"
    assert set(STOP_TO_FINISH) == set(StopReason)
```

- [ ] **Step 2: Verifica che falliscano**

Run (da `backend/`): `pytest tests/agent/test_models.py -v`
Expected: FAIL/ERROR con `ModuleNotFoundError: backend.services.agent.models`.

- [ ] **Step 3: Implementazione**

`backend/services/agent/models.py` — copia le definizioni dalla sezione "Interfacce
condivise" del piano e aggiungi:

```python
import json
import uuid


def normalize_tool_invocations(raw: list[dict[str, Any]]) -> tuple[ToolInvocation, ...]:
    """Normalizza le tool call del modello: ID sempre presenti, JSON validato.

    Invariante §6.1.2: gli ID sono assegnati QUI, una volta, così assistant
    message e tool response condividono lo stesso valore.
    """
    out: list[ToolInvocation] = []
    for item in raw:
        fn = item.get("function") or {}
        call_id = item.get("id") or f"call_{uuid.uuid4().hex}"
        name = fn.get("name") or ""
        raw_args = fn.get("arguments") or "{}"
        args: dict[str, Any] = {}
        parse_error: str | None = None
        if not name:
            parse_error = "tool call senza nome"
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                args = parsed
            else:
                parse_error = parse_error or "argomenti non-oggetto"
        except json.JSONDecodeError as exc:
            parse_error = parse_error or f"argomenti non parsabili: {exc}"
        out.append(ToolInvocation(
            call_id=call_id, name=name, args=args,
            raw_args=raw_args, parse_error=parse_error,
        ))
    return tuple(out)


STOP_TO_FINISH: dict[StopReason, str] = {
    StopReason.COMPLETED: "stop",
    StopReason.MAX_STEPS: "stop",
    StopReason.LENGTH: "length",
    StopReason.CANCELLED: "cancelled",
    StopReason.DISCONNECTED: "disconnected",
    StopReason.ERROR: "error",
}
```

- [ ] **Step 4: Verifica verde + gate**

Run: `pytest tests/agent/test_models.py -v` → PASS.
Run: `ruff check backend/services/agent backend/tests/agent` e
`mypy backend/services/agent/models.py` (da `backend/`) → 0 errori.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/models.py backend/tests/agent/test_models.py
git commit -m "feat(engine): DTO del motore - TurnRequest/TurnOutcome/ToolInvocation con normalizzazione ID"
```

---

### Task 3: `events.py` — eventi interni tipizzati

**Files:**
- Create: `backend/services/agent/events.py`
- Test: `backend/tests/agent/test_events.py`

**Interfaces:**
- Consumes: `ToolInvocation` da `models.py`.
- Produces: union `AgentEvent` di modelli pydantic v2 frozen, uno per fatto del turno
  (vocabolario v2 della spec §4 + 2 diagnostici Mossa-1-only). Ogni modello ha campo
  `type: Literal[...]` col nome wire v2. Elenco COMPLETO (payload minimi ma sufficienti
  per il parity adapter):

```python
# type = nome v2                      payload
TurnStartedEvent      "turn.started"           turn_id, conversation_id, source
TurnDeltaEvent        "turn.delta"             turn_id, step, kind: Literal["text","thinking"], text
LlmStepEvent          "turn.llm_step"          turn_id, step
ToolCallEvent         "tool.call"              turn_id, step, call: ToolInvocation
ToolStartedEvent      "tool.started"           turn_id, call_id
ToolProgressEvent     "tool.progress"          turn_id, call_id, progress: dict
ToolResultEvent       "tool.result"            turn_id, call_id, name, status, content_preview,
                                               artifact_id | None
InteractionRequestedEvent "interaction.requested"  turn_id, interaction_id, kind, call_id,
                                               payload: dict  # args/risk/description/questions
InteractionResolvedEvent  "interaction.resolved"   turn_id, interaction_id, kind, outcome
ContextUsageEvent     "context.usage"          turn_id, tokens, context_window
CompactionEvent       "context.compaction"     turn_id, phase: Literal["started","done","failed"],
                                               tokens_before | None, tokens_after | None, error | None
TurnWarningEvent      "turn.warning"           turn_id, code, message
TurnErrorEvent        "turn.error"             turn_id, code, message
TurnUsageEvent        "turn.usage"             turn_id, step, input_tokens, output_tokens, cost
TurnFinishedEvent     "turn.finished"          turn_id, finish_reason, steps, tool_calls, cost,
                                               final_message_id | None
# Diagnostici SOLO Mossa 1 (muoiono in Mossa 2 col parity adapter):
RawToolCallDeltaEvent "diag.tool_call_delta"   turn_id, payload: dict
```

- [ ] **Step 1: Test fallenti**

`backend/tests/agent/test_events.py`:
```python
"""Vocabolario eventi interni: type letterali, frozen, union esaustiva."""

import pydantic
import pytest

from backend.services.agent import events as ev
from backend.services.agent.models import ToolInvocation

CALL = ToolInvocation(call_id="call_1", name="t", args={}, raw_args="{}")


def test_every_event_has_literal_type() -> None:
    e = ev.ToolResultEvent(
        turn_id="t1", call_id="call_1", name="t", status="ok",
        content_preview="x", artifact_id=None,
    )
    assert e.type == "tool.result"


def test_events_are_frozen() -> None:
    e = ev.TurnStartedEvent(turn_id="t1", conversation_id="c1", source="chat")
    with pytest.raises(pydantic.ValidationError):
        e.turn_id = "other"  # type: ignore[misc]


def test_union_covers_all_event_classes() -> None:
    classes = {
        c for n, c in vars(ev).items()
        if isinstance(c, type) and n.endswith("Event")
    }
    from typing import get_args
    assert set(get_args(ev.AgentEvent)) == classes
```

- [ ] **Step 2: Verifica FAIL** — `pytest tests/agent/test_events.py -v` →
  `ModuleNotFoundError`.

- [ ] **Step 3: Implementazione** — un `class …Event(pydantic.BaseModel)` per riga della
  tabella sopra, tutti con `model_config = ConfigDict(frozen=True)` e `type:
  Literal["…"] = "…"`. `ToolInvocation` dentro `ToolCallEvent` va serializzato: usa
  `model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)` su quel modello.
  Chiudi con:

```python
AgentEvent = (
    TurnStartedEvent | TurnDeltaEvent | LlmStepEvent | ToolCallEvent
    | ToolStartedEvent | ToolProgressEvent | ToolResultEvent
    | InteractionRequestedEvent | InteractionResolvedEvent
    | ContextUsageEvent | CompactionEvent | TurnWarningEvent | TurnErrorEvent
    | TurnUsageEvent | TurnFinishedEvent | RawToolCallDeltaEvent
)
```

- [ ] **Step 4: Verde + gate** — `pytest tests/agent/test_events.py -v` PASS;
  `ruff check` + `mypy backend/services/agent/events.py` → 0.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/events.py backend/tests/agent/test_events.py
git commit -m "feat(engine): vocabolario eventi interni tipizzati (v2 + diagnostici parity)"
```

---

### Task 4: `ports.py` + test double

**Files:**
- Create: `backend/services/agent/ports.py`
- Create: `backend/tests/agent/doubles.py`
- Test: `backend/tests/agent/test_doubles.py`

**Interfaces:**
- Consumes: `ToolInvocation`, `ToolMeta` da models; `AgentEvent` da events.
- Produces: TUTTI i tipi della sezione "Interfacce condivise / ports.py" (copiali
  verbatim). E i double:

```python
class ScriptedLLMPort:            # LLMPort
    def __init__(self, steps: list[list[LLMEvent]]) -> None: ...
    # ogni chiamata a stream_step consuma la prossima lista di eventi;
    # registra le chiamate in .calls (messages/tools ricevuti)

class RecordingEventPort:         # EventPort
    events: list[AgentEvent]      # append-only; emit non solleva mai

class InMemoryPersistence:        # PersistencePort
    assistant_steps: list[dict]; tool_results: list[dict]; audits: list[dict]
    checkpoints: int              # contatore chiamate checkpoint()
    # save_assistant_step ritorna f"msg_{n}"; load_history ritorna history
    # passata al costruttore; archive_compacted registra la chiamata

class StaticPermissionPort:       # PermissionPort
    def __init__(self, verdicts: dict[str, GateVerdict], default: GateVerdict) -> None: ...
    # decide() per nome tool; registra le chiamate (per test mode-per-call)

class ScriptedInteractionPort:    # InteractionPort
    def __init__(self, confirm: InteractionOutcome = APPROVED,
                 client_result: ToolExecutionOutput | None = None,
                 ask_user_result: ToolExecutionOutput | None = None) -> None: ...

class NoopContextPort:            # ContextPort — mai compatta
class TriggeringContextPort:      # ContextPort — compatta alla prima chiamata, poi mai

class MapExecutionPort:           # ExecutionPort
    def __init__(self, tools: dict[str, ToolExecutionOutput],
                 meta: dict[str, ToolMeta] | None = None,
                 delays: dict[str, float] | None = None,
                 errors: dict[str, Exception] | None = None) -> None: ...
    # describe(): meta.get(name, ToolMeta(exists=name in tools));
    # execute(): sleep(delays.get(name,0)); raise errors[name] se presente;
    # registra started_at per-call per i test di parallelismo
```

- [ ] **Step 1: Test fallenti** — `backend/tests/agent/test_doubles.py`:

```python
"""I double rispettano i contratti delle porte (structural typing)."""

import asyncio

from backend.services.agent import ports
from backend.services.agent.models import ToolInvocation, ToolMeta
from backend.tests.agent.doubles import (
    MapExecutionPort, RecordingEventPort, ScriptedLLMPort,
)

CALL = ToolInvocation(call_id="c1", name="echo", args={}, raw_args="{}")


async def test_scripted_llm_yields_steps_in_order() -> None:
    port = ScriptedLLMPort(steps=[
        [ports.LLMTextDelta(text="ciao"),
         ports.LLMStepDone(finish_reason="stop", tool_calls=())],
    ])
    got = [e async for e in port.stream_step(
        system_prompt="s", messages=[], tools=[], max_tokens=None,
        cancel=asyncio.Event(),
    )]
    assert isinstance(got[0], ports.LLMTextDelta)
    assert isinstance(got[-1], ports.LLMStepDone)


async def test_map_execution_port_executes_and_describes() -> None:
    port = MapExecutionPort(tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")})
    assert port.describe("echo") == ToolMeta(exists=True)
    assert port.describe("nope").exists is False
    out = await port.execute(CALL, client_ip=None, conversation_id="c")
    assert out.ok and out.content == "hi"


async def test_recording_event_port_never_raises() -> None:
    port = RecordingEventPort()
    from backend.services.agent.events import TurnStartedEvent
    await port.emit(TurnStartedEvent(turn_id="t", conversation_id="c", source="chat"))
    assert len(port.events) == 1
```

- [ ] **Step 2: FAIL** — `pytest tests/agent/test_doubles.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implementa** `ports.py` (verbatim dalla sezione Interfacce condivise) e
  `doubles.py` secondo il contratto sopra. `ScriptedLLMPort.stream_step` è un
  `async def` generatore che fa `yield` degli eventi della prossima lista e appende
  `{"messages": messages, "tools": tools}` a `self.calls`.

- [ ] **Step 4: Verde + gate** — `pytest tests/agent/test_doubles.py -v` PASS; ruff+mypy 0.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/ports.py backend/tests/agent/doubles.py backend/tests/agent/test_doubles.py
git commit -m "feat(engine): porte del motore (7 Protocol) + test double propri"
```

---

### Task 5: `dedup.py` — registro dedup cross-step

**Files:**
- Create: `backend/services/agent/dedup.py`
- Test: `backend/tests/agent/test_dedup.py`

**Interfaces:**
- Consumes: `ToolInvocation`.
- Produces:

```python
class DedupRegistry:
    def seen_before(self, call: ToolInvocation) -> bool: ...
    # True se una call con stessa (name, args normalizzati) è già stata
    # registrata in QUALSIASI step precedente; registra la call se nuova.
```

Normalizzazione (invariante §6.8, Windows-safe): serializza `args` con
`json.dumps(args, sort_keys=True, ensure_ascii=False)` sostituendo PRIMA ogni valore
stringa con `value.replace("\\\\", "/")` (i path Windows con backslash diversi devono
collidere). Hash: `sha256` della stringa `f"{name}:{normalized}"`.

- [ ] **Step 1: Test fallenti** — `backend/tests/agent/test_dedup.py`:

```python
"""Dedup cross-step: stessa call → duplicata; path Windows normalizzati."""

from backend.services.agent.dedup import DedupRegistry
from backend.services.agent.models import ToolInvocation


def _call(name: str, args: dict) -> ToolInvocation:
    return ToolInvocation(call_id="x", name=name, args=args, raw_args="{}")


def test_first_time_is_not_duplicate_second_is() -> None:
    reg = DedupRegistry()
    assert reg.seen_before(_call("read", {"path": "a.txt"})) is False
    assert reg.seen_before(_call("read", {"path": "a.txt"})) is True


def test_different_args_are_distinct() -> None:
    reg = DedupRegistry()
    assert reg.seen_before(_call("read", {"path": "a.txt"})) is False
    assert reg.seen_before(_call("read", {"path": "b.txt"})) is False


def test_windows_backslash_paths_collide() -> None:
    reg = DedupRegistry()
    assert reg.seen_before(_call("read", {"path": "dir\\\\a.txt"})) is False
    assert reg.seen_before(_call("read", {"path": "dir/a.txt"})) is True


def test_key_order_is_irrelevant() -> None:
    reg = DedupRegistry()
    assert reg.seen_before(_call("t", {"a": 1, "b": 2})) is False
    assert reg.seen_before(_call("t", {"b": 2, "a": 1})) is True
```

- [ ] **Step 2: FAIL** — `pytest tests/agent/test_dedup.py -v`.

- [ ] **Step 3: Implementa**

```python
import hashlib
import json
from typing import Any

from backend.services.agent.models import ToolInvocation


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\\\\", "/")
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


class DedupRegistry:
    """Registro delle tool call già viste nel turno (invariante spec §6.8)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen_before(self, call: ToolInvocation) -> bool:
        payload = json.dumps(_normalize(call.args), sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(f"{call.name}:{payload}".encode()).hexdigest()
        if digest in self._seen:
            return True
        self._seen.add(digest)
        return False
```

- [ ] **Step 4: Verde + gate** — pytest PASS; ruff+mypy 0.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/dedup.py backend/tests/agent/test_dedup.py
git commit -m "feat(engine): dedup registry cross-step con normalizzazione Windows-safe"
```

---

### Task 6: `retry.py` — policy retry/steering

**Files:**
- Create: `backend/services/agent/retry.py`
- Test: `backend/tests/agent/test_retry.py`

**Interfaces:**
- Consumes: `LLMFailure` da ports.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool
    nudge: str | None = None    # messaggio user-role da appendere prima del retry

class RetryPolicy:
    def __init__(self, *, max_empty_retries: int = 2, max_transient_retries: int = 2) -> None: ...
    def on_empty_response(self, attempt: int) -> RetryDecision: ...
        # attempt parte da 1; retry=True con nudge finché attempt <= max_empty_retries
    def on_failure(self, failure: LLMFailure, attempt: int) -> RetryDecision: ...
        # failure.retryable=False (es. HTTPStatusError 4xx) → MAI retry (fail-fast);
        # retryable=True → retry finché attempt <= max_transient_retries

EMPTY_NUDGE = (
    "La tua risposta precedente era vuota. Continua il lavoro: rispondi con il "
    "contenuto o con la prossima tool call."
)
```

- [ ] **Step 1: Test fallenti** — `backend/tests/agent/test_retry.py`:

```python
"""Retry policy: empty-response nudge; transient sì, HTTP status fail-fast."""

from backend.services.agent.ports import LLMFailure
from backend.services.agent.retry import EMPTY_NUDGE, RetryPolicy


def test_empty_response_retries_with_nudge_then_gives_up() -> None:
    p = RetryPolicy(max_empty_retries=2)
    d1 = p.on_empty_response(attempt=1)
    assert d1.retry is True and d1.nudge == EMPTY_NUDGE
    assert p.on_empty_response(attempt=2).retry is True
    assert p.on_empty_response(attempt=3).retry is False


def test_transient_failure_retries_within_budget() -> None:
    p = RetryPolicy(max_transient_retries=2)
    f = LLMFailure(message="conn reset", status_code=None, retryable=True)
    assert p.on_failure(f, attempt=1).retry is True
    assert p.on_failure(f, attempt=3).retry is False


def test_http_status_failure_is_fail_fast() -> None:
    p = RetryPolicy()
    f = LLMFailure(message="400 bad request", status_code=400, retryable=False)
    assert p.on_failure(f, attempt=1).retry is False
```

- [ ] **Step 2: FAIL**; **Step 3: implementa** (diretto dai contratti sopra — nessuna
  logica oltre i confronti su attempt e retryable); **Step 4: verde + ruff/mypy**.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/retry.py backend/tests/agent/test_retry.py
git commit -m "feat(engine): retry policy - empty nudge e transient vs fail-fast"
```

---

### Task 7: `stop.py` — budget e stop conditions

**Files:**
- Create: `backend/services/agent/stop.py`
- Test: `backend/tests/agent/test_stop.py`

**Interfaces:**
- Consumes: `StopReason`, `STOP_TO_FINISH` da models.
- Produces:

```python
class BudgetTracker:
    def __init__(self, *, max_steps: int) -> None: ...
    def begin_step(self) -> int: ...        # incrementa e ritorna il numero step (1-based)
    @property
    def steps(self) -> int: ...
    def out_of_steps(self) -> bool: ...     # True se steps >= max_steps

def resolve_stop(
    *, llm_finish: str | None, cancelled: bool, disconnected: bool,
    out_of_steps: bool, errored: bool,
) -> StopReason: ...
```

Precedenza di `resolve_stop` (dall'alto): `disconnected` → DISCONNECTED; `cancelled` →
CANCELLED; `errored` → ERROR; `out_of_steps` → MAX_STEPS; `llm_finish == "length"` →
LENGTH; altrimenti COMPLETED. (Invariante: disconnect > cancel, spec §6.5.)

- [ ] **Step 1: Test fallenti** — `backend/tests/agent/test_stop.py`:

```python
"""Stop conditions: precedenza disconnect > cancel > error > budget > length."""

from backend.services.agent.models import StopReason
from backend.services.agent.stop import BudgetTracker, resolve_stop


def test_budget_tracker_counts_and_caps() -> None:
    b = BudgetTracker(max_steps=2)
    assert b.begin_step() == 1
    assert b.out_of_steps() is False
    assert b.begin_step() == 2
    assert b.out_of_steps() is True


def test_precedence_disconnect_beats_everything() -> None:
    assert resolve_stop(
        llm_finish="stop", cancelled=True, disconnected=True,
        out_of_steps=True, errored=True,
    ) is StopReason.DISCONNECTED


def test_precedence_cancel_beats_error_and_budget() -> None:
    assert resolve_stop(
        llm_finish=None, cancelled=True, disconnected=False,
        out_of_steps=True, errored=True,
    ) is StopReason.CANCELLED


def test_length_and_completed() -> None:
    common = dict(cancelled=False, disconnected=False, out_of_steps=False, errored=False)
    assert resolve_stop(llm_finish="length", **common) is StopReason.LENGTH
    assert resolve_stop(llm_finish="stop", **common) is StopReason.COMPLETED
```

- [ ] **Step 2: FAIL**; **Step 3: implementa** (if-chain nell'ordine di precedenza
  documentato); **Step 4: verde + ruff/mypy**.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/stop.py backend/tests/agent/test_stop.py
git commit -m "feat(engine): budget tracker e stop conditions con precedenza esplicita"
```

---

### Task 8: `engine.py` — passo singolo senza tool

**Files:**
- Create: `backend/services/agent/engine.py`
- Test: `backend/tests/agent/test_engine_single_step.py`

**Interfaces:**
- Consumes: tutto quanto prodotto dai Task 2-7.
- Produces: `AgentEngine.__init__` e `AgentEngine.run` ESATTAMENTE come in "Interfacce
  condivise". Comportamento di questo task (solo percorso senza tool call):
  1. `run()` genera `turn_id = uuid.uuid4().hex`, emette `TurnStartedEvent`.
  2. Per ogni step: `BudgetTracker.begin_step()`, emette `LlmStepEvent`, consuma
     `llm.stream_step` rilanciando `TurnDeltaEvent` per ogni delta (text/thinking),
     `RawToolCallDeltaEvent` per i `LLMToolCallDelta`, accumula usage.
  3. A `LLMStepDone` senza tool call: se contenuto vuoto → `RetryPolicy.on_empty_response`
     (nudge appeso come messaggio user alla history di lavoro, nuovo step). Se contenuto
     presente → stop.
  4. `LLMFailure`: consulta `RetryPolicy.on_failure`; su retry esaurito → StopReason.ERROR
     + `TurnErrorEvent`.
  5. Chiusura SEMPRE (finally-style): `TurnUsageEvent` per step + `TurnFinishedEvent`
     con `finish_reason = STOP_TO_FINISH[stop_reason]`; ritorna `TurnOutcome` popolato.
  6. `cancel.is_set()` controllato a inizio step → CANCELLED.
  NOTA: in questo task la persistenza del contenuto finale NON avviene (resta fuori dal
  motore, come oggi: `_persist_final_turn` in ws.py); `save_assistant_step` arriva col
  Task 9 solo per gli step con tool call.

- [ ] **Step 1: Test fallenti** — `backend/tests/agent/test_engine_single_step.py`:

```python
"""AgentEngine, percorso senza tool: eventi, retry vuoto, cancel, errore."""

import asyncio

import pytest

from backend.services.agent import events as ev
from backend.services.agent import ports
from backend.services.agent.engine import AgentEngine
from backend.services.agent.models import StopReason, TurnRequest, TurnSource
from backend.services.agent.retry import RetryPolicy
from backend.tests.agent.doubles import (
    InMemoryPersistence, MapExecutionPort, NoopContextPort,
    RecordingEventPort, ScriptedInteractionPort, ScriptedLLMPort,
    StaticPermissionPort,
)


def _request() -> TurnRequest:
    return TurnRequest(
        conversation_id="c1", system_prompt="sp",
        history=[{"role": "user", "content": "ciao"}], tools=[],
        source=TurnSource.CHAT, max_steps=5, context_window=32768,
        resolved_max_tokens=None, client_ip=None,
        version_group_id=None, version_index=None,
    )


def _engine(llm: ScriptedLLMPort, events: RecordingEventPort) -> AgentEngine:
    return AgentEngine(
        llm=llm,
        permissions=StaticPermissionPort(verdicts={}, default=ports.GateVerdict(
            action=ports.GateAction.EXECUTE, outcome="allow")),
        interaction=ScriptedInteractionPort(),
        events=events,
        persistence=InMemoryPersistence(),
        context=NoopContextPort(),
        execution=MapExecutionPort(tools={}),
        retry=RetryPolicy(),
    )


async def test_happy_path_stream_to_finished() -> None:
    llm = ScriptedLLMPort(steps=[[
        ports.LLMTextDelta(text="ci"), ports.LLMTextDelta(text="ao"),
        ports.LLMUsage(input_tokens=10, output_tokens=2, cost=0.001),
        ports.LLMStepDone(finish_reason="stop", tool_calls=()),
    ]])
    rec = RecordingEventPort()
    outcome = await _engine(llm, rec).run(_request(), cancel=asyncio.Event())
    assert outcome.content == "ciao"
    assert outcome.finish_reason == "stop"
    assert outcome.stop_reason is StopReason.COMPLETED
    assert outcome.steps == 1 and outcome.cost == pytest.approx(0.001)
    types = [e.type for e in rec.events]
    assert types[0] == "turn.started"
    assert "turn.llm_step" in types and "turn.delta" in types
    assert types[-1] == "turn.finished"
    deltas = [e for e in rec.events if e.type == "turn.delta"]
    assert "".join(d.text for d in deltas) == "ciao"


async def test_empty_response_retried_with_nudge() -> None:
    llm = ScriptedLLMPort(steps=[
        [ports.LLMStepDone(finish_reason="stop", tool_calls=())],       # vuoto
        [ports.LLMTextDelta(text="eccomi"),
         ports.LLMStepDone(finish_reason="stop", tool_calls=())],
    ])
    rec = RecordingEventPort()
    outcome = await _engine(llm, rec).run(_request(), cancel=asyncio.Event())
    assert outcome.content == "eccomi"
    assert outcome.steps == 2
    # il nudge è stato appeso ai messaggi del secondo step
    assert any("vuota" in str(m) for m in llm.calls[1]["messages"])


async def test_cancel_before_step_stops_clean() -> None:
    llm = ScriptedLLMPort(steps=[[
        ports.LLMTextDelta(text="mai"),
        ports.LLMStepDone(finish_reason="stop", tool_calls=()),
    ]])
    cancel = asyncio.Event(); cancel.set()
    rec = RecordingEventPort()
    outcome = await _engine(llm, rec).run(_request(), cancel=cancel)
    assert outcome.finish_reason == "cancelled"
    assert rec.events[-1].type == "turn.finished"


async def test_non_retryable_failure_is_error() -> None:
    llm = ScriptedLLMPort(steps=[[
        ports.LLMFailure(message="400", status_code=400, retryable=False),
    ]])
    rec = RecordingEventPort()
    outcome = await _engine(llm, rec).run(_request(), cancel=asyncio.Event())
    assert outcome.finish_reason == "error"
    assert any(e.type == "turn.error" for e in rec.events)
    assert rec.events[-1].type == "turn.finished"
```

- [ ] **Step 2: FAIL** — `pytest tests/agent/test_engine_single_step.py -v`.

- [ ] **Step 3: Implementa il nucleo di `engine.py`**

Struttura del loop (questo È il cuore del motore — scrivilo pulito, commenti solo sugli
invarianti):

```python
class AgentEngine:
    """Motore agentico: un loop unificato, I/O solo attraverso le porte."""

    def __init__(self, *, llm, permissions, interaction, events, persistence,
                 context, execution, retry, confirmation_timeout_s: float = 120.0) -> None:
        self._llm = llm; self._permissions = permissions
        self._interaction = interaction; self._events = events
        self._persistence = persistence; self._context = context
        self._execution = execution; self._retry = retry
        self._confirmation_timeout_s = confirmation_timeout_s

    async def run(self, request: TurnRequest, *, cancel: asyncio.Event) -> TurnOutcome:
        turn_id = uuid.uuid4().hex
        state = _TurnState(request=request)   # dataclass interna mutabile:
        # working_messages (copia della history), content, thinking, usage
        # accumulato, tool_calls count, empty_attempts, failure_attempts,
        # errored/disconnected flags, final_message_id
        await self._events.emit(ev.TurnStartedEvent(
            turn_id=turn_id, conversation_id=request.conversation_id,
            source=request.source.value))
        budget = BudgetTracker(max_steps=request.max_steps)
        stop: StopReason | None = None
        try:
            while stop is None:
                if cancel.is_set():
                    stop = StopReason.CANCELLED; break
                step = budget.begin_step()
                await self._events.emit(ev.LlmStepEvent(turn_id=turn_id, step=step))
                step_result = await self._run_llm_step(turn_id, step, state, cancel)
                stop = await self._after_step(turn_id, step, step_result, state,
                                              budget, cancel)
        except EngineDisconnected:
            stop = StopReason.DISCONNECTED
        except Exception as exc:                      # difesa: mai trapelare
            logger.exception("AgentEngine: errore non gestito"); state.errored = True
            await self._events.emit(ev.TurnErrorEvent(
                turn_id=turn_id, code="engine_error", message=str(exc)))
            stop = StopReason.ERROR
        return await self._finish(turn_id, stop, state, budget)
```

`_run_llm_step` consuma lo stream: accumula deltas in `state`, emette
`TurnDeltaEvent`/`RawToolCallDeltaEvent`, su `LLMUsage` emette `TurnUsageEvent` e somma,
ritorna `_StepResult(finish_reason, tool_calls, failure)`. `_after_step` decide: failure →
retry policy (nudge/errore); tool_calls → (Task 9); vuoto → retry policy; contenuto →
`resolve_stop`. `_finish` emette `TurnFinishedEvent` e costruisce `TurnOutcome`
(`finish_reason=STOP_TO_FINISH[stop]`). Il codice completo emerge dai test: implementa il
minimo che li fa passare, mantenendo i nomi qui definiti.

- [ ] **Step 4: Verde + gate** — pytest PASS; ruff+mypy 0.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/engine.py backend/tests/agent/test_engine_single_step.py
git commit -m "feat(engine): AgentEngine - loop base senza tool (stream, retry, cancel, errore)"
```

---

### Task 9: `engine.py` — step con tool: gate, esecuzione parallela, invarianti persistenza

**Files:**
- Modify: `backend/services/agent/engine.py`
- Test: `backend/tests/agent/test_engine_tools.py`

**Interfaces:**
- Consumes: `DedupRegistry`, `PermissionPort`, `InteractionPort`, `ExecutionPort`,
  `PersistencePort`.
- Produces: gestione completa di `LLMStepDone.tool_calls` dentro `_after_step`:

Flusso per uno step con N tool call (ORDINE NORMATIVO — ogni punto è un invariante):
1. `persistence.save_assistant_step(content, thinking, tool_calls)` PRIMA di tutto
   (§6.1.2) e `checkpoint()` (§6.15: rilascia il write-lock prima dell'esecuzione).
2. Per OGNI call, in ordine:
   a. `parse_error` → tool result sintetico d'errore (niente gate).
   b. `dedup.seen_before(call)` → result sintetico "duplicata, riusa il risultato
      precedente".
   c. `execution.describe(name).exists` False → result "tool sconosciuto".
   d. `permissions.decide(call)` (per-call, §6.9):
      - DENY → result sintetico col reason; `save_audit`.
      - CONFIRM → `InteractionRequestedEvent`; `interaction.confirm_tool(...)`;
        `InteractionResolvedEvent`; APPROVED → prosegue; REJECTED/TIMEOUT → result
        sintetico; CANCELLED → result sintetico "annullata"; DISCONNECTED → result
        sintetico "annullata (disconnesso)" e flag disconnect DOPO la persistenza;
        sempre `save_audit`.
   e. Routing: `meta.interactive == "ask_user"` → `interaction.ask_user(...)`;
      `meta.client_executed` → `interaction.run_client_tool(...)`; altrimenti va nel
      batch server-side.
3. Il batch server-side greenlit esegue in PARALLELO (`asyncio.gather`); emette
   `ToolStartedEvent` prima e `ToolResultEvent` dopo per ciascuna.
4. Per OGNI call (qualunque ramo, a-e incluse): `persistence.save_tool_result(...)` —
   UNA tool response per OGNI call_id (§6.1.1) — poi `register_artifacts` per i success
   server-side, e `checkpoint()` a fine batch.
5. SOLO DOPO la persistenza: check `cancel` (§6.4 persist-prima-di-cancel) e flag
   disconnect → stop. Altrimenti: nuovo step (la history di lavoro si arricchisce di
   assistant+tool messages).

- [ ] **Step 1: Test fallenti** — `backend/tests/agent/test_engine_tools.py`
  (usa gli helper `_request`/`_engine` come nel Task 8, parametrizzando le porte):

```python
"""Step con tool: invariante tool-response-per-ogni-call_id in OGNI ramo."""

import asyncio

from backend.services.agent import ports
from backend.services.agent.models import ToolInvocation, ToolMeta

# helper: uno ScriptedLLMPort a 2 step — step 1 emette le tool call date,
# step 2 chiude con testo "fatto".


def _tool_step(calls: tuple[ToolInvocation, ...]) -> list[ports.LLMEvent]:
    return [ports.LLMStepDone(finish_reason="tool_calls", tool_calls=calls)]


def _final_step() -> list[ports.LLMEvent]:
    return [ports.LLMTextDelta(text="fatto"),
            ports.LLMStepDone(finish_reason="stop", tool_calls=())]


async def test_every_call_id_gets_a_tool_result_across_branches() -> None:
    calls = (
        ToolInvocation(call_id="c_ok", name="echo", args={}, raw_args="{}"),
        ToolInvocation(call_id="c_bad", name="echo", args={}, raw_args="{x",
                       parse_error="argomenti non parsabili"),
        ToolInvocation(call_id="c_deny", name="rm", args={}, raw_args="{}"),
        ToolInvocation(call_id="c_missing", name="ghost", args={}, raw_args="{}"),
    )
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi"),
                    "rm": ports.ToolExecutionOutput(ok=True, content="")},
        verdicts={"rm": ports.GateVerdict(action=ports.GateAction.DENY,
                                          outcome="plan_denied", reason="plan mode")},
    )
    saved_ids = {r["call_id"] for r in persistence.tool_results}
    assert saved_ids == {"c_ok", "c_bad", "c_deny", "c_missing"}
    assert outcome.finish_reason == "stop" and outcome.content == "fatto"


async def test_assistant_step_persisted_before_results_and_checkpointed() -> None:
    calls = (ToolInvocation(call_id="c1", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    assert persistence.order[0] == ("assistant_step", "msg_1")
    assert persistence.checkpoints >= 2   # dopo assistant, dopo batch


async def test_duplicate_call_yields_synthetic_result_not_execution() -> None:
    same = ToolInvocation(call_id="c1", name="echo", args={"a": 1}, raw_args="{}")
    again = ToolInvocation(call_id="c2", name="echo", args={"a": 1}, raw_args="{}")
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step((same,)), _tool_step((again,)), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    dup = [r for r in persistence.tool_results if r["call_id"] == "c2"]
    assert dup and "duplicat" in dup[0]["content"].lower()


async def test_parallel_execution_of_greenlit_batch() -> None:
    calls = (
        ToolInvocation(call_id="a", name="slow_a", args={}, raw_args="{}"),
        ToolInvocation(call_id="b", name="slow_b", args={}, raw_args="{}"),
    )
    persistence, outcome, rec, exec_port = await _run_with_port(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"slow_a": ports.ToolExecutionOutput(ok=True, content=""),
                    "slow_b": ports.ToolExecutionOutput(ok=True, content="")},
        delays={"slow_a": 0.05, "slow_b": 0.05},
    )
    # se fossero seriali, il secondo inizierebbe dopo la fine del primo
    assert abs(exec_port.started_at["slow_a"] - exec_port.started_at["slow_b"]) < 0.04


async def test_confirmation_flow_events_and_audit() -> None:
    calls = (ToolInvocation(call_id="c1", name="write", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"write": ports.ToolExecutionOutput(ok=True, content="ok")},
        verdicts={"write": ports.GateVerdict(action=ports.GateAction.CONFIRM,
                                             outcome="needs_confirmation",
                                             risk_level="medium")},
        confirm=ports.InteractionOutcome.APPROVED,
    )
    types = [e.type for e in rec.events]
    assert "interaction.requested" in types and "interaction.resolved" in types
    assert persistence.audits and persistence.audits[0]["interaction"] == "approved"
    assert any(r["call_id"] == "c1" and r["status"] == "ok"
               for r in persistence.tool_results)


async def test_rejection_still_persists_tool_response() -> None:
    calls = (ToolInvocation(call_id="c1", name="write", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"write": ports.ToolExecutionOutput(ok=True, content="ok")},
        verdicts={"write": ports.GateVerdict(action=ports.GateAction.CONFIRM,
                                             outcome="needs_confirmation")},
        confirm=ports.InteractionOutcome.REJECTED,
    )
    saved = [r for r in persistence.tool_results if r["call_id"] == "c1"]
    assert saved and saved[0]["status"] == "rejected"


async def test_cancel_checked_only_after_persistence() -> None:
    # cancel scatta DURANTE l'esecuzione del tool: il result va comunque su DB
    calls = (ToolInvocation(call_id="c1", name="slow", args={}, raw_args="{}"),)
    cancel = asyncio.Event()

    async def _set_cancel_soon() -> None:
        await asyncio.sleep(0.01); cancel.set()

    task = asyncio.create_task(_set_cancel_soon())
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"slow": ports.ToolExecutionOutput(ok=True, content="ok")},
        delays={"slow": 0.05},
        cancel=cancel,
    )
    await task
    assert any(r["call_id"] == "c1" for r in persistence.tool_results)
    assert outcome.finish_reason == "cancelled"
```

Gli helper `_run_with`/`_run_with_port` (in cima al file di test) costruiscono l'engine
con i double e ritornano `(InMemoryPersistence, TurnOutcome, RecordingEventPort[, port])`.
`InMemoryPersistence` va esteso in `doubles.py` con la lista `order` (tuple
`("assistant_step"|"tool_result"|"checkpoint", id)`) per il test d'ordinamento.

- [ ] **Step 2: FAIL**; **Step 3: implementa** il flusso normativo 1-5 dentro
  `_after_step` + `_run_tool_batch`; **Step 4: verde + ruff/mypy**.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/engine.py backend/tests/agent/doubles.py backend/tests/agent/test_engine_tools.py
git commit -m "feat(engine): gate flow e batch tool paralleli con invarianti di persistenza"
```

---

### Task 10: `engine.py` — loop multi-step: budget, disconnect, voice trim, costo

**Files:**
- Modify: `backend/services/agent/engine.py`
- Test: `backend/tests/agent/test_engine_loop.py`

**Interfaces:**
- Consumes: tutto il già prodotto.
- Produces: comportamento completo del loop su più step. In più:
  `TurnRequest.max_tool_calls: int | None = None` (nuovo campo in `models.py`, default
  None = illimitato) — il trim voce (`agent.voice.max_tools`) arriva da qui: quando il
  contatore tool call del turno raggiunge il cap, le tool call ulteriori ricevono un
  result sintetico "budget voce esaurito" e il loop forza lo step finale senza tools.

- [ ] **Step 1: Test fallenti** — `backend/tests/agent/test_engine_loop.py`:

```python
"""Loop multi-step: budget step, disconnect via porte, voice trim, costo."""

import asyncio

from backend.services.agent import ports
from backend.services.agent.engine import EngineDisconnected
from backend.services.agent.models import StopReason, ToolInvocation


async def test_max_steps_stops_loop_with_warning() -> None:
    # LLM che chiede sempre tool: con max_steps=2 il loop si ferma
    call_step = _tool_step((ToolInvocation(call_id="c", name="echo",
                                           args={}, raw_args="{}"),))
    persistence, outcome, rec = await _run_with(
        llm_steps=[call_step, call_step, _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        max_steps=2,
    )
    assert outcome.stop_reason is StopReason.MAX_STEPS
    assert outcome.finish_reason == "stop"
    assert outcome.steps == 2
    assert any(e.type == "turn.warning" for e in rec.events)


async def test_disconnect_from_interaction_port_stops_after_persist() -> None:
    calls = (ToolInvocation(call_id="c1", name="write", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"write": ports.ToolExecutionOutput(ok=True, content="ok")},
        verdicts={"write": ports.GateVerdict(action=ports.GateAction.CONFIRM,
                                             outcome="needs_confirmation")},
        confirm=ports.InteractionOutcome.DISCONNECTED,
    )
    assert outcome.finish_reason == "disconnected"
    # la tool response del call annullato esiste comunque (§6.1.1)
    assert any(r["call_id"] == "c1" for r in persistence.tool_results)
    assert rec.events[-1].type == "turn.finished"


async def test_voice_trim_caps_tool_calls() -> None:
    one = ToolInvocation(call_id="c1", name="echo", args={"n": 1}, raw_args="{}")
    two = ToolInvocation(call_id="c2", name="echo", args={"n": 2}, raw_args="{}")
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step((one, two)), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        max_tool_calls=1,
    )
    trimmed = [r for r in persistence.tool_results if r["call_id"] == "c2"]
    assert trimmed and "budget" in trimmed[0]["content"].lower()
    assert outcome.tool_calls == 1        # solo la eseguita conta


async def test_cost_and_usage_accumulate_across_steps() -> None:
    step1 = [ports.LLMUsage(input_tokens=100, output_tokens=10, cost=0.01),
             ports.LLMStepDone(finish_reason="tool_calls", tool_calls=(
                 ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),))]
    step2 = [ports.LLMTextDelta(text="fine"),
             ports.LLMUsage(input_tokens=200, output_tokens=20, cost=0.02),
             ports.LLMStepDone(finish_reason="stop", tool_calls=())]
    persistence, outcome, rec = await _run_with(
        llm_steps=[step1, step2],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    assert outcome.input_tokens == 300 and outcome.output_tokens == 30
    assert round(outcome.cost, 4) == 0.03
    finished = rec.events[-1]
    assert finished.type == "turn.finished" and round(finished.cost, 4) == 0.03
    usage_events = [e for e in rec.events if e.type == "turn.usage"]
    assert len(usage_events) == 2         # uno per step (semantica attuale)
```

- [ ] **Step 2: FAIL**; **Step 3: implementa** — al `MAX_STEPS` emetti `TurnWarningEvent`
  (`code="max_steps"`); `EngineDisconnected` può arrivare da qualunque porta interaction
  — il flusso del Task 9 punto 2d già persiste PRIMA di propagare il flag; `max_tool_calls`
  contato su `outcome.tool_calls` (solo eseguite). **Step 4: verde + ruff/mypy.**

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/engine.py backend/services/agent/models.py backend/tests/agent/test_engine_loop.py
git commit -m "feat(engine): loop multi-step - budget, disconnect, voice trim, costo accumulato"
```

---

### Task 11: `engine.py` — compaction tra gli step

**Files:**
- Modify: `backend/services/agent/engine.py`
- Test: `backend/tests/agent/test_engine_compaction.py`

**Interfaces:**
- Consumes: `ContextPort`, `PersistencePort.archive_compacted`.
- Produces: PRIMA di ogni step LLM successivo al primo, il motore:
  1. `tokens = context.estimate_tokens(working_messages)`; emette `ContextUsageEvent`.
  2. Se `context.should_compact(tokens, context_window)`: emette
     `CompactionEvent(phase="started")`, chiama `context.compact(...)`;
     - success → `persistence.archive_compacted(...)` + `checkpoint()`, sostituisce la
       working history con `[summary] + messaggi post-compaction` come da
       `CompactionResult`, emette `CompactionEvent(phase="done")`;
     - errore → `CompactionEvent(phase="failed")` e si CONTINUA senza compattare
       (fail-open, il turno non muore per la compaction).
  Estendi `CompactionResult` (ports.py) con `kept_messages: tuple[dict, ...] = ()` —
  i messaggi che sopravvivono — e `archived_message_ids: tuple[str, ...] = ()`.

- [ ] **Step 1: Test fallenti** — `backend/tests/agent/test_engine_compaction.py`:

```python
"""Compaction tra gli step: trigger, archiviazione, fail-open."""

from backend.services.agent import ports
from backend.services.agent.models import ToolInvocation


async def test_compaction_triggers_between_steps_and_rewrites_history() -> None:
    calls = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec, llm = await _run_with_compaction(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        compaction=ports.CompactionResult(
            performed=True, summary_text="RIASSUNTO", tokens_before=30000,
            tokens_after=500, kept_messages=(),
            archived_message_ids=("m1", "m2")),
    )
    phases = [e.phase for e in rec.events if e.type == "context.compaction"]
    assert phases == ["started", "done"]
    assert persistence.archived == [("RIASSUNTO", ["m1", "m2"])]
    # il secondo step LLM vede il summary in testa alla working history
    assert any("RIASSUNTO" in str(m) for m in llm.calls[1]["messages"])


async def test_compaction_failure_is_fail_open() -> None:
    calls = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec, llm = await _run_with_compaction(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
        compaction=ports.CompactionResult(
            performed=False, summary_text=None, tokens_before=30000,
            tokens_after=30000, error="boom"),
    )
    phases = [e.phase for e in rec.events if e.type == "context.compaction"]
    assert phases == ["started", "failed"]
    assert outcome.finish_reason == "stop"     # il turno completa comunque


async def test_context_usage_emitted_each_extra_step() -> None:
    calls = (ToolInvocation(call_id="c", name="echo", args={}, raw_args="{}"),)
    persistence, outcome, rec = await _run_with(
        llm_steps=[_tool_step(calls), _final_step()],
        exec_tools={"echo": ports.ToolExecutionOutput(ok=True, content="hi")},
    )
    assert any(e.type == "context.usage" for e in rec.events)
```

`TriggeringContextPort` (doubles.py) va esteso per accettare il `CompactionResult` da
ritornare e registrare le chiamate; `InMemoryPersistence` guadagna `archived:
list[tuple[str, list[str]]]`.

- [ ] **Step 2: FAIL**; **Step 3: implementa**; **Step 4: verde + ruff/mypy.**

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/engine.py backend/services/agent/ports.py backend/tests/agent/doubles.py backend/tests/agent/test_engine_compaction.py
git commit -m "feat(engine): compaction tra gli step via ContextPort, fail-open"
```

---

### Task 12: Adapter piattaforma — `llm.py`, `permission.py`, `execution.py`, `context.py`

**Files:**
- Create: `backend/services/agent/adapters/llm.py`, `adapters/permission.py`,
  `adapters/execution.py`, `adapters/context.py`
- Test: `backend/tests/agent/test_adapter_llm.py`, `test_adapter_permission.py`

**Interfaces:**
- Consumes (piattaforma — consentita, NON è legacy del motore):
  - `LLMService.chat(messages, tools, cancel_event, *, system_prompt, max_output_tokens,
    …) -> AsyncIterator[dict]` — i chunk dict hanno `type` ∈ {"token", "thinking",
    "tool_call", "usage", "error", "done"} (verificare i campi esatti leggendo
    `backend/services/llm/` PRIMA di implementare: il contratto chunk è del servizio LLM,
    non del motore legacy).
  - `PermissionService.decide(*, tool_name, args, tool_def, conversation_id, mode) ->
    GateDecision` (`backend/services/permission_service.py:228`) + `PermissionModeService`
    per il mode PER-CALL + `ToolRegistry.get_tool_definition`.
  - `ToolRegistry.execute_tool(tool_name, args, context: ExecutionContext) -> ToolResult`
    (`backend/core/tools/execution.py:209`) — l'ExecutionContext si costruisce come nel
    call site attuale del registry (cerca `ExecutionContext(` in `backend/core/tools/`).
  - `ContextManager.estimate_tokens / should_compress / compress`
    (`backend/services/context_manager.py`).
- Produces:

```python
# adapters/llm.py
class LLMServiceAdapter:              # implementa LLMPort
    def __init__(self, llm: "LLMService") -> None: ...
    # traduce i chunk dict in LLMEvent tipizzati; accumula i tool_call delta
    # incrementali e li normalizza con normalize_tool_invocations in LLMStepDone;
    # emette LLMToolCallDelta per ogni chunk raw (parity); mappa i chunk "error"
    # in LLMFailure con retryable=False se status HTTP 4xx, True altrimenti.

# adapters/permission.py
class PermissionServiceAdapter:       # implementa PermissionPort
    def __init__(self, *, permission_service, mode_service, tool_registry,
                 conversation_id: str) -> None: ...
    # decide(): risolve il mode CORRENTE per la conversazione a OGNI chiamata
    # (invariante §6.9), recupera la tool_def dal registry, delega a
    # PermissionService.decide, mappa GateDecision → GateVerdict
    # (ALLOW→EXECUTE, DENY→DENY, NEEDS_CONFIRMATION→CONFIRM;
    #  outcome = decision.outcome.value; reason = decision.reason).

# adapters/execution.py
class ToolRegistryAdapter:            # implementa ExecutionPort
    # describe(): interroga il catalogo (get_tool_definition → exists;
    # tool_def.client_executed → client_executed; name == "ask_user" →
    # interactive="ask_user"); execute(): costruisce ExecutionContext,
    # applica il timeout config llm.tool_execution_timeout con
    # asyncio.wait_for, mappa ToolResult → ToolExecutionOutput
    # (timeout → ok=False, error="timeout dopo Ns").

# adapters/context.py
class ContextManagerAdapter:          # implementa ContextPort
    # mapping diretto; compact() chiama compress e traduce l'esito in
    # CompactionResult (errore catturato → performed=False, error=str(exc)).
```

- [ ] **Step 1: Test fallenti** (i due file di test insieme):

`test_adapter_llm.py` — usa un fake LLMService (classe locale con `chat` generatore
async) e verifica: (1) chunk token/thinking → `LLMTextDelta`/`LLMThinkingDelta`;
(2) sequenza di chunk `tool_call` incrementali → un solo `LLMStepDone` con le
`ToolInvocation` normalizzate e N `LLMToolCallDelta`; (3) chunk `error` con status 400 →
`LLMFailure(retryable=False)`; senza status → `retryable=True`; (4) chunk `usage` →
`LLMUsage` con `cost` presente.

```python
async def test_incremental_tool_call_chunks_become_one_stepdone() -> None:
    fake = FakeLLMService(chunks=[
        {"type": "tool_call", "tool_call": {"index": 0, "id": "call_1",
         "function": {"name": "read", "arguments": '{"pa'}}},
        {"type": "tool_call", "tool_call": {"index": 0,
         "function": {"arguments": 'th": "a.txt"}'}}},
        {"type": "done", "finish_reason": "tool_calls"},
    ])
    events = await _collect(LLMServiceAdapter(fake))
    done = [e for e in events if isinstance(e, ports.LLMStepDone)]
    assert len(done) == 1
    assert done[0].tool_calls[0].name == "read"
    assert done[0].tool_calls[0].args == {"path": "a.txt"}
```

NOTA per l'implementer: il formato esatto dei chunk (nomi campo, shape di `tool_call`)
va verificato in `backend/services/llm/streaming*.py` prima di scrivere il fake — il
fake DEVE riprodurre il contratto reale del servizio, e il test del fake va aggiornato
di conseguenza mantenendo i comportamenti qui specificati.

`test_adapter_permission.py` — con MagicMock dei servizi: (1) `decide` interroga il mode
service a ogni chiamata (2 chiamate → 2 lookup); (2) mapping ALLOW/DENY/
NEEDS_CONFIRMATION → EXECUTE/DENY/CONFIRM con reason propagato.

- [ ] **Step 2: FAIL**; **Step 3: implementa i 4 adapter**; **Step 4: verde + ruff/mypy**
  (`mypy backend/services/agent/adapters/`).

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/adapters backend/tests/agent/test_adapter_llm.py backend/tests/agent/test_adapter_permission.py
git commit -m "feat(engine): adapter piattaforma - LLM, permessi per-call, execution, context"
```

---

### Task 13: Adapter DB — `adapters/db.py` (PersistencePort)

**Files:**
- Create: `backend/services/agent/adapters/db.py`
- Test: `backend/tests/agent/test_adapter_db.py`

**Interfaces:**
- Consumes: `AsyncSession` SQLModel, modello `Message` e `ToolConfirmationAudit` da
  `backend/db/models.py` (piattaforma), `ctx.artifact_registry`
  (`register_from_tool_result`), directory immagini (config).
- Produces:

```python
class SqlModelPersistence:            # implementa PersistencePort
    def __init__(self, *, session: AsyncSession, conversation_id: str,
                 artifact_registry, version_group_id: str | None,
                 version_index: int | None) -> None: ...
```

Regole (invarianti §6.1, §6.15, §6.4.11):
- `save_assistant_step` → riga `Message(role="assistant", tool_calls=…)` + `flush()`
  (l'ID serve subito) — NIENTE commit qui: il commit è `checkpoint()`.
- `save_tool_result` → riga `Message(role="tool", tool_call_id=call.call_id, …)`.
- `checkpoint()` → `await session.commit()` (documentare nel docstring: rilascia il
  write-lock SQLite perché i plugin aprono connessioni proprie).
- `register_artifacts` → delega a `artifact_registry.register_from_tool_result` con la
  risoluzione del bare tool name come fa il registry stesso; immagini persistite su disco
  prima della registrazione (stessa directory config di oggi — cercala in
  `backend/services/artifacts/`).
- `load_history` → SELECT ordinata per `created_at` esclusi `context_excluded=True`.
- `archive_compacted` → UPDATE `context_excluded=True` sugli ID + INSERT del summary
  message (role="system" o il role che il ContextManager usa oggi per i summary — 
  verificarlo in `backend/services/context_manager.py`, è piattaforma).
- Il test usa il fixture DB in-memory del repo (vedi `backend/tests/conftest.py` per il
  pattern di sessione async usato dagli altri test DB).

- [ ] **Step 1: Test fallenti** — `test_adapter_db.py` con session reale in-memory:

```python
async def test_assistant_and_tool_rows_share_call_id(db_session) -> None:
    p = SqlModelPersistence(session=db_session, conversation_id=conv.id,
                            artifact_registry=None, version_group_id=None,
                            version_index=None)
    call = ToolInvocation(call_id="call_z", name="t", args={}, raw_args="{}")
    msg_id = await p.save_assistant_step(content="", thinking="", tool_calls=(call,))
    await p.save_tool_result(call=call, content="ok", status="ok")
    await p.checkpoint()
    rows = (await db_session.exec(select(Message).order_by(Message.created_at))).all()
    assert rows[-2].role == "assistant" and "call_z" in json.dumps(rows[-2].tool_calls)
    assert rows[-1].role == "tool" and rows[-1].tool_call_id == "call_z"


async def test_archive_compacted_excludes_from_history(db_session, conv) -> None:
    p = SqlModelPersistence(session=db_session, conversation_id=conv.id,
                            artifact_registry=None, version_group_id=None,
                            version_index=None)
    ids = []
    for i in range(3):
        db_session.add(Message(conversation_id=conv.id, role="user",
                               content=f"m{i}"))
    await db_session.flush()
    rows = (await db_session.exec(select(Message).order_by(Message.created_at))).all()
    ids = [r.id for r in rows[:2]]
    await p.archive_compacted(summary_text="SUMMARY", upto_message_ids=ids)
    await p.checkpoint()
    history = await p.load_history()
    contents = [m.get("content") for m in history]
    assert "m0" not in contents and "m1" not in contents
    assert "m2" in contents
    assert any("SUMMARY" in str(c) for c in contents)
```

(Il fixture `conv` crea una `Conversation` come fanno i test DB esistenti del repo.)

- [ ] **Step 2: FAIL**; **Step 3: implementa**; **Step 4: verde + ruff/mypy.**

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/adapters/db.py backend/tests/agent/test_adapter_db.py
git commit -m "feat(engine): PersistencePort su SQLModel con unit-of-work esplicite"
```

---

### Task 14: Adapter WS — `adapters/ws.py` (EventPort + InteractionPort, read-pump nuovo)

**Files:**
- Create: `backend/services/agent/adapters/ws.py`
- Test: `backend/tests/agent/test_adapter_ws.py`

**Interfaces:**
- Consumes: `WebSocket` Starlette; i FRAME inbound attuali del canale chat (vocabolario
  client→server INVARIATO in Mossa 1: `cancel`, `tool_confirmation_response`,
  `client_tool_result`, `ask_user_response` — verificare i nomi esatti in
  `backend/api/ws_schema/chat.py` sezione client).
- Produces:

```python
class WsTransport:
    """Proprietario del socket: UNICO lettore (invariante §6.6), send fail-safe."""
    def __init__(self, websocket: WebSocket) -> None: ...
    def begin_turn(self) -> asyncio.Event: ...      # nuovo cancel event per-turno
    async def start(self) -> None: ...              # avvia il read-pump
    async def aclose(self) -> None: ...
    async def send_json(self, payload: dict) -> None: ...   # MAI solleva; su socket
                                                            # chiuso marca disconnected
    async def request(self, kind: str, frame_out: dict, *, timeout_s: float,
                      cancel: asyncio.Event) -> dict | None: ...
    # correlation_id UUID; race: disconnect > cancel > timeout;
    # disconnect → solleva EngineDisconnected; cancel/timeout → None;
    # risposte stale (correlation sconosciuta) scartate con log.
    @property
    def connected(self) -> bool: ...
    async def next_user_message(self) -> dict | None: ...   # per ws.py (giro turni)

class WsEventPort:                    # implementa EventPort
    def __init__(self, transport: WsTransport, translator) -> None: ...
    # translator: Callable[[AgentEvent], list[dict]] — in Mossa 1 è il parity
    # adapter (Task 15); emit() = for frame in translator(event): send_json(frame)

class WsInteractionPort:              # implementa InteractionPort
    def __init__(self, transport: WsTransport, events: EventPort) -> None: ...
    # confirm_tool: emette InteractionRequested/Resolved via events, frame legacy
    # via transport.request("tool_confirmation", …) → mappa la risposta in
    # InteractionOutcome; run_client_tool / ask_user analoghi (§6.5: su
    # disconnect il request solleva EngineDisconnected e la porta lo propaga).
```

Il read-pump: task asyncio che consuma `websocket.iter_json()`; dispatch per `type`:
`cancel` → set del cancel corrente + risoluzione a None delle request pendenti;
frame con `correlation_id` → risolve il Future corrispondente; altri frame → coda
`next_user_message`. Su `WebSocketDisconnect`/`RuntimeError` da socket chiuso: marca
disconnected, risolve tutte le pendenti con EngineDisconnected, sentinella nella coda.

- [ ] **Step 1: Test fallenti** — `test_adapter_ws.py` con un FakeWebSocket locale
  (coda inbound controllata dal test + lista outbound):

```python
async def test_single_reader_and_cancel_dispatch() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws); cancel = t.begin_turn(); await t.start()
    await ws.feed({"type": "cancel"})
    await asyncio.wait_for(_until(lambda: cancel.is_set()), timeout=1)


async def test_request_roundtrip_with_correlation() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws); await t.start()

    async def _answer() -> None:
        sent = await ws.next_sent()          # frame outbound della request
        await ws.feed({"type": "tool_confirmation_response",
                       "correlation_id": sent["correlation_id"], "approved": True})

    task = asyncio.create_task(_answer())
    resp = await t.request("tool_confirmation", {"type": "tool_confirmation_required"},
                           timeout_s=2, cancel=asyncio.Event())
    await task
    assert resp is not None and resp["approved"] is True


async def test_stale_response_is_discarded() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws); await t.start()
    await ws.feed({"type": "tool_confirmation_response",
                   "correlation_id": "ignota", "approved": True})   # stale: no crash

    async def _answer() -> None:
        sent = await ws.next_sent()
        await ws.feed({"type": "tool_confirmation_response",
                       "correlation_id": sent["correlation_id"], "approved": False})

    task = asyncio.create_task(_answer())
    resp = await t.request("tool_confirmation", {"type": "tool_confirmation_required"},
                           timeout_s=2, cancel=asyncio.Event())
    await task
    assert resp is not None and resp["approved"] is False


async def test_disconnect_during_request_raises_engine_disconnected() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws); await t.start()
    task = asyncio.create_task(t.request("tool_confirmation", {"type": "x"},
                                         timeout_s=5, cancel=asyncio.Event()))
    await ws.disconnect()
    with pytest.raises(EngineDisconnected):
        await task


async def test_timeout_returns_none_cancel_returns_none() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws); await t.start()
    resp = await t.request("tool_confirmation", {"type": "tool_confirmation_required"},
                           timeout_s=0.05, cancel=asyncio.Event())
    assert resp is None
    cancelled = asyncio.Event(); cancelled.set()
    resp2 = await t.request("tool_confirmation", {"type": "tool_confirmation_required"},
                            timeout_s=5, cancel=cancelled)
    assert resp2 is None


async def test_send_after_close_never_raises() -> None:
    ws = FakeWebSocket(); t = WsTransport(ws); await t.start()
    await ws.disconnect()
    await t.send_json({"type": "token", "content": "x"})   # non deve sollevare
    assert t.connected is False
```

- [ ] **Step 2: FAIL**; **Step 3: implementa** (`_until` helper: loop con sleep 0.005);
  **Step 4: verde + ruff/mypy.**

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/adapters/ws.py backend/tests/agent/test_adapter_ws.py
git commit -m "feat(engine): trasporto WS greenfield - read-pump unico, request correlate, disconnect"
```

---

### Task 15: `adapters/parity.py` + parity harness

**Files:**
- Create: `backend/services/agent/adapters/parity.py`
- Test: `backend/tests/agent/test_parity.py`

**Interfaces:**
- Consumes: `AgentEvent` (Task 3); il vocabolario wire ATTUALE (`backend/api/ws_schema/chat.py`
  — unica lettura di codice esistente consentita in questo task: è il CONTRATTO, non il
  motore).
- Produces:

```python
def to_wire_frames(event: AgentEvent) -> list[dict[str, Any]]:
    """Traduce un evento interno nei frame wire attuali (legacy + canonici).

    THROWAWAY (Mossa 2 lo elimina). Tabella normativa:
      TurnStartedEvent      → [turn.started]
      LlmStepEvent          → [llm_requery (solo step>1), turn.llm_step]
      TurnDeltaEvent(text)  → [token]
      TurnDeltaEvent(think) → [thinking]
      RawToolCallDeltaEvent → [tool_call]           # relay raw legacy
      ToolCallEvent         → [tool.call]
      ToolStartedEvent      → [tool_execution_start]
      ToolProgressEvent     → [tool_progress]
      ToolResultEvent       → [tool_execution_done, tool.result]
      InteractionRequestedEvent → [interaction.requested]   # il frame legacy
                              # (tool_confirmation_required/…) lo emette il
                              # round-trip di WsInteractionPort, NON il translator
      InteractionResolvedEvent  → [interaction.resolved]
      ContextUsageEvent     → [context_info]
      CompactionEvent       → [context_compression_start|done|failed]
      TurnWarningEvent      → [warning]
      TurnErrorEvent        → [error]
      TurnUsageEvent        → [turn.usage]
      TurnFinishedEvent     → [turn.finished]        # il frame legacy `done` lo
                              # emette _persist_final_turn in ws.py, come oggi
    Ogni frame prodotto DEVE validare contro validate_chat_server (guard strict).
    """
```

- [ ] **Step 1: Test fallenti** — `test_parity.py`, parte A (unit translator):

```python
"""Parity adapter: ogni evento produce frame che validano il contratto attuale."""

from backend.api.ws_schema import validate_chat_server   # verificare il nome esatto
                                                         # dell'helper in __init__.py
from backend.services.agent import events as ev
from backend.services.agent.adapters.parity import to_wire_frames


def test_every_agent_event_maps_to_valid_wire_frames() -> None:
    samples = _one_sample_per_event_class()   # helper nel test: un'istanza per classe
    for event in samples:
        for frame in to_wire_frames(event):
            validate_chat_server(frame)       # non deve sollevare


def test_tool_result_produces_legacy_and_canonical_pair() -> None:
    e = ev.ToolResultEvent(turn_id="t", call_id="c", name="read", status="ok",
                           content_preview="x", artifact_id=None)
    types = [f["type"] for f in to_wire_frames(e)]
    assert types == ["tool_execution_done", "tool.result"]


def test_llm_step_one_emits_no_requery() -> None:
    types = [f["type"] for f in to_wire_frames(ev.LlmStepEvent(turn_id="t", step=1))]
    assert types == ["turn.llm_step"]
    types2 = [f["type"] for f in to_wire_frames(ev.LlmStepEvent(turn_id="t", step=2))]
    assert types2 == ["llm_requery", "turn.llm_step"]
```

Parte B (harness end-to-end v1 vs v2) — nello stesso file:

```python
# Scenari scriptati eseguiti su ENTRAMBI i motori:
#   v1: DirectTurnExecutor + ScriptedInteractionChannel + RecordingEventSink
#       (il harness può importare services.turn: vive nei TEST, il contratto
#        import-linter copre solo backend/services/agent)
#   v2: AgentEngine + double + WsEventPort(translator=to_wire_frames) su un
#       RecordingTransport locale
# Scenari minimi: (1) turno senza tool; (2) turno con 1 tool ok;
#   (3) tool rejected da conferma; (4) cancel a metà.
# Confronto con normalizzazione:
NORMALIZE = {
    "drop_keys": {"correlation_id", "timestamp", "turn_id", "message_id",
                  "audit_id", "interaction_id", "call_id", "tool_call_id",
                  "duration_ms", "cost", "input_tokens", "output_tokens"},
    "collapse_types": {"token", "thinking", "tool_call"},   # sequenze contigue
                     # dello stesso type si riducono a una con content concatenato
}

def test_parity_scenario_no_tools() -> None:
    v1 = _normalized(_run_v1(SCENARIO_NO_TOOLS))
    v2 = _normalized(_run_v2(SCENARIO_NO_TOOLS))
    assert v1 == v2   # stessa sequenza di type + payload salienti
```

Gli scenari e i runner del harness sono la parte più delicata del task: costruiscili
leggendo le firme pubbliche (`DirectTurnExecutor.execute(turn, sink, cancel_event,
session, channel)`, `TurnInput` in `services/turn/models.py`) — la parità si misura sul
WIRE, non sull'implementazione. Se una differenza è legittima (es. v1 emette un frame
che la spec §6 non copre e il FE non usa), documentala nel file come
`KNOWN_DIFFERENCES` con motivazione, e portala in review.

- [ ] **Step 2: FAIL**; **Step 3: implementa translator + harness**;
  **Step 4: verde + ruff/mypy.**

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/adapters/parity.py backend/tests/agent/test_parity.py
git commit -m "feat(engine): parity adapter e harness v1-vs-v2 sul wire attuale"
```

---

### Task 16: Wiring — flag `agent.engine`, bootstrap, ws.py, headless

**Files:**
- Modify: `backend/core/config.py` (modello `AgentConfig`: campo
  `engine: Literal["v1", "v2"] = "v1"`), `config/default.yaml` (`agent.engine: "v1"`)
- Create: `backend/services/agent/runner.py` — composition root del motore
- Modify: `backend/api/routes/chat/ws.py`, `backend/api/routes/chat/headless.py`
- Modify: `docs/flag-registry.md` (censimento flag)
- Test: `backend/tests/agent/test_runner_integration.py`

**Interfaces:**
- Produces:

```python
# backend/services/agent/runner.py
async def run_agent_turn(
    ctx: AppContext, *, request: TurnRequest, session: AsyncSession,
    transport: WsTransport | None,           # None → headless (eventi via sink param)
    sink_fallback: "WSEventSink | None" = None,  # per headless/eval (RecordingEventSink)
    cancel: asyncio.Event,
) -> TurnOutcome:
    """Composition root: costruisce porte+engine e esegue il turno."""
```

- In `ws.py`: dove oggi `create_turn_executor(ctx, llm)` + `executor.execute(...)`,
  ramifica sul flag: `if ctx.config.agent.engine == "v2": run_agent_turn(...)` con un
  mapping `TurnInput → TurnRequest` e `TurnOutcome → TurnResult` LOCALE a ws.py (vive nel
  call site legacy, così il package agent resta pulito; muore col Task 19).
- In `headless.py`: stesso ramo; il `sink` parametro (contratto eval, §6.14) viene
  avvolto in un `WsEventPort`-like che usa `sink.send` — creare in `runner.py` un
  `SinkEventPort(sink, translator=to_wire_frames)`; interaction = porta headless che
  auto-declina: aggiungi in `runner.py` una `AutoDeclineInteractionPort` (confirm →
  REJECTED, client/ask_user → ToolExecutionOutput(ok=False, error="interazione non
  disponibile in headless")).
- `docs/flag-registry.md`: riga per `agent.engine` marcata **TEMPORANEO Fase 1**.

- [ ] **Step 1: Test fallente** — `test_runner_integration.py`: turno headless completo
  su app di test:

```python
async def test_headless_turn_runs_on_v2_engine(monkeypatch) -> None:
    # app testing=True con override agent.engine=v2 (monkeypatch della config o
    # ALICE_AGENT__ENGINE=v2 prima del boot — seguire il pattern dell'eval runner)
    # ScriptedLLM iniettato al posto del llm_service (pattern di
    # tests/evals/test_runner_mock.py MA con doppio proprio: qui si testa il
    # runner, il double è ScriptedLLMPort dietro un LLMService-shim locale)
    result = await run_headless_turn(ctx, conversation_id=None,
                                     prompt="ciao", sink=recording_sink)
    assert result is not None and result.finish_reason == "stop"
    types = [f["type"] for f in recording_sink.events]
    assert "turn.llm_step" in types and "turn.finished" in types
```

- [ ] **Step 2: FAIL**; **Step 3: implementa runner + rami flag**; **Step 4:** verde +
  regressione mirata: `pytest tests/agent/ tests/test_headless_turn.py -v` e
  `pytest tests/evals/ -v` (39 attesi, il mock e2e gira su v1 default). ruff+mypy 0.

- [ ] **Step 5: Commit**

```bash
git add backend/services/agent/runner.py backend/core/config.py config/default.yaml backend/api/routes/chat/ws.py backend/api/routes/chat/headless.py docs/flag-registry.md backend/tests/agent/test_runner_integration.py
git commit -m "feat(engine): wiring flag agent.engine - ws, headless, composition root"
```

---

### Task 17: Audit invarianti + mappatura test legacy

**Files:**
- Create: `backend/tests/agent/invariants_map.md`

**Interfaces:** nessuna — task di verifica/documentazione.

- [ ] **Step 1:** Compila `invariants_map.md` con DUE tabelle:
  1. **Checklist spec §6 → test**: per OGNUNA delle 15 voci, il/i test del motore nuovo
     che la coprono (`file::test_name`). Le voci scoperte vanno colmate ORA con test
     aggiuntivi nei file esistenti (stesso stile TDD).
  2. **Test legacy → destino**: per ogni file in `backend/tests/` che importa
     `services.turn` (elenco con `grep -l "services.turn" backend/tests -r`), la riga:
     test equivalente nel motore nuovo, oppure `DECADE: <motivo>` (es. "fissa la doppia
     emissione, che muore per design"). Questa tabella è il contratto del Task 19.

- [ ] **Step 2:** Fai girare l'intera suite del motore:
  `pytest tests/agent/ -v` → tutti PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/agent/invariants_map.md
git commit -m "test(engine): mappa invarianti spec-to-test e destino dei test legacy"
```

---

### Task 18: Eval run su v2 (GATE — richiede OK utente sulla spesa)

**Files:** nessuno nel repo (output in `evals_output/`).

- [ ] **Step 1:** CHIEDI ALL'UTENTE l'OK sulla spesa (pochi dollari, ~15 min).
- [ ] **Step 2:** Da repo root, venv ROOT:

```powershell
$env:ALICE_AGENT__ENGINE = "v2"
python -m backend.evals run --baseline docs/superpowers/evals/2026-07-17-baseline-fase0/report.json
```

Expected: **23/23, nessuna REGRESSIONE** nel confronto. Se un fail: leggere la trace
JSONL, diagnosticare con systematic-debugging, fixare il motore (MAI abbassare il check),
rilanciare. Con 23/23: annotare run_id e costo per l'handoff.

- [ ] **Step 3:** Nessun commit (il run baseline di FASE si committa a fine Mossa 2).

---

### Task 19: Swap default + demolizione `services/turn/`

**Files:**
- Modify: `config/default.yaml` (`agent.engine: "v2"`), `backend/core/config.py`
  (default `"v2"`)
- Delete: `backend/services/turn/` (TUTTO), `backend/tests/test_tool_loop.py`,
  `test_pipeline.py`, `test_direct_executor_*.py`, `test_turn_*.py`,
  `test_reflective_executor.py`, `test_interaction_channel.py`, e ogni altro file della
  tabella 2 del Task 17 marcato con destino "equivalente/DECADE"
- Modify: `backend/api/routes/chat/ws.py` + `headless.py` (rimozione ramo v1 e del
  mapping locale: ora costruiscono `TurnRequest` direttamente), `_assembly.py` (output →
  `TurnRequest`), `backend/core/config.py` (rimozione blocco `agent.reflection.*`),
  `config/default.yaml` (idem), `docs/flag-registry.md` (rimozione righe
  `agent.reflection.*`; `agent.engine` resta marcato "rimozione a fine Mossa 2")
- Modify: `backend/tests/evals/` SOLO se importano simboli di services.turn
  (es. `TurnResult` type hint in runner eval → sostituire con `TurnOutcome`)

**Procedura (ordine obbligato):**

- [ ] **Step 1:** Swap default a `v2` + run mirato:
  `pytest tests/agent/ tests/evals/ -v` → verdi.
- [ ] **Step 2:** `grep -r "services.turn" backend/ --include="*.py" -l` → per ogni file
  fuori da services/turn stesso, sostituisci l'uso (assembly, ws, headless, factory
  import in altri moduli). NIENTE riferimenti residui.
- [ ] **Step 3:** `git rm -r backend/services/turn` + `git rm` dei test in tabella.
- [ ] **Step 4:** Rimozione reflection config + ramo v1 + import morti.
- [ ] **Step 5:** Gate completi:

```bash
# da backend/:
pytest tests/agent/ tests/evals/ -v
pytest tests/ -k "headless or trigger or chat_ws or assembly or persist" -v
ruff check . ; mypy backend/services/agent backend/api/routes/chat
# da repo root:
lint-imports --config backend/pyproject.toml     # il contratto agent↛turn ora è
                                                 # vacuamente KEPT; NON rimuoverlo
                                                 # ancora (lo toglie Mossa 2)
.\scripts\check-contracts.ps1                    # wire invariato → nessun drift atteso
```

Expected: tutto verde; l'unico rosso tollerato è il pre-esistente AUD-008 voice.

- [ ] **Step 6:** Eval di conferma post-demolizione (il flag ora è default):
  `python -m backend.evals run --no-judge --filter fs-` → 5/5 (smoke economico).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(engine)!: swap a AgentEngine e demolizione del percorso turn legacy

Il motore greenfield e l'unico percorso vivo. Muoiono tool_loop, direct/reflective
executor, pipeline, channel, sink, reflection e i loro test (mappa in
backend/tests/agent/invariants_map.md)."
```

---

### Task 20: Chiusura Mossa 1 — docs, handoff, push

**Files:**
- Modify: `CLAUDE.md` (sezione 3 del backend: sostituire la descrizione
  DirectTurnExecutor/tool_loop con AgentEngine/porte; aggiornare la riga sulla reflection)
- Create: `docs/superpowers/handoffs/2026-07-17-agent-engine-fase1-handoff.md`

- [ ] **Step 1:** Aggiorna CLAUDE.md: la sezione "Tools & the turn executor" descrive ora
  `backend/services/agent/` (engine, porte, adapter, runner, flag `agent.engine`
  temporaneo fino a Mossa 2, reflection rimossa).
- [ ] **Step 2:** Scrivi l'handoff: stato Mossa 1 (task completati, eval run id/costo,
  KNOWN_DIFFERENCES di parità se esistono, debito censito), prossimo passo = piano
  Mossa 2 (wire v2 + FE, da scrivere con writing-plans partendo dalla spec §4-5, §7
  punti 7-9).
- [ ] **Step 3:** Gate finali della mossa (ripeti il blocco del Task 19 Step 5) + push:

```bash
git push -u origin feat/agent-engine-fase1
```

- [ ] **Step 4: Commit finale**

```bash
git add CLAUDE.md docs/superpowers/handoffs/2026-07-17-agent-engine-fase1-handoff.md
git commit -m "docs(engine): CLAUDE.md al motore nuovo + handoff Mossa 1" && git push
```

---

## Note per l'esecutore

- Ogni task: implementer subagent + spec review + quality review (metodo Fase 0).
- Nei dispatch: pytest SEMPRE foreground; mai due pytest concorrenti; mai suite integrale.
- Il branch NON si merge a fine Mossa 1: la fase chiude col piano Mossa 2 (wire v2 + FE)
  sullo stesso branch. L'eval baseline di fase si committa a fine Mossa 2.
- Se un test di parità rivela un comportamento legacy NON coperto dalla spec §6 ma
  necessario (FE o eval lo consumano): STOP, aggiornare la spec (nuova voce §6) con
  l'utente informato, poi procedere. Mai copiare silenziosamente comportamento legacy.
