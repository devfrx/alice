# Agent v2 — Fase 1, Mossa 2: wire v2 + migrazione FE + eliminazione parity/flag — Piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (metodo Fase 1: implementer + spec review + quality review per task, fixer sui finding,
> ledger in `.superpowers/sdd/progress.md`). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Il canale chat parla SOLO il vocabolario canonico v2 (spec §4), emesso dall'adapter
WS definitivo con frame Pydantic tipizzati; il frontend fa il fold del turno su un unico
stream (`agentRun` fonte di verità, spec §5); `adapters/parity.py` e il flag `agent.engine`
eliminati; ogni voce della carry list dell'addendum risolta; fase chiusa con eval 23/23 e
baseline committata.

**Architecture:** Sequenza a tre fasi: (A) task 1–5 risolvono la carry list SENZA toccare il
wire (test WS live prima di tutto, poi tool progress, summary role, interaction arricchite,
persistenza finale nel motore); (B) task 6–10 muovono il contratto in modo additivo → switch
→ purga, così ogni commit resta verde; (C) task 11–12 migrano il FE in lockstep e chiudono i
gate. Il motore resta l'unico emettitore dei fatti del turno; il persist path api-layer emette
solo frame di manutenzione conversazione (context) attraverso lo STESSO trasporto.

**Tech Stack:** FastAPI/Pydantic (`api/ws_schema/`), SQLModel, motore `services/agent/`
(porte Protocol), Electron+Vue3+Pinia, codegen `scripts/gen-contracts.ps1`, pytest, vitest.

---

## Vincoli NON negoziabili (dal programma e dall'utente)

1. **PRINCIPIO PILASTRO**: zero influenza del legacy (né logica né professionalità); niente
   scorciatoie, niente debiti non censiti — la soluzione meno pigra. Vale anche per i test
   double. `services/turn` non esiste più ma il divieto di "ispirarsi" a wording/strutture
   legacy resta (il contratto wire attuale in `api/ws_schema/chat.py` è fair game: È il
   contratto, non il motore legacy).
2. **Contratti**: ogni modifica wire passa da `api/ws_schema/` (Pydantic) → frozen test in
   `backend/tests/contracts/` → `.\scripts\gen-contracts.ps1` → FE `ChatHandlerMap`
   esaustiva. MAI tipi TS a mano (solo `types/generated/index.ts` è editabile).
3. **Eval a pagamento**: ogni `python -m backend.evals run` reale costa denaro → SEMPRE OK
   esplicito dell'utente PRIMA. In questo piano c'è UN solo run reale (task 12).
4. **Gotcha macchina** (da mettere in OGNI dispatch subagent):
   - venv ROOT: `C:\Users\Jays\Desktop\alice\alice\.venv` (attivare con
     `.\.venv\Scripts\Activate.ps1` da repo root). MAI `backend\.venv` (inganna con falsi
     `ModuleNotFoundError`/`qdrant_client` mancante).
   - pytest SEMPRE foreground, da `backend/`, MAI due pytest concorrenti, MAI la suite
     integrale (AUD-008) — solo sottoinsiemi mirati (`tests/agent/ tests/evals/
     tests/contracts/`).
   - Console Windows cp1252: niente Unicode nei print CLI.
   - Subagent crashato/stallato: recuperare via `SendMessage` sull'agent id, NON rilanciare.
5. **Ledger**: `.superpowers/sdd/progress.md`. Su QUESTA macchina il ledger della Mossa 1
   non esiste (sessione M1 eseguita altrove, dir non versionata): al primo task creare
   `.superpowers/sdd/progress.md` fresco con nota d'apertura "Mossa 2 — ledger M1 non
   presente su questa macchina, storia M1 nel handoff
   `docs/superpowers/handoffs/2026-07-17-agent-engine-fase1-handoff.md`".

## Carry list dell'addendum → task che la risolve

| # | Voce addendum | Task |
|---|---|---|
| 5 | Test WS live end-to-end PRIMA di muovere il vocabolario | **Task 1** |
| 1 | Pipeline `tool_progress` orfana (Important) | **Task 2** |
| 6 | Mismatch role del summary di compaction | **Task 3** |
| 4 | `InteractionRequestedEvent` sottile; ask_user/client senza requested/resolved | **Task 4** (+ 8 per il wire) |
| 2 | `turn.finished` payload gap (`final_message_id`, token, cost) | **Task 5** (+ 7 per il wire) |
| 3 | Collasso ownership `done`/`context_info`/compression | **Task 5 + 9** |
| — | `ask_user_required` senza value-pin (debito M1 §6) | **Task 7** (test_wire value-pinned su TUTTI i frame, interaction incluse) |

## Vocabolario v2 finale (riferimento per tutti i task)

Server→client (canale chat, envelope piatto `type`+`origin`+`correlation_id?` invariato):

| type | payload (dopo la purga, task 10) |
|---|---|
| `turn.started` | turn_id, conversation_id, source (`chat\|voice\|headless`) |
| `turn.delta` | turn_id, step, kind (`text\|thinking`), text |
| `turn.llm_step` | turn_id, step *(invariato — eval harness dipende dal nome)* |
| `tool.call` | turn_id, execution_id, tool_name, args, step *(nome/semantica invariati — eval)* |
| `tool.started` | turn_id, execution_id, tool_name |
| `tool.progress` | turn_id, execution_id, tool_name, progress (dict) |
| `tool.result` | turn_id, execution_id, tool_name, status (vocabolario engine: ok/error/parse_error/duplicate/unknown_tool/denied/rejected/timeout/cancelled/budget_exhausted), result (corpo COMPLETO, anche sintetico), content_type?, artifact_id? |
| `interaction.requested` | turn_id, interaction_id, execution_id, kind (`tool_confirmation\|client_tool_call\|ask_user`), tool_name?, args?, risk_level?, description?, reasoning?, allow_remember?, questions? |
| `interaction.resolved` | turn_id, interaction_id, execution_id, kind, outcome |
| `context.usage` | turn_id?, used, available, context_window, percentage (FRAZIONE [0,1]), was_compressed, messages_summarized, is_estimated, breakdown? |
| `context.compaction` | turn_id?, phase (`started\|done\|failed`), messages_summarized?, summary_message_id?, tokens_before?, tokens_after?, error? |
| `turn.warning` | turn_id, code, message |
| `turn.error` | turn_id? (None per errori pre-turno), code, message |
| `turn.usage` | turn_id, step, input_tokens, output_tokens, cost, tool_calls, max_steps *(nome/semantica invariati — eval; cost additivo)* |
| `turn.finished` | turn_id, finish_reason, conversation_id, message_id (""=nessun msg finale), user_message_id, version_group_id?, version_index, steps, tool_calls, input_tokens, output_tokens, cost? |

Client→server: messaggio utente UNTAGGED (`WsUserMessage`, invariato), `cancel` (invariato),
`interaction.response` {interaction_id, kind, approved?, remember?, answers?, success?,
result?, error?} — sostituisce `tool_confirmation_response`/`ask_user_response`/
`client_tool_result`.

Escono dal contratto (task 10): `token`, `thinking`, `tool_call`, `done`, `error`,
`warning`, `tool_execution_start`, `tool_execution_done`, `tool_progress` (legacy piatto),
`context_info`, `context_compression_start/done/failed`, `llm_requery`,
`tool_confirmation_required`, `client_tool_call`, `ask_user_required`,
`agent.critic_invoked`, `agent.warning`; client: `tool_confirmation_response`,
`client_tool_result`, `ask_user_response`.

Canale events (`/api/events/ws`): NON toccato.

**Nota percentuale contesto**: il legacy era incoerente (assembly emetteva frazione [0,1],
il translator di parità (used/window)*100). v2 normalizza a FRAZIONE [0,1] ovunque — il
view-model FE `ContextInfo.percentage` documenta già [0,1].

---

### Task 1: Ledger fresco + test WS live end-to-end sul wire ATTUALE (carry #5)

Pinna il percorso completo `ws_chat` (TestClient WS reale: transport, engine, persist)
PRIMA di muovere il vocabolario. Nei task 7–9 questo test si aggiorna deliberatamente: è il
sismografo del cambio contratto.

**Files:**
- Create: `.superpowers/sdd/progress.md` (ledger fresco, nota d'apertura — vedi vincolo 5)
- Create: `backend/tests/agent/_llm_shim.py`
- Create: `backend/tests/agent/test_ws_chat_live.py`
- Modify: `backend/tests/agent/test_runner_integration.py` (importa lo shim condiviso)

- [ ] **Step 1: estrarre lo shim LLM condiviso**

Spostare la classe `_ScriptedLLMShim` da `test_runner_integration.py` in un nuovo modulo
`backend/tests/agent/_llm_shim.py` (rinominata `ScriptedLLMShim`, contenuto IDENTICO alla
classe attuale, righe 29–110 di `test_runner_integration.py`, docstring inclusa). In
`test_runner_integration.py` sostituire la definizione con
`from backend.tests.agent._llm_shim import ScriptedLLMShim` — attenzione: i test importano
con path `tests.agent...`? No: il pacchetto test usa import relativi al rootdir pytest
`backend/` → usare `from tests.agent._llm_shim import ScriptedLLMShim` (verificare lo stile
di import degli altri file in `tests/agent/`, es. `conftest.py`/`doubles.py`, e adeguarsi).

- [ ] **Step 2: scrivere il test live (fallisce solo se il wire attuale è rotto — deve passare subito)**

`backend/tests/agent/test_ws_chat_live.py`:

```python
"""Test WS live end-to-end del percorso completo /api/ws/chat (carry #5 addendum M1).

Boot dell'app di test (lifespan via TestClient), LLM scriptato, socket WS REALE:
esercita WsTransport (read-pump), run_agent_turn, _persist_final_turn e il DB.
È il sismografo del cambio contratto della Mossa 2: i task 7-9 lo aggiornano
deliberatamente al vocabolario v2.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.core.app import create_app
from tests.agent._llm_shim import ScriptedLLMShim


@pytest.fixture
def live_client():
    """TestClient con lifespan attivo (il with esegue startup/shutdown)."""
    app = create_app(testing=True)
    with TestClient(app) as client:
        yield app, client


def _drain_until(ws: Any, terminal_type: str, limit: int = 200) -> list[dict[str, Any]]:
    """Riceve frame finché arriva ``terminal_type`` (o esplode il limite)."""
    frames: list[dict[str, Any]] = []
    for _ in range(limit):
        frame = ws.receive_json()
        frames.append(frame)
        if frame.get("type") == terminal_type:
            return frames
    raise AssertionError(f"terminal frame {terminal_type!r} mai arrivato: {frames}")


def test_text_turn_full_wire_sequence(live_client) -> None:
    app, client = live_client
    ctx = app.state.context
    ctx.llm_service = ScriptedLLMShim([
        {"type": "token", "content": "Ciao dal wire live."},
        {"type": "usage", "input_tokens": 12, "output_tokens": 6, "cost": 0.0},
        {"type": "done", "finish_reason": "stop"},
    ])
    with client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json({"content": "ciao"})
        frames = _drain_until(ws, "done")

    types = [f["type"] for f in frames]
    # Ordine saliente del wire ATTUALE (Mossa 1, parity): il turno apre con
    # turn.started, ogni step annuncia turn.llm_step, i token streammano, lo
    # usage per-step arriva, turn.finished chiude il motore, done chiude il
    # persist path.
    assert types.index("turn.started") < types.index("turn.llm_step")
    assert "token" in types
    assert "turn.usage" in types
    assert types.index("turn.finished") < types.index("done")
    done = frames[-1]
    assert done["finish_reason"] == "stop"
    assert done["conversation_id"]
    assert done["message_id"]  # messaggio assistant persistito


def test_tool_step_turn_wire_sequence(live_client) -> None:
    """Turno con tool call verso un tool sconosciuto: esercita il gate, la
    tool response sintetica (§6.1.1), il secondo step e la persistenza."""
    app, client = live_client
    ctx = app.state.context
    ctx.llm_service = ScriptedLLMShim([
        # step 1: il modello chiama un tool inesistente
        {"type": "tool_call", "tool_call": {
            "id": "call_live_1", "function": {
                "name": "tool_inesistente", "arguments": "{}"}}},
        {"type": "usage", "input_tokens": 10, "output_tokens": 4, "cost": 0.0},
        {"type": "done", "finish_reason": "tool_calls"},
        # step 2: risposta finale
        {"type": "token", "content": "Fatto."},
        {"type": "usage", "input_tokens": 20, "output_tokens": 3, "cost": 0.0},
        {"type": "done", "finish_reason": "stop"},
    ])
    with client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json({"content": "usa il tool"})
        frames = _drain_until(ws, "done")

    types = [f["type"] for f in frames]
    assert "tool.call" in types
    assert "tool.result" in types
    tool_result = next(f for f in frames if f["type"] == "tool.result")
    assert tool_result["execution_id"] == "call_live_1"
    # llm_requery legacy compare solo dallo step 2 in poi (wire attuale)
    assert "llm_requery" in types
    assert frames[-1]["finish_reason"] == "stop"
```

NOTA per l'implementer: la forma esatta dei chunk `tool_call` accettati da
`ScriptedLLMShim`/`LLMServiceAdapter` va verificata contro
`backend/services/agent/adapters/llm.py` e `tests/evals` mock (formato chunk piattaforma:
`{"type": "tool_call", ...}` con il payload che `LLMServiceAdapter` normalizza). Se lo shim
attuale non supporta chunk tool_call, estenderlo in `_llm_shim.py` replicando il formato che
`LLMService.chat` produce (NON copiando da codice legacy: il riferimento è l'adapter
`llm.py` del motore, che è codice nuovo).

- [ ] **Step 3: eseguire**

Da `backend/` (venv ROOT): `pytest tests/agent/test_ws_chat_live.py tests/agent/test_runner_integration.py -v`
Atteso: PASS (il wire attuale già funziona — il test lo PINNA).

- [ ] **Step 4: commit**

```bash
git add .superpowers/sdd/progress.md backend/tests/agent/_llm_shim.py backend/tests/agent/test_ws_chat_live.py backend/tests/agent/test_runner_integration.py
git commit -m "test(agent): WS live end-to-end sul wire corrente + ledger Mossa 2 (carry #5)"
```

---

### Task 2: Re-wiring tool progress (carry #1 — Important, in testa)

La demolizione ha lasciato `core/tool_progress.py` orfano: il ContextVar
`current_progress_emitter` non viene mai settato → i tool lunghi (cad_generator) non
streammano più progresso. Re-wiring: il motore passa una callback all'`ExecutionPort`;
l'adapter setta il ContextVar per la durata di `execute_tool`; la callback emette
`ToolProgressEvent` (già tradotto da parity in `tool_progress` legacy — wire invariato).

**Files:**
- Modify: `backend/services/agent/ports.py` (firma `ExecutionPort.execute` + alias callback)
- Modify: `backend/services/agent/events.py` (`ToolProgressEvent` + campo `name`)
- Modify: `backend/services/agent/adapters/execution.py` (set/reset ContextVar)
- Modify: `backend/services/agent/engine.py` (`_run_tool_batch._one` passa la closure)
- Modify: `backend/services/agent/adapters/parity.py` (usa `event.name` come `tool_name`)
- Modify: `backend/core/tool_progress.py` (docstring: non più orfano)
- Modify: `backend/tests/agent/doubles.py` (double ExecutionPort supporta `on_progress`)
- Test: `backend/tests/agent/test_engine_tools.py`, `backend/tests/agent/test_adapter_execution.py`

- [ ] **Step 1: test rosso — il motore emette ToolProgressEvent**

In `test_engine_tools.py` aggiungere (adattando ai double/helper esistenti del file —
`_engine_helpers.py` costruisce l'engine con i double di `doubles.py`):

```python
async def test_tool_progress_callback_emits_event(...) -> None:
    """La callback on_progress passata all'ExecutionPort produce ToolProgressEvent
    con turn_id/call_id/name reali e il payload del tool."""
    # double execution che, dentro execute(), invoca on_progress({"phase": "sampling", "percent": 50})
    # scenario: un tool greenlit; asserire che tra gli eventi emessi ci sia
    # ToolProgressEvent(call_id=<call>, name=<tool>, progress={"phase": "sampling", "percent": 50})
```

Il double `ExecutionPort` in `doubles.py` va esteso: `execute(self, call, *, client_ip,
conversation_id, on_progress=None)`; se lo script del double contiene una chiave
`progress`, chiama `await on_progress(payload)` prima di ritornare l'output.

Run: `pytest tests/agent/test_engine_tools.py -v` → FAIL (firma/parametro inesistente).

- [ ] **Step 2: implementare**

`ports.py` — sopra le porte:

```python
#: Callback di progresso tool: riceve il payload parziale del tool
#: (senza type/tool_name/execution_id, che aggiunge chi emette il frame).
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
```

(aggiungere `from collections.abc import Awaitable, Callable` agli import) e:

```python
class ExecutionPort(Protocol):
    """Esecuzione dei tool (server-side); timeout per-tool interno all'adapter."""

    def describe(self, name: str) -> ToolMeta: ...

    async def execute(
        self, call: ToolInvocation, *, client_ip: str | None,
        conversation_id: str,
        on_progress: ProgressCallback | None = None,
    ) -> ToolExecutionOutput: ...
```

`events.py` — `ToolProgressEvent` guadagna il nome del tool:

```python
class ToolProgressEvent(BaseModel):
    """Evento: progresso di esecuzione tool."""

    type: Literal["tool.progress"] = "tool.progress"
    turn_id: str
    call_id: str
    name: str
    progress: dict[str, Any]
    model_config = ConfigDict(frozen=True)
```

`engine.py` — in `_run_tool_batch._one`, prima della try:

```python
        async def _one(call: ToolInvocation) -> tuple[str, _CallResolution]:
            await self._events.emit(ev.ToolStartedEvent(
                turn_id=turn_id, call_id=call.call_id, name=call.name,
            ))

            async def _on_progress(payload: dict[str, Any]) -> None:
                # Best-effort: il progresso non può affondare il tool.
                await self._events.emit(ev.ToolProgressEvent(
                    turn_id=turn_id, call_id=call.call_id, name=call.name,
                    progress=dict(payload),
                ))

            try:
                output = await self._execution.execute(
                    call, client_ip=state.request.client_ip,
                    conversation_id=state.request.conversation_id,
                    on_progress=_on_progress,
                )
```

`execution.py` — `ToolRegistryAdapter.execute` guadagna il parametro e setta il ContextVar
(token-based, task-local: `asyncio.gather` esegue ogni `_one` in un task figlio? NO — le
coroutine di `gather` girano nello stesso task solo se non wrappate; `asyncio.gather` crea
un Task per ogni coroutine → il ContextVar settato dentro `execute` è isolato per-call):

```python
from backend.core.tool_progress import current_progress_emitter
...
    async def execute(
        self, call: ToolInvocation, *, client_ip: str | None, conversation_id: str,
        on_progress: ProgressCallback | None = None,
    ) -> ToolExecutionOutput:
        ...
        token = None
        if on_progress is not None:
            token = current_progress_emitter.set(on_progress)
        try:
            try:
                result = await asyncio.wait_for(
                    self._tool_registry.execute_tool(call.name, dict(call.args), exec_ctx),
                    timeout=timeout_s,
                )
            except TimeoutError:
                return ToolExecutionOutput(
                    ok=False, content="", error=f"timeout dopo {timeout_s}s",
                )
        finally:
            if token is not None:
                current_progress_emitter.reset(token)
        ...
```

`parity.py` — il ramo `ToolProgressEvent` usa il nome reale e il payload annidato:

```python
    if isinstance(event, ev.ToolProgressEvent):
        frame: dict[str, Any] = {
            **event.progress,
            "type": "tool_progress",
            "tool_name": event.name,
            "execution_id": event.call_id,
        }
        return [frame]
```

`core/tool_progress.py` — aggiornare il paragrafo "Mechanism" della docstring: il ContextVar
è settato da `ToolRegistryAdapter.execute` (`backend/services/agent/adapters/execution.py`)
per la durata di ogni invocazione tool; la callback emette `ToolProgressEvent` dal motore.

- [ ] **Step 3: test adapter (ContextVar set/reset)**

In `test_adapter_execution.py`: test che, con un registry double il cui `execute_tool`
chiama `await emit_tool_progress({"phase": "x"})`, la callback `on_progress` riceve il
payload; e che DOPO `execute` il ContextVar è tornato `None` (reset anche su timeout: usare
un registry double che dorme oltre il timeout e verificare `current_progress_emitter.get()
is None` dopo).

- [ ] **Step 4: run mirato + eventi**

`pytest tests/agent/test_engine_tools.py tests/agent/test_adapter_execution.py tests/agent/test_events.py tests/agent/test_parity.py -v` → PASS
(aggiornare `test_events.py`/`test_parity.py` per il nuovo campo `name` e il payload
annidato `progress`).

- [ ] **Step 5: commit**

```bash
git commit -am "fix(engine): re-wiring tool progress via ExecutionPort.on_progress (carry #1)"
```

---

### Task 3: Allineamento role del summary di compaction (carry #6)

Il motore inserisce il summary in-turn come `{"role": "system"}` nudo, mentre la
piattaforma (assembly/persist/`archive_compacted`) lo persiste come `assistant` +
`is_context_summary=True` col prefisso `[Context summary of N earlier messages]:`. Al
turno dopo la history ricaricata diverge da quella in-turn. Allineare il motore alla
convenzione di piattaforma.

**Files:**
- Modify: `backend/services/agent/engine.py` (`_maybe_compact`)
- Test: `backend/tests/agent/test_engine_compaction.py`

- [ ] **Step 1: test rosso**

In `test_engine_compaction.py`, aggiornare/aggiungere il test sulla working history
post-compaction: il primo messaggio dopo la compattazione deve essere

```python
{
    "role": "assistant",
    "content": (
        f"[Context summary of {len(result.archived_message_ids)} earlier "
        f"messages]:\n{summary_text}"
    ),
}
```

Run → FAIL (oggi è `{"role": "system", "content": summary_text}`).

- [ ] **Step 2: implementare**

In `engine.py`, `_maybe_compact`, sostituire:

```python
        state.working_messages = [
            {"role": "system", "content": summary_text},
            *result.kept_messages,
        ]
```

con:

```python
        # Stessa forma con cui la piattaforma persiste e ricarica il summary
        # (role=assistant + prefisso "[Context summary of N...]" — vedi
        # adapters/db.py archive_compacted e _assembly._filter_history_for_llm):
        # la history in-turn e quella ricostruita al turno dopo coincidono.
        summary_entry = {
            "role": "assistant",
            "content": (
                f"[Context summary of {len(result.archived_message_ids)} "
                f"earlier messages]:\n{summary_text}"
            ),
        }
        state.working_messages = [summary_entry, *result.kept_messages]
```

- [ ] **Step 3: run + commit**

`pytest tests/agent/test_engine_compaction.py -v` → PASS

```bash
git commit -am "fix(engine): summary di compaction in-turn allineato alla convenzione di piattaforma (carry #6)"
```

---

### Task 4: Interaction arricchite + `interaction_id` nelle porte (carry #4, parte interna)

Gli eventi `interaction.requested/resolved` devono portare il payload completo (spec §4) e
coprire TUTTI e tre i kind (oggi solo confirm). Le porte interaction ricevono
l'`interaction_id` (serve al task 8 per la correlazione wire). Il wire resta invariato
(parity non traduce il payload arricchito).

**Files:**
- Modify: `backend/services/agent/events.py` (`InteractionRequestedEvent` +
  `InteractionResolvedEvent` con `call_id`)
- Modify: `backend/services/agent/ports.py` (firme `InteractionPort`)
- Modify: `backend/services/agent/engine.py` (`_confirm_call`, `_run_interactive`)
- Modify: `backend/services/agent/adapters/ws.py` (`WsInteractionPort` accetta
  `interaction_id`, per ora lo ignora)
- Modify: `backend/services/agent/runner.py` (`AutoDeclineInteractionPort` firma)
- Modify: `backend/tests/agent/doubles.py` (double InteractionPort firma)
- Test: `backend/tests/agent/test_engine_tools.py`, `test_events.py`, `test_adapter_ws.py`,
  `test_runner_integration.py`

- [ ] **Step 1: test rosso**

In `test_engine_tools.py`:

```python
async def test_ask_user_and_client_emit_interaction_events(...) -> None:
    """ask_user e client tool emettono interaction.requested/resolved con
    payload completo; outcome answered/executed sui success, failed sugli
    errori."""
    # scenario A: tool con meta.interactive == "ask_user", double interaction
    # ritorna ok=True → eventi attesi nella sequenza:
    #   InteractionRequestedEvent(kind="ask_user", call_id=<id>,
    #       payload={"questions": <call.args["questions"]>}, tool_name=<nome>)
    #   InteractionResolvedEvent(kind="ask_user", outcome="answered", call_id=<id>)
    # scenario B: meta.client_executed, double ok=False → outcome "executed"? NO:
    #   ok=True → "executed"; ok=False → "failed".

async def test_confirm_event_payload_is_complete(...) -> None:
    """Il requested del confirm porta args/risk_level/description/reasoning/
    allow_remember (non più il payload minimale)."""
```

Run → FAIL.

- [ ] **Step 2: eventi**

`events.py`:

```python
class InteractionRequestedEvent(BaseModel):
    """Evento: interazione richiesta (payload COMPLETO, spec §4).

    ``payload`` per kind:
      * ``confirm``: args, risk_level, description, reasoning, allow_remember.
      * ``ask_user``: questions (raw dagli args del tool, normalizzate al wire).
      * ``client``: args.
    """

    type: Literal["interaction.requested"] = "interaction.requested"
    turn_id: str
    interaction_id: str
    kind: str
    call_id: str
    payload: dict[str, Any]
    tool_name: str | None = None
    model_config = ConfigDict(frozen=True)


class InteractionResolvedEvent(BaseModel):
    """Evento: interazione risolta."""

    type: Literal["interaction.resolved"] = "interaction.resolved"
    turn_id: str
    interaction_id: str
    kind: str
    call_id: str
    outcome: str
    model_config = ConfigDict(frozen=True)
```

(`call_id` è NUOVO su resolved: il FE correla l'attività tool.)

- [ ] **Step 3: porte**

`ports.py` — `InteractionPort`:

```python
class InteractionPort(Protocol):
    """Interazioni con l'utente: conferma, esecuzione client-side, ask_user.

    ``interaction_id`` è la chiave di correlazione wire della richiesta: il
    motore la genera, la emette nell'evento ``interaction.requested`` e la
    passa alla porta, che DEVE usarla per correlare la risposta del client.
    """

    async def confirm_tool(
        self, call: ToolInvocation, *, interaction_id: str, verdict: GateVerdict,
        timeout_s: float, cancel: asyncio.Event,
    ) -> InteractionOutcome: ...

    async def run_client_tool(
        self, call: ToolInvocation, *, interaction_id: str, timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput: ...

    async def ask_user(
        self, call: ToolInvocation, *, interaction_id: str, timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput: ...
```

Aggiornare `WsInteractionPort` (accetta e per ora ignora `interaction_id` — commento: "usata
dal task 8 per la correlazione interaction.response"), `AutoDeclineInteractionPort` e i
double in `doubles.py` alla nuova firma.

- [ ] **Step 4: engine**

`_confirm_call`: arricchire il payload dell'evento requested:

```python
        await self._events.emit(ev.InteractionRequestedEvent(
            turn_id=turn_id, interaction_id=interaction_id, kind="confirm",
            call_id=call.call_id, tool_name=call.name,
            payload={
                "args": call.args,
                "risk_level": verdict.risk_level,
                "description": verdict.description,
                "reasoning": verdict.reason,
                "allow_remember": True,
            },
        ))
        outcome = await self._interaction.confirm_tool(
            call, interaction_id=interaction_id, verdict=verdict,
            timeout_s=self._confirmation_timeout_s, cancel=cancel,
        )
        await self._events.emit(ev.InteractionResolvedEvent(
            turn_id=turn_id, interaction_id=interaction_id, kind="confirm",
            call_id=call.call_id, outcome=outcome.value,
        ))
```

**INVARIANTE (documentare nel docstring di `_confirm_call` e `_run_interactive`)**: nessun
`await` tra il ritorno di `emit(InteractionRequestedEvent)` e la chiamata alla porta — la
porta registra il waiter in modo sincrono prima del primo await (task 8), quindi la risposta
del client non può andare persa.

`_run_interactive` — nuova firma `(self, turn_id: str, call, *, kind, timeout_s, cancel)`
(aggiornare il call site in `_gate_call` passando `turn_id`; `_gate_call` ha già `turn_id`):

```python
    async def _run_interactive(
        self,
        turn_id: str,
        call: ToolInvocation,
        *,
        kind: str,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> _CallResolution:
        """Esegue una call interattiva (ask_user o client-side) con eventi
        requested/resolved (carry #4)."""
        interaction_id = uuid.uuid4().hex
        if kind == "ask_user":
            payload: dict[str, Any] = {"questions": call.args.get("questions")}
        else:
            payload = {"args": call.args}
        await self._events.emit(ev.InteractionRequestedEvent(
            turn_id=turn_id, interaction_id=interaction_id, kind=kind,
            call_id=call.call_id, tool_name=call.name, payload=payload,
        ))
        try:
            if kind == "ask_user":
                output = await self._interaction.ask_user(
                    call, interaction_id=interaction_id,
                    timeout_s=timeout_s, cancel=cancel,
                )
            else:
                output = await self._interaction.run_client_tool(
                    call, interaction_id=interaction_id,
                    timeout_s=timeout_s, cancel=cancel,
                )
        except EngineDisconnected:
            await self._events.emit(ev.InteractionResolvedEvent(
                turn_id=turn_id, interaction_id=interaction_id, kind=kind,
                call_id=call.call_id, outcome="disconnected",
            ))
            return _CallResolution(
                content="Chiamata annullata (disconnesso).",
                status=_STATUS_CANCELLED, disconnect=True,
            )
        if output.ok:
            outcome = "answered" if kind == "ask_user" else "executed"
        else:
            # timeout/cancel/errore client convergono su "failed": la porta
            # ritorna un ToolExecutionOutput e non distingue l'esito wire
            # (residuo deliberato, censito nel ledger).
            outcome = "failed"
        await self._events.emit(ev.InteractionResolvedEvent(
            turn_id=turn_id, interaction_id=interaction_id, kind=kind,
            call_id=call.call_id, outcome=outcome,
        ))
        status = _STATUS_OK if output.ok else _STATUS_ERROR
        return _CallResolution(content=output.content, status=status, output=output)
```

`parity.py`: nel ramo `InteractionResolvedEvent` usare ora `event.call_id` come
`execution_id` (il commento sull'id volatile decade); il ramo requested resta invariato
(payload non tradotto sul wire legacy).

- [ ] **Step 5: run + commit**

`pytest tests/agent/ -q` (da `backend/`, foreground) → tutti verdi.

```bash
git commit -am "feat(engine): interaction.requested/resolved completi su confirm/ask_user/client + interaction_id nelle porte (carry #4)"
```

---

### Task 5: Persistenza finale nel motore + `TurnFinishedEvent` arricchito (carry #2 + #3, parte 1)

Il motore diventa proprietario del salvataggio del messaggio assistant finale (incluso il
recovery su disconnect): `final_message_id` reale, token/cost reali su `turn.finished`.
`_persist.py` smette di creare il messaggio ma emette ancora `done` legacy (wire invariato
fino al task 9).

**Files:**
- Modify: `backend/services/agent/models.py` (`TurnRequest.user_message_id`)
- Modify: `backend/services/agent/ports.py` (`PersistencePort.save_final_message`)
- Modify: `backend/services/agent/adapters/db.py` (implementazione)
- Modify: `backend/services/agent/events.py` (`TurnFinishedEvent` arricchito)
- Modify: `backend/services/agent/engine.py` (`_finish` con matrice di salvataggio)
- Modify: `backend/services/agent/adapters/parity.py` (`turn.finished` con token reali)
- Modify: `backend/api/routes/chat/_assembly.py` (popola `user_message_id`)
- Modify: `backend/api/routes/chat/_persist.py` (non crea più il messaggio finale)
- Modify: `backend/api/routes/chat/ws.py` (ramo disconnect: niente più recovery inline)
- Modify: `backend/tests/agent/doubles.py` (double persistence)
- Test: `backend/tests/agent/test_engine_loop.py`, `test_adapter_db.py`, `test_parity.py`,
  `test_ws_chat_live.py`

- [ ] **Step 1: test rosso (matrice di salvataggio)**

In `test_engine_loop.py`:

```python
# Matrice (§_finish): stop → salva se...
#   COMPLETED/LENGTH/MAX_STEPS → content.strip() non vuoto OPPURE tool_calls == 0
#   CANCELLED                  → content o thinking non vuoti
#   DISCONNECTED               → content non vuoto (recovery message)
#   ERROR                      → mai
async def test_finish_saves_final_message_on_completed(...): ...
async def test_finish_skips_save_on_tool_only_turn(...): ...      # content vuoto + tool_calls>0
async def test_finish_saves_recovery_on_disconnect(...): ...
async def test_finish_never_saves_on_error(...): ...
async def test_turn_finished_event_carries_ids_and_totals(...): ...
# turn.finished: final_message_id = id ritornato dal save; conversation_id,
# user_message_id, version_group_id/index dalla request; input/output_tokens e
# cost = totali accumulati; emesso DOPO save+checkpoint.
async def test_save_failure_degrades_to_error(...): ...
# persistence double che solleva su save_final_message → turn.error(code=
# "persist_failed") emesso, finish_reason "error", nessuna eccezione fuori.
```

Il double persistence in `doubles.py` registra le chiamate `save_final_message` e ritorna
un id fisso (`"final-msg-1"`).

- [ ] **Step 2: modelli, porta, eventi**

`models.py` — `TurnRequest` guadagna (dopo `version_index`):

```python
    user_message_id: str | None = None
```

(docstring: "ID del messaggio utente che apre il turno; alimenta turn.finished").

`ports.py` — `PersistencePort` guadagna:

```python
    async def save_final_message(
        self, *, content: str, thinking: str,
        input_tokens: int, output_tokens: int, cost: float,
    ) -> str: ...
```

`events.py` — `TurnFinishedEvent`:

```python
class TurnFinishedEvent(BaseModel):
    """Evento: turno completato (payload completo, carry #2)."""

    type: Literal["turn.finished"] = "turn.finished"
    turn_id: str
    finish_reason: str
    conversation_id: str
    final_message_id: str | None
    user_message_id: str | None
    version_group_id: str | None
    version_index: int
    steps: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    model_config = ConfigDict(frozen=True)
```

- [ ] **Step 3: adapter db**

`db.py`:

```python
    async def save_final_message(
        self, *, content: str, thinking: str,
        input_tokens: int, output_tokens: int, cost: float,
    ) -> str:
        """Persiste il messaggio assistant FINALE del turno (flush, no commit).

        La DECISIONE di salvare è del motore (matrice in ``engine._finish``);
        qui solo la scrittura: version fields del turno, ``token_count`` quando
        i token reali sono noti, ``usage`` (accounting OpenRouter) quando il
        turno ha un costo. Divergenza minore censita: il legacy legava
        ``token_count`` alla presenza di context_manager/context_window (era il
        gate del frame context_info, non della colonna) — qui si persiste
        sempre che ``input_tokens > 0``.
        """
        message = Message(
            conversation_id=self._conversation_id,
            role="assistant",
            content=content,
            thinking_content=thinking or None,
            version_group_id=self._version_group_id,
            version_index=(
                self._version_index if self._version_index is not None else 0
            ),
        )
        if input_tokens > 0:
            message.token_count = input_tokens
        if cost > 0:
            message.usage = {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "cost": round(cost, 8),
            }
        self._session.add(message)
        await self._session.flush()
        return str(message.id)
```

Test in `test_adapter_db.py`: riga scritta con role/content/version corretti; `usage`
presente solo con `cost > 0`; `token_count` solo con `input_tokens > 0`; id ritornato.

- [ ] **Step 4: engine `_finish`**

Sostituire il corpo di `_finish` (mantenendo il calcolo di `final_content` esistente, che
va SPOSTATO PRIMA del salvataggio):

```python
    async def _finish(
        self,
        turn_id: str,
        stop: StopReason | None,
        state: _TurnState,
        budget: BudgetTracker,
    ) -> TurnOutcome:
        """Persiste il messaggio finale (matrice sotto), emette ``TurnFinishedEvent``
        e costruisce il ``TurnOutcome``. Chiamato SEMPRE."""
        resolved_stop = stop if stop is not None else StopReason.ERROR
        finish_reason = STOP_TO_FINISH[resolved_stop]
        if resolved_stop is StopReason.MAX_STEPS and state.pending_tool_intent:
            await self._events.emit(ev.TurnWarningEvent(
                turn_id=turn_id, code="max_steps",
                message="Budget di step esaurito con tool call in sospeso.",
            ))
        # (blocco esistente: final_content dall'ultimo step / fallback sui rami
        #  cancelled/disconnected/error — INVARIATO, solo spostato qui sopra)
        if resolved_stop in (
            StopReason.CANCELLED, StopReason.DISCONNECTED, StopReason.ERROR,
        ):
            final_content = state.content or state.last_step_content
        else:
            final_content = state.content

        # Matrice di salvataggio del messaggio finale (carry #2/#3):
        #   COMPLETED/LENGTH/MAX_STEPS → prosa finale, o turno senza tool
        #   CANCELLED                  → parziale (content o thinking)
        #   DISCONNECTED               → recovery message (era in ws.py)
        #   ERROR                      → mai (il persist path fa solo rollback)
        if resolved_stop in (
            StopReason.COMPLETED, StopReason.LENGTH, StopReason.MAX_STEPS,
        ):
            should_save = bool(final_content.strip()) or state.tool_calls == 0
        elif resolved_stop is StopReason.CANCELLED:
            should_save = bool(final_content or state.thinking)
        elif resolved_stop is StopReason.DISCONNECTED:
            should_save = bool(final_content)
        else:  # ERROR
            should_save = False
        if should_save:
            try:
                state.final_assistant_message_id = (
                    await self._persistence.save_final_message(
                        content=final_content, thinking=state.thinking,
                        input_tokens=state.input_tokens,
                        output_tokens=state.output_tokens, cost=state.cost,
                    )
                )
                await self._persistence.checkpoint()
            except Exception as exc:
                logger.exception("AgentEngine: persistenza finale fallita")
                await self._events.emit(ev.TurnErrorEvent(
                    turn_id=turn_id, code="persist_failed", message=str(exc),
                ))
                resolved_stop = StopReason.ERROR
                finish_reason = STOP_TO_FINISH[resolved_stop]
                state.final_assistant_message_id = None

        await self._events.emit(ev.TurnFinishedEvent(
            turn_id=turn_id, finish_reason=finish_reason,
            conversation_id=state.request.conversation_id,
            final_message_id=state.final_assistant_message_id,
            user_message_id=state.request.user_message_id,
            version_group_id=state.request.version_group_id,
            version_index=state.request.version_index or 0,
            steps=budget.steps, tool_calls=state.tool_calls,
            input_tokens=state.input_tokens, output_tokens=state.output_tokens,
            cost=state.cost,
        ))
        return TurnOutcome(
            content=final_content, thinking=state.thinking,
            finish_reason=finish_reason, stop_reason=resolved_stop,
            steps=budget.steps, tool_calls=state.tool_calls,
            input_tokens=state.input_tokens, output_tokens=state.output_tokens,
            cost=state.cost,
            final_assistant_message_id=state.final_assistant_message_id,
        )
```

- [ ] **Step 5: parity + assembly + persist + ws**

`parity.py` — ramo `TurnFinishedEvent` (token reali, non più 0; il commento decade):

```python
    if isinstance(event, ev.TurnFinishedEvent):
        return [{
            "type": "turn.finished",
            "turn_id": event.turn_id,
            "finish_reason": event.finish_reason,
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
            "steps": event.steps,
            "cost": event.cost,
        }]
```

`_assembly.py` — nella costruzione della `TurnRequest` aggiungere
`user_message_id=str(user_msg.id),`.

`_persist.py` — tre cambi, wire INVARIATO (`done` è ancora emesso da qui):
1. Ramo `cancelled`: NON creare più `cancel_msg` (il motore l'ha già salvato).
   `asst_msg_id = result.final_assistant_message_id or ""`; resta l'update di
   `conv.updated_at`/title/commit sotto la stessa condizione
   (`result.tool_calls > 0 or result.content or result.thinking`).
2. Percorso normale: eliminare la creazione di `asst_msg` e la persistenza di
   usage/token_count (ora nel motore via `save_final_message`);
   `asst_msg_id = result.final_assistant_message_id or ""`. Il blocco `context_info`
   (v2-6) resta; il blocco `context_snapshot` (v2-5) resta; title/updated_at restano.
3. Il ramo error resta identico (rollback difensivo + done error).

`ws.py` — il ramo disconnect si riduce a:

```python
                if result.finish_reason == "disconnected":
                    # Il recovery message parziale è già stato persistito dal
                    # motore (matrice _finish, carry #3): qui si esce e basta.
                    raise WebSocketDisconnect()
```

(rimuovere l'import di `Message` se resta inutilizzato).

Divergenza minore da CENSIRE nel ledger: il recovery su disconnect non aggiorna più
`conv.updated_at` (il legacy lo faceva in `ws.py`; il motore persiste solo il messaggio).
Se la review la giudica regressione reale, il fix è nell'adapter
(`save_final_message` aggiorna `Conversation.updated_at`), non in `ws.py`.

- [ ] **Step 6: run mirato**

`pytest tests/agent/ tests/evals/ -q` (foreground, da `backend/`) → 150+ verdi (i test
nuovi si sommano; aggiornare `test_parity.py`/`test_events.py` per i campi nuovi, e i test
di `test_runner_integration.py`/`test_ws_chat_live.py` devono restare verdi SENZA modifiche
di sequenza — `done` è ancora lì).

- [ ] **Step 7: commit**

```bash
git commit -am "feat(engine): persistenza del messaggio finale nel motore + turn.finished con id/token/cost reali (carry #2/#3)"
```

---

### Task 6: Vocabolario v2 ADDITIVO in `api/ws_schema/chat.py` + frozen test

Aggiunge i modelli v2 nuovi e i campi v2 (opzionali) sui modelli che mantengono il nome.
Nessun emettitore cambia: contratto più largo, wire identico. La purga (task 10) toglie il
legacy e irrigidisce gli opzionali.

**Files:**
- Modify: `backend/api/ws_schema/chat.py`
- Modify: `backend/tests/contracts/test_ws_schema_chat.py`

- [ ] **Step 1: test rosso (frozen vocabulary additivo)**

In `test_ws_schema_chat.py` aggiungere a `EXPECTED_CHAT_SERVER_TYPES`:
`"turn.delta"`, `"tool.started"`, `"tool.progress"`, `"context.usage"`,
`"context.compaction"`, `"turn.warning"`, `"turn.error"`; a
`EXPECTED_CHAT_CLIENT_TYPES`: `"interaction.response"`. Aggiungere representative frames
(vedi Step 2 per le shape; almeno un frame per tipo nuovo, e per `interaction.requested`
un frame CON payload completo: args+risk_level+description+reasoning+allow_remember, e uno
kind=ask_user con questions). Run → FAIL.

- [ ] **Step 2: modelli**

In `chat.py`, nuova sezione "Canonical v2 (Mossa 2)":

```python
class WsTurnDelta(ChatServerFrame):
    """Delta di output del turno (testo o thinking)."""

    type: Literal["turn.delta"]
    turn_id: str
    step: int
    kind: Literal["text", "thinking"]
    text: str


class WsToolStarted(ChatServerFrame):
    """Un tool greenlit ha iniziato l'esecuzione server-side."""

    type: Literal["tool.started"]
    turn_id: str
    execution_id: str
    tool_name: str


class WsToolProgress(ChatServerFrame):
    """Progresso incrementale di un tool lungo (payload annidato, tipizzato)."""

    type: Literal["tool.progress"]
    turn_id: str
    execution_id: str
    tool_name: str
    progress: dict[str, Any]


class WsContextUsage(ChatServerFrame):
    """Utilizzo della finestra di contesto (percentage = frazione [0,1])."""

    type: Literal["context.usage"]
    turn_id: str | None = None
    used: int
    available: int
    context_window: int
    percentage: float
    was_compressed: bool = False
    messages_summarized: int = 0
    is_estimated: bool = True
    breakdown: WsContextBreakdown | None = None


class WsContextCompaction(ChatServerFrame):
    """Ciclo di compattazione del contesto (started/done/failed)."""

    type: Literal["context.compaction"]
    turn_id: str | None = None
    phase: Literal["started", "done", "failed"]
    messages_summarized: int | None = None
    summary_message_id: str | None = None
    tokens_before: int | None = None
    tokens_after: int | None = None
    error: str | None = None


class WsTurnWarning(ChatServerFrame):
    """Avvertimento non fatale del turno."""

    type: Literal["turn.warning"]
    turn_id: str
    code: str
    message: str


class WsTurnError(ChatServerFrame):
    """Errore del turno; ``turn_id`` assente per errori pre-turno (validazione)."""

    type: Literal["turn.error"]
    turn_id: str | None = None
    code: str
    message: str
```

Estensioni ADDITIVE (campi opzionali, irrigiditi nel task 10) sui modelli esistenti:

```python
class WsTurnStarted(ChatServerFrame):
    type: Literal["turn.started"]
    turn_id: str
    conversation_id: str
    source: Literal["chat", "voice", "headless"] | None = None      # v2

class WsTurnToolCall(ChatServerFrame):
    ...campi esistenti...
    step: int | None = None                                          # v2

class WsTurnToolResult(ChatServerFrame):
    ...campi esistenti (success/result/content_type/artifact_id)...
    status: str | None = None                                        # v2

class WsInteractionRequested(ChatServerFrame):
    type: Literal["interaction.requested"]
    turn_id: str
    execution_id: str
    kind: InteractionKind
    tool_name: str | None = None
    interaction_id: str | None = None                                # v2
    args: dict[str, Any] | None = None                               # v2
    risk_level: RiskLevel | None = None                              # v2
    description: str | None = None                                   # v2
    reasoning: str | None = None                                     # v2
    allow_remember: bool | None = None                               # v2
    questions: list[WsAskUserQuestion] | None = None                 # v2

class WsInteractionResolved(ChatServerFrame):
    ...campi esistenti...
    interaction_id: str | None = None                                # v2

class WsTurnUsage(ChatServerFrame):
    ...campi esistenti...
    cost: float | None = None                                        # v2

class WsTurnFinished(ChatServerFrame):
    type: Literal["turn.finished"]
    turn_id: str
    finish_reason: str | None = None
    input_tokens: int
    output_tokens: int
    steps: int
    cost: float | None = None
    conversation_id: str | None = None                               # v2
    message_id: str | None = None                                    # v2
    user_message_id: str | None = None                               # v2
    version_group_id: str | None = None                              # v2
    version_index: int | None = None                                 # v2
    tool_calls: int | None = None                                    # v2
```

Client:

```python
class WsInteractionResponse(ClientFrame):
    """Risposta unica alle interazioni (kind discriminato nel payload)."""

    type: Literal["interaction.response"]
    interaction_id: str
    kind: InteractionKind
    # tool_confirmation
    approved: bool | None = None
    remember: RememberChoice = "none"
    # ask_user
    answers: list[WsAskUserAnswer] | None = None
    # client_tool_call
    success: bool | None = None
    result: str | list[Any] | dict[str, Any] | None = None
    error: str | None = None
```

Aggiungere i 8 modelli nuovi alle union `ChatServerMessage`/`ChatClientMessage`.
NOTA nome: il modello legacy `WsToolProgress` (type `tool_progress`) va RINOMINATO
`WsToolProgressLegacy` per liberare il nome (aggiornare gli import se esistono — grep
`WsToolProgress` in backend; il FE usa i nomi generati, rigenerati al task 11).

- [ ] **Step 3: run + commit**

`pytest tests/contracts/ -q` → PASS. `pytest tests/agent/ -q` → PASS (nessun emettitore
toccato).

```bash
git commit -am "feat(contracts): vocabolario chat v2 additivo in ws_schema (frame nuovi + campi v2 opzionali)"
```

---

### Task 7: `adapters/wire.py` definitivo + switch dell'emissione eventi; parity ELIMINATO

Il translator definitivo costruisce ogni frame ATTRAVERSO i modelli Pydantic di
`ws_schema` (validazione by-construction: risolve il debito M1 #1 "frame non validati a
runtime"). `WsEventPort`/`SinkEventPort` passano a `to_v2_frames`. `parity.py` e il suo
harness muoiono. Nasce `test_wire.py` value-pinned su TUTTI i frame (chiude anche il
debito M1 #6: `ask_user`/interaction senza value-pin).

**Files:**
- Create: `backend/services/agent/adapters/wire.py`
- Create: `backend/tests/agent/test_wire.py`
- Delete: `backend/services/agent/adapters/parity.py`
- Delete: `backend/tests/agent/test_parity.py`
- Modify: `backend/services/agent/runner.py` (import translator)
- Modify: `backend/services/agent/engine.py` (`ToolResultEvent` con corpo pieno)
- Modify: `backend/services/agent/events.py` (`ToolResultEvent`: `result: str`, via
  `content_preview`)
- Modify: `backend/tests/agent/test_events.py`, `test_runner_integration.py`,
  `test_ws_chat_live.py` (sequenza: niente più frame legacy dal motore)

- [ ] **Step 1: `ToolResultEvent` porta il corpo COMPLETO sempre**

La distinzione result-solo-sui-success era un artefatto del confronto di parità (morto con
parity). In `events.py`:

```python
class ToolResultEvent(BaseModel):
    """Evento: risultato di esecuzione tool (corpo completo, anche sintetico)."""

    type: Literal["tool.result"] = "tool.result"
    turn_id: str
    call_id: str
    name: str
    status: str
    result: str
    artifact_id: str | None
    content_type: str | None = None
    model_config = ConfigDict(frozen=True)
```

In `engine.py` (`_run_tool_step`, emissione ToolResultEvent):

```python
            await self._events.emit(ev.ToolResultEvent(
                turn_id=turn_id, call_id=call.call_id, name=call.name,
                status=resolution.status, result=resolution.content,
                artifact_id=artifact_id,
                content_type=(
                    resolution.output.content_type
                    if resolution.output is not None else None
                ),
            ))
```

- [ ] **Step 2: test rosso — `test_wire.py`**

Un test parametrico per OGNI classe di `AgentEvent`: costruisce l'evento con valori pinnati
e asserisce il/i frame risultante/i CAMPO PER CAMPO (value-pinned), più
`validate_chat_server(frame)` su ogni frame. Esempi obbligatori:

```python
def test_tool_result_frame() -> None:
    frames = to_v2_frames(ev.ToolResultEvent(
        turn_id="t1", call_id="c1", name="web_search", status="denied",
        result="Chiamata negata: plan tier.", artifact_id=None,
    ))
    assert frames == [{
        "type": "tool.result", "origin": "agent", "turn_id": "t1",
        "execution_id": "c1", "tool_name": "web_search", "status": "denied",
        "success": False,  # presente fino alla purga (task 10 lo rimuove)
        "result": "Chiamata negata: plan tier.",
    }]

def test_interaction_requested_ask_user_value_pinned() -> None:
    frames = to_v2_frames(ev.InteractionRequestedEvent(
        turn_id="t1", interaction_id="i1", kind="ask_user", call_id="c1",
        tool_name="agent_ask_user",
        payload={"questions": [{"id": "q1", "text": "Quale?", "type": "radio",
                                "options": ["a"], "extraneous": "drop-me"}]},
    ))
    assert frames == [{
        "type": "interaction.requested", "origin": "agent", "turn_id": "t1",
        "interaction_id": "i1", "execution_id": "c1", "kind": "ask_user",
        "tool_name": "agent_ask_user",
        "questions": [{"id": "q1", "text": "Quale?", "type": "radio",
                       "options": ["a"], "allow_free_text": False}],
    }]
```

(le chiavi `None` sono OMESSE dai frame — `exclude_none`; `origin` è presente col default
`"agent"`; `correlation_id` omesso.)

- [ ] **Step 3: implementare `wire.py`**

```python
"""Translator DEFINITIVO: ``AgentEvent`` → frame wire v2 (spec Fase 1 §4).

Ogni frame è costruito ATTRAVERSO il modello Pydantic del contratto
(``backend/api/ws_schema/chat.py``) e serializzato con
``model_dump(mode="json", exclude_none=True)``: un frame che non valida non
può essere costruito — la garanzia sul wire è by-construction, non più solo
a livello di test (chiude il debito M1 "frame del motore non validati a
runtime"). Un evento = un frame; nessun frame legacy.
"""

from __future__ import annotations

from typing import Any

from backend.api.ws_schema import chat as ws
from backend.services.agent import events as ev
from backend.services.agent.events import AgentEvent

#: kind interno → InteractionKind del contratto.
_INTERACTION_KIND: dict[str, str] = {
    "confirm": "tool_confirmation",
    "client": "client_tool_call",
    "ask_user": "ask_user",
}


def _dump(frame: Any) -> dict[str, Any]:
    return frame.model_dump(mode="json", exclude_none=True)


def normalize_questions(raw: Any) -> list[dict[str, Any]]:
    """Normalizza le domande di ``ask_user`` alla forma del contratto.

    ``WsAskUserQuestion`` (extra='forbid') richiede esattamente
    id/text/type/options/allow_free_text: chiavi estranee filtrate, default
    riempiti, tipi coartati in modo difensivo.
    """
    questions: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return questions
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        qtype = item.get("type")
        options = item.get("options")
        questions.append({
            "id": str(item.get("id") or f"q{index + 1}"),
            "text": str(item.get("text") or ""),
            "type": qtype if qtype in ("radio", "checkbox") else "radio",
            "options": [str(o) for o in options] if isinstance(options, list) else [],
            "allow_free_text": bool(item.get("allow_free_text", False)),
        })
    return questions


def to_v2_frames(event: AgentEvent) -> list[dict[str, Any]]:
    """Traduce un evento interno nel suo frame wire v2 (0 o 1 frame)."""
    if isinstance(event, ev.TurnStartedEvent):
        return [_dump(ws.WsTurnStarted(
            type="turn.started", turn_id=event.turn_id,
            conversation_id=event.conversation_id, source=event.source,
        ))]
    if isinstance(event, ev.TurnDeltaEvent):
        return [_dump(ws.WsTurnDelta(
            type="turn.delta", turn_id=event.turn_id, step=event.step,
            kind=event.kind, text=event.text,
        ))]
    if isinstance(event, ev.LlmStepEvent):
        return [_dump(ws.WsTurnLlmStep(
            type="turn.llm_step", turn_id=event.turn_id, step=event.step,
        ))]
    if isinstance(event, ev.ToolCallEvent):
        return [_dump(ws.WsTurnToolCall(
            type="tool.call", turn_id=event.turn_id,
            execution_id=event.call.call_id, tool_name=event.call.name,
            args=event.call.args, step=event.step,
        ))]
    if isinstance(event, ev.ToolStartedEvent):
        return [_dump(ws.WsToolStarted(
            type="tool.started", turn_id=event.turn_id,
            execution_id=event.call_id, tool_name=event.name,
        ))]
    if isinstance(event, ev.ToolProgressEvent):
        return [_dump(ws.WsToolProgress(
            type="tool.progress", turn_id=event.turn_id,
            execution_id=event.call_id, tool_name=event.name,
            progress=event.progress,
        ))]
    if isinstance(event, ev.ToolResultEvent):
        return [_dump(ws.WsTurnToolResult(
            type="tool.result", turn_id=event.turn_id,
            execution_id=event.call_id, tool_name=event.name,
            status=event.status, success=event.status == "ok",
            result=event.result, content_type=event.content_type,
            artifact_id=event.artifact_id,
        ))]
    if isinstance(event, ev.InteractionRequestedEvent):
        payload = event.payload
        questions = payload.get("questions")
        return [_dump(ws.WsInteractionRequested(
            type="interaction.requested", turn_id=event.turn_id,
            interaction_id=event.interaction_id,
            execution_id=event.call_id,
            kind=_INTERACTION_KIND.get(event.kind, event.kind),
            tool_name=event.tool_name,
            args=payload.get("args"),
            risk_level=payload.get("risk_level"),
            description=payload.get("description"),
            reasoning=payload.get("reasoning"),
            allow_remember=payload.get("allow_remember"),
            questions=(
                normalize_questions(questions) if questions is not None else None
            ),
        ))]
    if isinstance(event, ev.InteractionResolvedEvent):
        return [_dump(ws.WsInteractionResolved(
            type="interaction.resolved", turn_id=event.turn_id,
            interaction_id=event.interaction_id, execution_id=event.call_id,
            kind=_INTERACTION_KIND.get(event.kind, event.kind),
            outcome=event.outcome,
        ))]
    if isinstance(event, ev.ContextUsageEvent):
        window = event.context_window or 1
        return [_dump(ws.WsContextUsage(
            type="context.usage", turn_id=event.turn_id, used=event.tokens,
            available=max(window - event.tokens, 0),
            context_window=event.context_window,
            percentage=round(event.tokens / window, 4),
            is_estimated=True,
        ))]
    if isinstance(event, ev.CompactionEvent):
        return [_dump(ws.WsContextCompaction(
            type="context.compaction", turn_id=event.turn_id,
            phase=event.phase, tokens_before=event.tokens_before,
            tokens_after=event.tokens_after, error=event.error,
        ))]
    if isinstance(event, ev.TurnWarningEvent):
        return [_dump(ws.WsTurnWarning(
            type="turn.warning", turn_id=event.turn_id, code=event.code,
            message=event.message,
        ))]
    if isinstance(event, ev.TurnErrorEvent):
        return [_dump(ws.WsTurnError(
            type="turn.error", turn_id=event.turn_id, code=event.code,
            message=event.message,
        ))]
    if isinstance(event, ev.TurnUsageEvent):
        return [_dump(ws.WsTurnUsage(
            type="turn.usage", turn_id=event.turn_id, step=event.step,
            input_tokens=event.input_tokens, output_tokens=event.output_tokens,
            cost=event.cost, tool_calls=event.tool_calls,
            max_steps=event.max_steps,
        ))]
    if isinstance(event, ev.TurnFinishedEvent):
        return [_dump(ws.WsTurnFinished(
            type="turn.finished", turn_id=event.turn_id,
            finish_reason=event.finish_reason,
            conversation_id=event.conversation_id,
            message_id=event.final_message_id or "",
            user_message_id=event.user_message_id,
            version_group_id=event.version_group_id,
            version_index=event.version_index,
            steps=event.steps, tool_calls=event.tool_calls,
            input_tokens=event.input_tokens, output_tokens=event.output_tokens,
            cost=event.cost,
        ))]
    if isinstance(event, ev.RawToolCallDeltaEvent):
        # Diagnostico Mossa 1: non ha un frame v2 (muore nel task 10).
        return []
    return []
```

NOTA `WsInteractionRequested`: `execution_id`/`tool_name`... il campo `args` con valore
`{}` (dict vuoto) NON è None → resta nel frame: va bene. `success` su `tool.result` resta
fino alla purga (task 10 lo toglie da modello e wire.py).

- [ ] **Step 4: switch del translator**

`runner.py`: `from backend.services.agent.adapters.wire import to_v2_frames` e sostituire i
due usi di `to_wire_frames`. Eliminare `parity.py` e `test_parity.py`
(`git rm`). Aggiornare `test_runner_integration.py` (asserzioni per tipo: ancora
`turn.llm_step`/`turn.finished` → invariate) e `test_ws_chat_live.py`: dal motore ora
arrivano SOLO frame v2 (`turn.delta` al posto di `token`, niente `llm_requery`, niente
`tool_execution_*`), ma `done`/`context_info`/compression legacy arrivano ancora dal
persist path (fino al task 9). Aggiornare le asserzioni di sequenza di conseguenza
(`turn.finished` < `done` resta).

- [ ] **Step 5: run + commit**

`pytest tests/agent/ tests/evals/ tests/contracts/ -q` → verdi (evals mock: `trace.py` legge
`turn.llm_step`/`tool.call`/`turn.usage`, tutti invariati).

```bash
git rm backend/services/agent/adapters/parity.py backend/tests/agent/test_parity.py
git commit -am "feat(engine): adapter wire v2 definitivo (frame Pydantic by-construction); parity adapter eliminato"
```

---

### Task 8: Correlazione `interaction.response` nel trasporto + `WsInteractionPort` v2

Il giro interattivo passa al vocabolario v2: il frame di richiesta È l'evento
`interaction.requested` (emesso dal motore via EventPort); la porta attende la risposta
correlata per `interaction_id`; il bridge `correlation_id`/`alt_key` muore.

**Files:**
- Modify: `backend/services/agent/adapters/ws.py` (transport + WsInteractionPort riscritti)
- Test: `backend/tests/agent/test_adapter_ws.py`, `backend/tests/agent/test_ws_chat_live.py`

- [ ] **Step 1: test rosso (unit transport)**

In `test_adapter_ws.py`:

```python
async def test_wait_response_resolves_by_interaction_id(...) -> None:
    # register sincrono: chiamare wait_response, POI iniettare nel pump un frame
    # {"type": "interaction.response", "interaction_id": "i1", "approved": True}
    # → il future risolve col frame.
async def test_interaction_response_stale_is_dropped(...) -> None:
    # response con interaction_id sconosciuto → scartata con log, NON in coda utente.
async def test_wait_response_precedence_disconnect_over_cancel(...) -> None:
    # invariata dalla request() legacy: disconnect > cancel > timeout.
async def test_confirm_tool_builds_no_frame(...) -> None:
    # WsInteractionPort.confirm_tool NON invia frame outbound (il frame è
    # l'evento del motore): il transport double non registra send.
async def test_confirm_tool_maps_response(...) -> None:
    # approved True/False → APPROVED/REJECTED; None+cancel → CANCELLED;
    # None → TIMEOUT; EngineDisconnected → DISCONNECTED (dato).
async def test_ask_user_and_client_parse_v2_response(...) -> None:
    # answers → testo formattato; success/result/error → ToolExecutionOutput.
```

- [ ] **Step 2: implementare il transport**

In `ws.py` (adapter): sostituire `request()` con `wait_response()`; `_pending` ora è
keyed by `interaction_id`; `_alt_keys` e `_forget_alt_key` ELIMINATI.

```python
    async def wait_response(
        self,
        interaction_id: str,
        *,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> dict[str, Any] | None:
        """Attende il frame ``interaction.response`` correlato a ``interaction_id``.

        Il frame di RICHIESTA è già sul wire (l'evento ``interaction.requested``
        del motore, emesso via EventPort PRIMA di chiamare la porta): qui si
        registra il waiter e si attende. La registrazione è SINCRONA (prima di
        qualunque await): unita all'invariante del motore "nessun await tra
        l'emit del requested e la chiamata alla porta", garantisce che una
        risposta non possa arrivare al pump prima che il waiter esista.

        Precedenza: disconnect > cancel > timeout (invariata).
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any] | None] = loop.create_future()
        self._pending[interaction_id] = future
        if not self._connected:
            # Registrato a socket già caduto: esito disconnect immediato.
            self._pending.pop(interaction_id, None)
            raise EngineDisconnected("client WS disconnesso")
        disconnect_waiter = asyncio.create_task(self._disconnected_event.wait())
        cancel_waiter = asyncio.create_task(cancel.wait())
        try:
            waiters: set[asyncio.Future[Any]] = {future, disconnect_waiter, cancel_waiter}
            await asyncio.wait(
                waiters, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED,
            )
            if future.done():
                return future.result()
            if disconnect_waiter.done():
                raise EngineDisconnected(
                    f"client WS caduto in attesa di interaction.response "
                    f"({interaction_id})"
                )
            if not cancel_waiter.done():
                logger.debug(
                    "WsTransport: interaction {} scaduta dopo {}s",
                    interaction_id, timeout_s,
                )
            return None
        finally:
            self._pending.pop(interaction_id, None)
            if not future.done():
                future.cancel()
            disconnect_waiter.cancel()
            cancel_waiter.cancel()
```

`_dispatch` diventa:

```python
    def _dispatch(self, frame: dict[str, Any]) -> None:
        """Smista un frame inbound: cancel, interaction.response, o messaggio utente."""
        if frame.get("type") == "cancel":
            self._cancel.set()
            self._resolve_all_pending_to_none()
            return
        if frame.get("type") == "interaction.response":
            interaction_id = frame.get("interaction_id")
            future = self._pending.pop(str(interaction_id), None)
            if future is None:
                logger.warning(
                    "WsTransport: interaction.response stale scartata "
                    "(interaction_id={})", interaction_id,
                )
                return
            if not future.done():
                future.set_result(frame)
            return
        self._user_messages.put_nowait(frame)
```

(`_resolve_all_pending_to_none` e `_mark_disconnected`: rimuovere i riferimenti a
`_alt_keys`.)

- [ ] **Step 3: riscrivere `WsInteractionPort`**

```python
class WsInteractionPort:
    """``InteractionPort`` sul trasporto WS, vocabolario v2.

    NON costruisce frame outbound: il frame di richiesta è l'evento
    ``interaction.requested`` emesso dal MOTORE (un evento = un fatto del
    turno). Qui solo l'attesa correlata per ``interaction_id`` e la
    decodifica della ``interaction.response``.
    """

    def __init__(self, transport: WsTransport) -> None:
        self._transport = transport

    async def confirm_tool(
        self, call: ToolInvocation, *, interaction_id: str, verdict: GateVerdict,
        timeout_s: float, cancel: asyncio.Event,
    ) -> InteractionOutcome:
        """Attende l'esito della conferma; DISCONNECTED come DATO (adjudicazione T4)."""
        try:
            response = await self._transport.wait_response(
                interaction_id, timeout_s=timeout_s, cancel=cancel,
            )
        except EngineDisconnected:
            return InteractionOutcome.DISCONNECTED
        if response is None:
            if cancel.is_set():
                return InteractionOutcome.CANCELLED
            return InteractionOutcome.TIMEOUT
        if bool(response.get("approved")):
            return InteractionOutcome.APPROVED
        return InteractionOutcome.REJECTED

    async def run_client_tool(
        self, call: ToolInvocation, *, interaction_id: str, timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput:
        """Raises: EngineDisconnected se il client cade prima del risultato."""
        response = await self._transport.wait_response(
            interaction_id, timeout_s=timeout_s, cancel=cancel,
        )
        if response is None:
            return self._interrupted_output(call, cancel)
        success = bool(response.get("success", False))
        raw_result = response.get("result")
        if isinstance(raw_result, str):
            content = raw_result
        elif raw_result is None:
            content = ""
        else:
            content = json.dumps(raw_result, ensure_ascii=False)
        error = response.get("error")
        if success:
            return ToolExecutionOutput(ok=True, content=content)
        return ToolExecutionOutput(
            ok=False, content=content,
            error=str(error) if error else "esecuzione client fallita",
        )

    async def ask_user(
        self, call: ToolInvocation, *, interaction_id: str, timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput:
        """Raises: EngineDisconnected se il client cade prima delle risposte."""
        response = await self._transport.wait_response(
            interaction_id, timeout_s=timeout_s, cancel=cancel,
        )
        if response is None:
            return self._interrupted_output(call, cancel)
        answers = response.get("answers")
        return ToolExecutionOutput(
            ok=True,
            content=_format_answers(answers if isinstance(answers, list) else []),
        )

    # _interrupted_output invariato (statico, già presente)
```

`_normalize_questions` esce da `ws.py` (vive in `wire.py` dal task 7 — rimuovere qui la
copia e i suoi usi; `_format_answers` resta in `ws.py`). Aggiornare il docstring di modulo
di `ws.py` (via il paragrafo sul correlation bridge/alt_key e sui frame legacy).

- [ ] **Step 4: run + commit**

`pytest tests/agent/ -q` → verdi.

```bash
git commit -am "feat(ws): round-trip interattivo su interaction.requested/response correlato per interaction_id; bridge correlation/alt_key eliminato"
```

---

### Task 9: Route/persist/assembly su frame v2 tipizzati; UNICO stream (carry #3, parte 2)

I frame residui dell'api layer (`done`→morto, `context_info`→`context.usage`,
compression→`context.compaction`, `error`→`turn.error`) diventano modelli tipizzati emessi
ATTRAVERSO lo stesso trasporto del motore. `turn.finished` (motore) è ora il frame finale
del turno.

**Files:**
- Modify: `backend/api/routes/chat/_sink.py` (nuovo `TransportEventSink`)
- Modify: `backend/api/routes/chat/ws.py` (error frames tipizzati, sink sul transport)
- Modify: `backend/api/routes/chat/_persist.py` (niente done; frame v2 tipizzati)
- Modify: `backend/api/routes/chat/_assembly.py` (frame v2 tipizzati)
- Modify: `backend/api/routes/chat/headless.py` (nessun cambio atteso — verificare)
- Test: `backend/tests/agent/test_ws_chat_live.py` (sequenza v2 finale)

- [ ] **Step 1: test rosso — sequenza v2 finale nel live test**

Aggiornare `test_ws_chat_live.py`: il turno testo chiude con `turn.finished` (nessun
`done`); frame attesi: `turn.started` → `context.usage` (assembly, pre-turno, turn_id
assente) → `turn.llm_step` → `turn.delta` → `turn.usage` → `turn.finished` (con
`conversation_id`/`message_id`/`user_message_id` valorizzati) → eventuale `context.usage`
post-turno. `_drain_until(ws, "turn.finished")`… ATTENZIONE: il `context.usage` reale
post-turno arriva DOPO `turn.finished` — drenare fino a `turn.finished` e asserire su quel
prefisso. Turno tool: `tool.call`/`tool.result` v2 con `status`. Errore di validazione:
inviare `{"content": ""}` → frame `turn.error` con `code`.

- [ ] **Step 2: `TransportEventSink`**

In `_sink.py`:

```python
class TransportEventSink:
    """Sink del persist path sopra il ``WsTransport`` del motore.

    Collasso dell'ownership (carry #3): l'api layer scrive gli ultimi frame di
    manutenzione conversazione (context.*) attraverso lo STESSO trasporto del
    motore — un solo writer per il canale chat. Il costruttore accetta
    qualunque oggetto con ``send_json``/``connected`` (strutturale, niente
    import dal package agent).
    """

    def __init__(self, transport: Any, frame_validator: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._transport = transport
        self._validate = frame_validator

    async def send(self, event: dict[str, Any]) -> None:
        if self._validate is not None:
            self._validate(event)
        await self._transport.send_json(event)

    @property
    def is_connected(self) -> bool:
        return bool(self._transport.connected)
```

`WebSocketEventSink` resta per ora (lo si valuta nel task 10: se orfano, muore).

- [ ] **Step 3: `ws.py` (route)**

- `sink = TransportEventSink(transport, frame_validator=chat_frame_validator)` al posto di
  `WebSocketEventSink(websocket, ...)`.
- I quattro error frame inline diventano tipizzati (turn_id assente):

```python
from backend.api.ws_schema.chat import WsTurnError


def _error_frame(code: str, message: str) -> dict[str, Any]:
    """Frame turn.error pre-turno (validato by-construction)."""
    return WsTurnError(
        type="turn.error", code=code, message=message,
    ).model_dump(mode="json", exclude_none=True)
```

e i quattro send diventano: `_error_frame("server_not_ready", "Server not ready —
services not initialized")`, `_error_frame("empty_message", "Empty message")`,
`_error_frame("message_too_long", "Message too long")`,
`_error_frame("llm_unavailable", "LLM service unavailable")`. L'helper vive in `ws.py`
(o in `_shared.py` se serve anche a `_assembly.py` — decisione dell'implementer, una
sola copia).

- [ ] **Step 4: `_persist.py`**

- `_build_done_event` ELIMINATA; tutte le `sink.send(done)` rimosse (il frame finale è il
  `turn.finished` del motore). Il ramo error del `try` di persistenza conv-metadata emette
  `WsTurnError(code="save_failed", message="Failed to save response")` (dump tipizzato) e
  basta.
- `context_info` reale (v2-6) → `WsContextUsage` tipizzato:

```python
            await sink.send(ws_chat.WsContextUsage(
                type="context.usage",
                used=real_usage.used_tokens,
                available=real_usage.available_tokens,
                context_window=context_window,
                percentage=real_usage.percentage,   # verificare che sia frazione [0,1]
                was_compressed=was_compressed,
                messages_summarized=(
                    pre_comp.usage.messages_summarized if pre_comp else 0
                ),
                is_estimated=False,
                breakdown=ws_chat.WsContextBreakdown(**_compute_context_breakdown(
                    messages, tool_tokens, ctx.context_manager,
                )),
            ).model_dump(mode="json", exclude_none=True))
```

  (VERIFICA implementer: `ContextUsage.percentage` di `get_usage_real` — se è percentuale
  0-100 va normalizzata a frazione; il contratto v2 è frazione [0,1].)
- Post-stream compression: `context_compression_start` → `WsContextCompaction(phase=
  "started")`; `..._done` → `phase="done"` con `messages_summarized` +
  `summary_message_id`; `..._failed` → `phase="failed"`; il `context_info` finale →
  `WsContextUsage` come sopra con `is_estimated=True, was_compressed=True`.
- La rimozione della creazione del messaggio è già avvenuta al task 5 — qui muore solo il
  frame `done` e la sua builder.

- [ ] **Step 5: `_assembly.py`**

- Error frames di validazione (`Invalid conversation_id`, `Invalid edit_message_id`,
  `Invalid edit target`) → `WsTurnError` tipizzato (`code="invalid_conversation_id"`,
  `"invalid_edit_message_id"`, `"invalid_edit_target"`).
- `context_compression_start/done/failed` pre-gen → `WsContextCompaction` tipizzato
  (`phase="started"/"done"/"failed"`, done con `messages_summarized` +
  `summary_message_id`).
- `context_info` iniziale → `WsContextUsage` tipizzato (`is_estimated=usage_est.
  is_estimated`, breakdown incluso).

- [ ] **Step 6: run + commit**

`pytest tests/agent/ tests/evals/ tests/contracts/ -q` → verdi.

```bash
git commit -am "feat(chat): persist/assembly emettono frame v2 tipizzati sullo stream unico; done eliminato (carry #3)"
```

---

### Task 10: Purga del legacy dal contratto + eventi/porte morti

Il canale chat parla SOLO v2. Escono i modelli legacy, gli opzionali v2 si irrigidiscono,
muoiono i residui diagnostici del motore.

**Files:**
- Modify: `backend/api/ws_schema/chat.py` (purga + irrigidimento)
- Modify: `backend/services/agent/events.py` (via `RawToolCallDeltaEvent`)
- Modify: `backend/services/agent/ports.py` (via `LLMToolCallDelta`)
- Modify: `backend/services/agent/adapters/llm.py` (non emette più i chunk raw)
- Modify: `backend/services/agent/engine.py` (via il ramo `LLMToolCallDelta`)
- Modify: `backend/services/agent/adapters/wire.py` (via i rami morti; via `success` da
  tool.result)
- Modify: `backend/api/routes/chat/_sink.py` (eliminare `WebSocketEventSink` se orfano —
  grep prima; `NullEventSink`/`WSEventSink` restano per headless/eval)
- Modify: `backend/tests/contracts/test_ws_schema_chat.py` (vocabolario finale)
- Modify: `backend/api/ws_schema/chat.py` docstring + `backend/api/ws_schema/guard.py`
  docstring (la garanzia è by-construction in `wire.py`)
- Test: tutti i mirati

- [ ] **Step 1: test rosso (vocabolario finale)**

`EXPECTED_CHAT_SERVER_TYPES` finale = i 15 tipi della tabella "Vocabolario v2 finale";
`EXPECTED_CHAT_CLIENT_TYPES` = {"cancel", "interaction.response"}. Representative frames:
solo v2, aggiornati alle shape irrigidite. Run → FAIL.

- [ ] **Step 2: purga**

In `chat.py` rimuovere: `WsToken`, `WsThinking`, `WsToolCallStream`, `WsToolCallFunction`,
`WsError`, `WsDone`, `WsToolExecutionStart`, `WsToolExecutionDone`, `WsToolProgressLegacy`,
`WsContextInfo`, `WsContextCompressionStart/Done/Failed`, `WsLlmRequery`, `WsWarning`,
`WsToolConfirmationRequired`, `WsClientToolCall`, `WsAskUserRequired`,
`WsAgentCriticInvoked`, `WsAgentWarning`, `WsToolConfirmationResponse`,
`WsClientToolResult`, `WsAskUserResponse` (le classi `WsAskUserQuestion`/`WsAskUserAnswer`
RESTANO: le usano `interaction.requested`/`interaction.response`). Irrigidire:

- `WsTurnStarted.source: Literal["chat", "voice", "headless"]` (required)
- `WsTurnToolCall.step: int` (required)
- `WsTurnToolResult`: `status: str` required; RIMUOVERE `success` (derivato da status)
- `WsInteractionRequested.interaction_id: str` (required)
- `WsInteractionResolved.interaction_id: str` (required)
- `WsTurnUsage.cost: float` (required)
- `WsTurnFinished`: `finish_reason: str`, `conversation_id: str`, `message_id: str`,
  `version_index: int`, `tool_calls: int` required; `user_message_id: str | None` RESTA
  opzionale (turni motore costruiti senza request completa lo emettono assente — il FE non
  lo consuma), come `version_group_id: str | None` e `cost: float | None`

Aggiornare `wire.py` (via `success=...` da tool.result; via il ramo
`RawToolCallDeltaEvent`). In `events.py` rimuovere `RawToolCallDeltaEvent` dalla union e
dal modulo; in `ports.py` rimuovere `LLMToolCallDelta` dalla union `LLMEvent`; in
`adapters/llm.py` rimuovere l'emissione dei chunk raw; in `engine.py` rimuovere il ramo
`LLMToolCallDelta` da `_run_llm_step`. Riscrivere il docstring di modulo di `chat.py`
(produttori: `wire.py` + `_persist`/`_assembly` tipizzati). Aggiornare la docstring di
`guard.py`. Grep `WebSocketEventSink` — se l'unico uso era `ws.py` (sostituito al task 9),
eliminarla insieme a `is_websocket_closed_runtime_error` se orfana.

- [ ] **Step 3: run + commit**

`pytest tests/agent/ tests/evals/ tests/contracts/ -q` → verdi.
`ruff check .` (da `backend/`) → 0.

```bash
git commit -am "feat(contracts)!: canale chat solo vocabolario v2 — frame legacy e diagnostici eliminati"
```

---

### Task 11: Codegen + migrazione frontend (spec §5)

Contratti rigenerati; `agentRun` unica fonte di verità del fold del turno (tool,
interazioni, progress); `chat.ts` tiene solo lo stato messaggi/streaming/context bar;
`ChatHandlerMap` esaustiva sul vocabolario v2; dialoghi su `interaction.requested`;
risposte su `interaction.response`.

**Files:**
- Regenerate: `frontend/src/renderer/src/types/generated/*` (SOLO via script)
- Modify: `frontend/src/renderer/src/types/turn.ts`, `types/chat.ts`
- Modify: `frontend/src/renderer/src/stores/agentRun.ts` (+ `agentRun.spec.ts`)
- Modify: `frontend/src/renderer/src/stores/chat.ts` (+ `chat.spec.ts`,
  `chat-cost.spec.ts`)
- Modify: `frontend/src/renderer/src/composables/useChat.ts`
- Modify: componenti consumatori (censiti sotto)

- [ ] **Step 1: rigenerare i contratti**

Da repo root (PowerShell): `.\scripts\gen-contracts.ps1` → rigenera
`openapi.json`/`api.d.ts`. MAI editare a mano i generati (eccetto `index.ts`).
`npm run typecheck` da `frontend/` ora FALLISCE (atteso): è la to-do list della migrazione.

- [ ] **Step 2: tipi**

`types/turn.ts` — sostituire il blocco alias generati:

```ts
export type WsTurnStartedMessage = ApiSchema<'WsTurnStarted'>
export type WsTurnDeltaMessage = ApiSchema<'WsTurnDelta'>
export type WsTurnLlmStepMessage = ApiSchema<'WsTurnLlmStep'>
export type WsToolCallMessage = ApiSchema<'WsTurnToolCall'>
export type WsToolStartedMessage = ApiSchema<'WsToolStarted'>
export type WsToolProgressMessage = ApiSchema<'WsToolProgress'>
export type WsToolResultMessage = ApiSchema<'WsTurnToolResult'>
export type WsInteractionRequestedMessage = ApiSchema<'WsInteractionRequested'>
export type WsInteractionResolvedMessage = ApiSchema<'WsInteractionResolved'>
export type WsContextUsageMessage = ApiSchema<'WsContextUsage'>
export type WsContextCompactionMessage = ApiSchema<'WsContextCompaction'>
export type WsTurnWarningMessage = ApiSchema<'WsTurnWarning'>
export type WsTurnErrorMessage = ApiSchema<'WsTurnError'>
export type WsTurnUsageMessage = ApiSchema<'WsTurnUsage'>
export type WsTurnFinishedMessage = ApiSchema<'WsTurnFinished'>
```

`types/chat.ts` — aggiornare gli alias WS: rimuovere `WsToolCallMessage` (legacy stream),
`WsToolConfirmationResponsePayload`, `WsAskUserResponsePayload`; aggiungere
`export type WsInteractionResponsePayload = ApiSchema<'WsInteractionResponse'>`;
`RememberChoice = NonNullable<ApiSchema<'WsInteractionResponse'>['remember']>`;
`AskUserQuestion`/`AskUserAnswer`/`ContextBreakdown` restano (i modelli sopravvivono).
`ConfirmationRequest`/`AskUserRequest` view-model: la chiave diventa `interactionId`
(rinominare `executionId` → tenere ANCHE `executionId` per correlare il tool chip).

- [ ] **Step 3: store `agentRun` (fold completo)**

`ToolActivity` guadagna `progress?: Record<string, unknown>`; `InteractionActivity`
guadagna `interactionId: string`, `args?: Record<string, unknown>`, `riskLevel?: string`,
`description?: string`, `reasoning?: string`, `allowRemember?: boolean`,
`questions?: AskUserQuestion[]` (import type da `./chat`). Azioni nuove/aggiornate:

```ts
/** `turn.delta` → nessun fold qui (testo in chat store); presente per esaustività. */
/** `tool.started` → marca running l'attività (idempotente, create-if-absent). */
function applyToolStarted(msg: WsToolStartedMessage): void { ... }
/** `tool.progress` → aggiorna la snapshot progress dell'attività. */
function applyToolProgress(msg: WsToolProgressMessage): void {
  const run = ensureRun(msg.turn_id)
  const idx = run.tools.findIndex((t) => t.executionId === msg.execution_id)
  if (idx === -1) return
  const updated: ToolActivity = { ...run.tools[idx], progress: msg.progress }
  run.tools = [...run.tools.slice(0, idx), updated, ...run.tools.slice(idx + 1)]
}
```

`applyToolResult`: `status` al posto di `success` → `const status = msg.status === 'ok' ?
'success' : 'error'`; conserva `result`/`content_type`/`artifact_id` come oggi.
`applyInteractionRequested`: chiave `msg.interaction_id`, popola i campi payload.
`applyInteractionResolved`: chiave `msg.interaction_id`.
`applyTurnFinished`: aggiunge `run.toolCalls = msg.tool_calls`.
Getter nuovi (per i componenti dialogo — stessa shape dei vecchi view-model chat-store):

```ts
/** Conferme tool pendenti del run corrente (fold canonico, spec §5). */
const pendingConfirmations = computed<InteractionActivity[]>(() => {
  const run = currentRun.value
  if (!run) return []
  return run.interactions.filter(
    (i) => i.status === 'pending' && i.kind === 'tool_confirmation'
  )
})
/** Richieste ask_user pendenti del run corrente. */
const pendingAskUser = computed<InteractionActivity[]>(() => { /* idem kind==='ask_user' */ })
```

Aggiornare `agentRun.spec.ts` (frame v2 nei fixture; test nuovi per
started/progress/requested arricchito/resolved per interaction_id).

- [ ] **Step 4: store `chat` (dimagrimento)**

Rimuovere da `chat.ts`: `toolExecutions`, `pendingConfirmations`, `pendingAskUser` e le
azioni `addToolExecution`/`completeToolExecution`/`updateToolExecutionProgress`/
`addPendingConfirmation`/`removePendingConfirmation`/`addPendingAskUser`/
`removePendingAskUser` (grep dei consumer PRIMA di rimuovere — vedi Step 6). Restano:
streaming text/thinking, `contextInfo`, compressione, costi, versioning, conversazioni.
`finalizeStream` invariata. Aggiornare `chat.spec.ts`/`chat-cost.spec.ts`.

- [ ] **Step 5: `useChat.ts` — ChatHandlerMap v2**

```ts
  const handlers: ChatHandlerMap = {
    'turn.started': (msg) => agentRunStore.applyTurnStarted(msg),

    'turn.delta': (msg) => {
      if (store.streamGeneration !== activeGeneration) return
      if (msg.kind === 'text') store.appendToStream(msg.text)
      else store.appendToThinking(msg.text)
    },

    'turn.llm_step': (msg) => {
      agentRunStore.applyLlmStep(msg)
      if (store.streamGeneration !== activeGeneration) return
      if (msg.step > 1) {
        // Nuovo step LLM: reset del buffer testo (il precedente è persistito
        // server-side); il thinking si accumula con separatore (spec §4).
        store.currentStreamContent = ''
        if (store.currentThinkingContent) {
          store.currentThinkingContent += '\n\n---\n\n'
        }
      }
    },

    'tool.call': (msg) => agentRunStore.applyToolCall(msg),
    'tool.started': (msg) => agentRunStore.applyToolStarted(msg),
    'tool.progress': (msg) => agentRunStore.applyToolProgress(msg),
    'tool.result': (msg) => agentRunStore.applyToolResult(msg),

    'interaction.requested': (msg) => {
      agentRunStore.applyInteractionRequested(msg)
      if (msg.kind === 'tool_confirmation') {
        // Auto-approve: tool safe o conferme disattivate (parità col legacy).
        if (msg.risk_level === 'safe' || !settingsStore.toolConfirmations) {
          respondToConfirmation(msg.interaction_id, true)
        }
      }
      // kind 'client_tool_call': nessun executor renderer (dormiente, come prima).
    },
    'interaction.resolved': (msg) => agentRunStore.applyInteractionResolved(msg),

    'context.usage': (msg) => {
      if (store.streamingConversationId !== store.currentConversation?.id) return
      store.updateContextInfo({
        used: msg.used,
        available: msg.available,
        contextWindow: msg.context_window,
        percentage: msg.percentage,
        wasCompressed: msg.was_compressed ?? false,
        messagesSummarized: msg.messages_summarized ?? 0,
        isEstimated: msg.is_estimated ?? true,
        breakdown: msg.breakdown ?? undefined
      })
    },
    'context.compaction': (msg) => {
      if (store.streamingConversationId !== store.currentConversation?.id) return
      if (msg.phase === 'started') store.setCompressingContext(true)
      else if (msg.phase === 'done') store.setCompressionDone(msg.messages_summarized ?? 0)
      else store.setCompressingContext(false)
    },

    'turn.usage': (msg) => agentRunStore.applyTurnUsage(msg),
    'turn.warning': (msg) => console.warn('[useChat] Turn warning:', msg.code, msg.message),
    'turn.error': (msg) => console.error('[useChat] Turn error:', msg.code, msg.message),

    'turn.finished': (msg) => {
      agentRunStore.applyTurnFinished(msg)
      if (store.streamGeneration !== activeGeneration) return
      store.finalizeStream(
        msg.conversation_id,
        msg.message_id,
        msg.version_group_id,
        msg.version_index
      )
      store.addTurnCost(msg.cost ?? null)
    }
  }
```

NOTE: il gate `streamGeneration` su `context.usage`/`context.compaction` CADE (il frame
post-turno arriva dopo `finalizeStream`, che avanza la generation — gate solo sulla
conversazione). `respondToConfirmation`/`answerAskUser` diventano:

```ts
  function respondToConfirmation(
    interactionId: string,
    approved: boolean,
    remember: RememberChoice = 'none'
  ): void {
    const payload: WsInteractionResponsePayload = {
      type: 'interaction.response',
      interaction_id: interactionId,
      kind: 'tool_confirmation',
      approved
    }
    if (remember !== 'none') payload.remember = remember
    wsManager.send(payload)
    // lo stato pending si risolve col frame interaction.resolved del server
  }

  function answerAskUser(interactionId: string, answers: AskUserAnswer[]): void {
    wsManager.send({
      type: 'interaction.response',
      interaction_id: interactionId,
      kind: 'ask_user',
      answers
    } satisfies WsInteractionResponsePayload)
  }
```

(la firma pubblica `UseChatReturn` cambia: primo parametro `interactionId` — aggiornare i
call site nei componenti dialogo.)

- [ ] **Step 6: componenti**

`npm run typecheck` guida la lista. Censimento noto dei consumer dello stato
tool/conferme del chat store (verificare con grep `toolExecutions|pendingConfirmations|
pendingAskUser`): `views/HorizonView.vue`, `components/horizon/HorizonCockpit.vue`,
`components/chat/ChatInput.vue`, `components/chat/StreamingIndicator.vue`,
`components/workspace/ChatPanel.vue`, `components/workspace/modules/ActivityModule.vue`,
`components/chat/ReasoningThread.vue`, `components/chat/CADGenerationPlaceholder.vue`.
Migrazione: sorgente dati → `useAgentRunStore()` (`currentRun.tools`,
`pendingConfirmations`, `pendingAskUser` getter). Le shape sono state tenute compatibili
(executionId/toolName/args/riskLevel/description/reasoning/allowRemember/questions;
progress su `ToolActivity.progress`), quindi la migrazione è quasi solo un cambio di
sorgente + rename campi camelCase dove differiscono. I dialoghi passano
`interactionId` alle nuove firme di `respondToConfirmation`/`answerAskUser`.

Nuance da CENSIRE nel ledger: nel fold v2 anche una conferma auto-approvata compare per un
istante come interaction `pending` (finché arriva `interaction.resolved` dal server). Se in
smoke il dialogo "flasha", il gate va nel componente (non renderizzare conferme quando
`risk_level === 'safe'` o `!settingsStore.toolConfirmations` — stesso predicato
dell'auto-approve), MAI omettendo il fold.

- [ ] **Step 7: verifiche FE**

Da `frontend/`: `npm run typecheck` → 0 errori; `npm run lint` → pulito;
`npx vitest run` → verdi. Poi da `backend/`: `pytest tests/contracts/ -q` e da repo root
`.\scripts\check-contracts.ps1` → verde (artifacts committati freschi).

- [ ] **Step 8: smoke manuale (facoltativo ma raccomandato dalla spec §11)**

Se l'ambiente lo consente: `.\scripts\start-dev.ps1`, un turno con tool + una conferma su
Horizon. In caso contrario annotare nel ledger che lo smoke è rinviato all'utente.

- [ ] **Step 9: commit**

```bash
git add frontend/src/renderer/src backend/api scripts
git commit -m "feat(frontend)!: migrazione al vocabolario chat v2 — agentRun unica fonte del fold, interaction.response, tipi rigenerati"
```

---

### Task 12: Flag `agent.engine` rimosso, contratto lint ritirato, docs, gate completi, eval finale, baseline, handoff

- [ ] **Step 1: rimozione flag e contratto lint**

- `backend/core/config.py`: rimuovere il campo `engine` da `AgentConfig` (e la sua
  docstring). Grep `agent.engine|ALICE_AGENT__ENGINE|config.agent.engine` in backend/docs:
  aggiornare `test_runner_integration.py` (via il monkeypatch env e l'assert — la fixture
  `v2_app` si rinomina `app` senza env), `config/default.yaml` se presente la chiave,
  `docs/flag-registry.md` (voce `agent.engine` RIMOSSA, con nota).
- `backend/pyproject.toml`: rimuovere il contratto import-linter `agent ↛ turn` (il
  target `services/turn` non esiste più; spec §9 "il contratto si ritira"). Da repo root:
  `lint-imports --config backend/pyproject.toml` → contratti restanti KEPT.

- [ ] **Step 2: docs**

- `CLAUDE.md` (sezione "Tools & the AgentEngine"): parity.py eliminato, wire v2 unico
  vocabolario, `_sink.py` ridotto, flag rimosso, interaction.response, persistenza finale
  nel motore.
- `backend/api/ws_schema/guard.py` + `chat.py` docstring già aggiornate (task 10) —
  verificare coerenza finale.
- `docs/flag-registry.md`: census di eventuali chiavi toccate.

- [ ] **Step 3: gate completi (spec §9)**

Da `backend/` (venv ROOT, foreground): `pytest tests/agent/ tests/evals/ tests/contracts/
-q` → tutti verdi; `ruff check .` → 0; `mypy` a parità sui file toccati (confronto col
baseline di branch: nessun errore NUOVO). Da repo root: `lint-imports --config
backend/pyproject.toml` → KEPT; `.\scripts\check-contracts.ps1` → verde. Da `frontend/`:
`npm run typecheck && npm run lint` e `npx vitest run` → verdi.

- [ ] **Step 4: EVAL FINALE — STOP: serve l'OK esplicito dell'utente (costa denaro)**

NON eseguire senza OK. Con l'OK: da repo root (venv ROOT):

```powershell
python -m backend.evals run --baseline docs/superpowers/evals/2026-07-17-baseline-fase0/report.json
```

Gate: **23/23 scenari, zero regressioni vs baseline Fase 0**. In caso di regressione:
systematic-debugging, fix, e NUOVO OK per il re-run.

- [ ] **Step 5: baseline di fase + handoff**

- Copiare il report del run verde in `docs/superpowers/evals/<YYYYMMDD-HHMMSS>-baseline-fase1/`
  e committarlo (è la baseline di Fase 1 per le fasi successive).
- Scrivere `docs/superpowers/handoffs/<data>-agent-engine-fase1-mossa2-handoff.md`: esiti,
  debito censito residuo (es. outcome "failed" indistinto su timeout/cancel client,
  divergenza token_count, smoke manuale se rinviato), gate verificati, prossimo passo del
  programma (Fase 2).
- Ledger `.superpowers/sdd/progress.md` chiuso con l'esito di ogni task.

- [ ] **Step 6: commit finale**

```bash
git add -A
git commit -m "chore(fase1): flag agent.engine rimosso, contratto agent↛turn ritirato, baseline eval Fase 1, handoff Mossa 2"
```

La fase chiude qui; il merge di `feat/agent-engine-fase1` in `main` avviene SOLO dopo
questo task, su decisione dell'utente (skill `finishing-a-development-branch`).

---

## Note per l'orchestrazione subagent (metodo Fase 1)

- Un implementer per task + spec review + quality review; fixer sui finding; nessun task
  chiuso con Critical/Major aperti. Review package con BASE = commit pre-implementer (mai
  `HEAD~1`).
- Modelli: implementer economico su task 1–3, 6 (meccanici, codice completo nel piano);
  medio su 2, 9, 11 (adapter/integrazione/FE); top su 5, 7, 8 (motore/concorrenza) e sulla
  review olistica finale. SEMPRE specificare il modello nel dispatch.
- In OGNI dispatch: il blocco "Gotcha macchina" (venv ROOT, pytest foreground, no suite
  integrale, cp1252) + il PRINCIPIO PILASTRO + il divieto di leggere codice legacy (non
  esiste più nel tree, ma vale per wording/consultazione storica via git).
- Dopo il task 10 il backend parla SOLO v2 e il FE è rotto fino a fine task 11: NON
  eseguire smoke FE tra 10 e 11; i task 10→11 vanno eseguiti back-to-back.
