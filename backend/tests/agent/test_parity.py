"""Parity adapter + harness v1-vs-v2 sul wire attuale.

Parte A (unit translator): ogni ``AgentEvent`` produce frame che validano il
contratto chat attuale (``validate_chat_server``).

Parte B (harness end-to-end): scenari scriptati eseguiti su ENTRAMBI i motori —
v1 (``DirectTurnExecutor`` + tool loop legacy, guidato dai double dei test
legacy) e v2 (``AgentEngine`` + double + ``WsEventPort(translator=to_wire_frames)``
su un ``RecordingTransport`` locale). Il confronto è sul WIRE, non
sull'implementazione: i frame di entrambi i motori sono normalizzati (drop di
chiavi volatili + collapse di sequenze contigue) e confrontati. Le differenze
LEGITTIME (campi che l'evento greenfield ha scartato, o frame di request delle
interazioni posseduti dall'``InteractionPort`` e non dal translator) sono
registrate in :data:`KNOWN_DIFFERENCES` con motivazione, MAI nascoste
indebolendo la normalizzazione.

Il harness importa ``backend.services.turn`` (motore legacy) e i double dei suoi
test: vive nei TEST, e il suo scopo è proprio comparare v1 vs v2 — il contratto
import-linter copre solo ``backend/services/agent`` (che NON importa turn).
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from backend.api.ws_schema import validate_chat_server
from backend.core.plugin_models import ToolDefinition, ToolResult
from backend.services.agent import events as ev
from backend.services.agent import ports
from backend.services.agent.adapters.parity import to_wire_frames
from backend.services.agent.adapters.ws import WsEventPort
from backend.services.agent.engine import AgentEngine
from backend.services.agent.models import (
    ToolInvocation,
    ToolMeta,
    TurnRequest,
    TurnSource,
)
from backend.services.agent.retry import RetryPolicy
from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.models import TurnInput
from backend.tests.agent.doubles import (
    InMemoryPersistence,
    MapExecutionPort,
    NoopContextPort,
    ScriptedInteractionPort,
    ScriptedLLMPort,
    StaticPermissionPort,
)
from backend.tests.test_tool_loop import (
    MockSession,
    MockToolRegistry,
    MockWebSocket,
)

# ---------------------------------------------------------------------------
# Parte A — unit translator
# ---------------------------------------------------------------------------


def _one_sample_per_event_class() -> list[ev.AgentEvent]:
    """Un'istanza rappresentativa per OGNI classe di ``AgentEvent``."""
    call = ToolInvocation(call_id="c1", name="read", args={"q": "x"}, raw_args='{"q":"x"}')
    return [
        ev.TurnStartedEvent(turn_id="t", conversation_id="conv", source="chat"),
        ev.TurnDeltaEvent(turn_id="t", step=1, kind="text", text="ciao"),
        ev.TurnDeltaEvent(turn_id="t", step=1, kind="thinking", text="rifletto"),
        ev.LlmStepEvent(turn_id="t", step=1),
        ev.LlmStepEvent(turn_id="t", step=2),
        ev.ToolCallEvent(turn_id="t", step=1, call=call),
        ev.ToolStartedEvent(turn_id="t", call_id="c1"),
        ev.ToolProgressEvent(turn_id="t", call_id="c1", progress={"phase": "run", "percent": 50.0}),
        ev.ToolResultEvent(
            turn_id="t", call_id="c1", name="read", status="ok",
            content_preview="risultato", artifact_id=None,
        ),
        ev.ToolResultEvent(
            turn_id="t", call_id="c1", name="cad", status="ok",
            content_preview="art", artifact_id="art-1",
        ),
        ev.InteractionRequestedEvent(
            turn_id="t", interaction_id="i1", kind="confirm", call_id="c1",
            payload={"outcome": "ask", "risk_level": "medium", "description": "d"},
        ),
        ev.InteractionResolvedEvent(
            turn_id="t", interaction_id="i1", kind="confirm", outcome="approved",
        ),
        ev.ContextUsageEvent(turn_id="t", tokens=1000, context_window=32768),
        ev.CompactionEvent(
            turn_id="t", phase="started", tokens_before=None, tokens_after=None, error=None,
        ),
        ev.CompactionEvent(
            turn_id="t", phase="done", tokens_before=1000, tokens_after=500, error=None,
        ),
        ev.CompactionEvent(
            turn_id="t", phase="failed", tokens_before=None, tokens_after=None, error="boom",
        ),
        ev.TurnWarningEvent(turn_id="t", code="max_steps", message="attenzione"),
        ev.TurnErrorEvent(turn_id="t", code="engine_error", message="errore"),
        ev.TurnUsageEvent(turn_id="t", step=1, input_tokens=10, output_tokens=5, cost=0.01),
        ev.TurnFinishedEvent(
            turn_id="t", finish_reason="stop", steps=2, tool_calls=1, cost=0.02,
            final_message_id="m1",
        ),
        ev.RawToolCallDeltaEvent(
            turn_id="t",
            payload={"id": "call_1", "function": {"name": "read", "arguments": "{}"}},
        ),
    ]


def test_every_agent_event_maps_to_valid_wire_frames() -> None:
    """Ogni frame prodotto dal translator valida contro il contratto chat."""
    for event in _one_sample_per_event_class():
        frames = to_wire_frames(event)
        for frame in frames:
            validate_chat_server(frame)  # non deve sollevare


def test_tool_result_produces_legacy_and_canonical_pair() -> None:
    """ToolResultEvent → coppia [tool_execution_done, tool.result]."""
    e = ev.ToolResultEvent(
        turn_id="t", call_id="c", name="read", status="ok",
        content_preview="x", artifact_id=None,
    )
    types = [f["type"] for f in to_wire_frames(e)]
    assert types == ["tool_execution_done", "tool.result"]


def test_llm_step_one_emits_no_requery() -> None:
    """Step 1 → solo turn.llm_step; step>1 → llm_requery + turn.llm_step."""
    types = [f["type"] for f in to_wire_frames(ev.LlmStepEvent(turn_id="t", step=1))]
    assert types == ["turn.llm_step"]
    types2 = [f["type"] for f in to_wire_frames(ev.LlmStepEvent(turn_id="t", step=2))]
    assert types2 == ["llm_requery", "turn.llm_step"]


def test_turn_finished_only_no_done() -> None:
    """TurnFinishedEvent → solo turn.finished; `done` lo emette ws.py, non qui."""
    e = ev.TurnFinishedEvent(
        turn_id="t", finish_reason="stop", steps=1, tool_calls=0, cost=0.0,
        final_message_id=None,
    )
    types = [f["type"] for f in to_wire_frames(e)]
    assert types == ["turn.finished"]


def test_interaction_kind_is_mapped_to_wire_vocab() -> None:
    """Il kind interno 'confirm' diventa 'tool_confirmation' sul wire."""
    e = ev.InteractionRequestedEvent(
        turn_id="t", interaction_id="i", kind="confirm", call_id="c",
        payload={},
    )
    frame = to_wire_frames(e)[0]
    assert frame["kind"] == "tool_confirmation"


def test_raw_tool_call_delta_relays_complete_call() -> None:
    """RawToolCallDeltaEvent → un frame tool_call legacy con function completa."""
    e = ev.RawToolCallDeltaEvent(
        turn_id="t",
        payload={"id": "call_9", "function": {"name": "grep", "arguments": '{"p":1}'}},
    )
    frames = to_wire_frames(e)
    assert len(frames) == 1
    assert frames[0]["type"] == "tool_call"
    assert frames[0]["function"] == {"name": "grep", "arguments": '{"p":1}'}


# ---------------------------------------------------------------------------
# Parte B — harness end-to-end v1 vs v2
# ---------------------------------------------------------------------------

#: Conversation id fisso su entrambi i lati: ``conversation_id`` NON è tra le
#: drop_keys, quindi va allineato per un confronto pulito.
_CONV = "11111111-1111-1111-1111-111111111111"

#: Normalizzazione (NORMALIZE dello spec Task 15): chiavi volatili scartate.
#: ``execution_id`` è aggiunto qui — è l'alias wire dell'id di call che lo spec
#: già scarta sotto i nomi interni ``call_id``/``tool_call_id``/``interaction_id``
#: (id di correlazione random, non parte della forma-contratto). Vedi
#: :data:`KNOWN_DIFFERENCES` voce ``dropkey:execution_id``.
_DROP_KEYS = {
    "correlation_id", "timestamp", "turn_id", "message_id", "audit_id",
    "interaction_id", "call_id", "tool_call_id", "duration_ms", "cost",
    "input_tokens", "output_tokens", "execution_id",
}

#: Tipi le cui sequenze contigue collassano in un frame solo (spec Task 15).
_COLLAPSE_TYPES = {"token", "thinking", "tool_call"}

#: Differenze LEGITTIME tra il wire legacy (v1) e il wire tradotto (v2), ognuna
#: con una motivazione. NON sono papered-over: sono ESPLICITAMENTE tolte dal
#: confronto (campo o intero frame) e portate in review. La chiave codifica la
#: forma della differenza:
#:   ``field:<type>#<field>`` — quel campo è tolto dai frame di quel ``type``;
#:   ``type:<type>``          — l'intero frame di quel ``type`` è escluso;
#:   ``dropkey:<key>``        — chiave volatile aggiunta alle drop_keys.
KNOWN_DIFFERENCES: dict[str, str] = {
    "field:turn.usage#tool_calls": (
        "TurnUsageEvent greenfield non porta tool_calls (i contatori veri "
        "vivono su turn.finished e sui contatori di turno); v2 riempie 0."
    ),
    "field:turn.usage#max_steps": (
        "TurnUsageEvent greenfield non porta max_steps (budget noto al motore, "
        "non allo snapshot usage); v2 riempie 0."
    ),
    "field:tool_execution_start#tool_name": (
        "ToolStartedEvent greenfield porta solo call_id: il nome tool vive sul "
        "tool.call correlato per execution_id; v2 emette tool_name vuoto."
    ),
    "field:tool_execution_done#content_type": (
        "ToolResultEvent greenfield non porta content_type (vive sull'artifact "
        "registrato); v2 lo omette."
    ),
    "field:tool_execution_done#result": (
        "Il corpo testuale della tool response è prosa scritta dal motore (i "
        "messaggi sintetici v2 differiscono per wording/lingua); la parità "
        "asserisce success + framing, non il testo verbatim."
    ),
    "field:tool.result#content_type": (
        "Come tool_execution_done#content_type: l'evento greenfield lo ha "
        "scartato."
    ),
    "field:tool.result#result": (
        "Come tool_execution_done#result: corpo prosa engine-authored."
    ),
    "field:interaction.requested#tool_name": (
        "InteractionRequestedEvent greenfield non porta il nome tool (il FE lo "
        "correla via execution_id col tool.call); v2 lo omette."
    ),
    "type:context_info": (
        "Il motore greenfield emette uno snapshot context-usage PRIMA di ogni "
        "step>1 incondizionatamente; il loop legacy emette context_info solo "
        "quando la compressione parte davvero. Frame escluso dal confronto."
    ),
    "type:tool_confirmation_required": (
        "I frame legacy di RICHIESTA interazione li emette il round-trip "
        "dell'InteractionPort (WsInteractionPort), NON il translator (spec Task "
        "15). Nel harness v2 usa un ScriptedInteractionPort che non li emette."
    ),
    "type:client_tool_call": (
        "Come tool_confirmation_required: frame di request posseduto "
        "dall'InteractionPort, fuori dallo scope di to_wire_frames."
    ),
    "type:ask_user_required": (
        "Come tool_confirmation_required: frame di request posseduto "
        "dall'InteractionPort, fuori dallo scope di to_wire_frames."
    ),
    "dropkey:execution_id": (
        "Alias wire dell'id di call (random) che lo spec già scarta sotto "
        "call_id/tool_call_id/interaction_id; scartato per parità sugli id."
    ),
}

_EXCLUDED_TYPES: frozenset[str] = frozenset(
    key.split(":", 1)[1] for key in KNOWN_DIFFERENCES if key.startswith("type:")
)


def _stripped_fields() -> dict[str, set[str]]:
    """Deriva {type -> {campi da togliere}} dalle voci ``field:`` note."""
    out: dict[str, set[str]] = {}
    for key in KNOWN_DIFFERENCES:
        if not key.startswith("field:"):
            continue
        frame_type, field = key.split(":", 1)[1].split("#", 1)
        out.setdefault(frame_type, set()).add(field)
    return out


_STRIP_FIELDS = _stripped_fields()


def _normalized(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalizza una sequenza wire per il confronto di parità.

    Applica, nell'ordine: esclusione dei tipi noti divergenti, drop delle
    chiavi volatili, strip dei campi noti divergenti, collapse delle sequenze
    contigue dello stesso ``type`` (concatenando il contenuto testuale).
    """
    out: list[dict[str, Any]] = []
    for frame in frames:
        frame_type = frame.get("type")
        if frame_type in _EXCLUDED_TYPES:
            continue
        norm = {k: v for k, v in frame.items() if k not in _DROP_KEYS}
        for field in _STRIP_FIELDS.get(frame_type or "", set()):
            norm.pop(field, None)
        if frame_type in _COLLAPSE_TYPES and out and out[-1].get("type") == frame_type:
            _merge_collapsed(out[-1], norm)
            continue
        out.append(norm)
    return out


def _merge_collapsed(prev: dict[str, Any], nxt: dict[str, Any]) -> None:
    """Fonde un frame collassabile nel precedente concatenando il contenuto."""
    if "content" in prev and "content" in nxt:
        prev["content"] = prev["content"] + nxt["content"]
    elif "function" in prev and "function" in nxt:
        prev["function"]["arguments"] = (
            prev["function"].get("arguments", "") + nxt["function"].get("arguments", "")
        )


# --- v1 (legacy) runner -----------------------------------------------------


class _ScriptedV1LLM:
    """LLMService double per v1: una lista di eventi-dict per ogni chat()."""

    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any):
        resp = (
            self._responses[self._idx]
            if self._idx < len(self._responses)
            else [{"type": "done"}]
        )
        self._idx += 1
        for event in resp:
            yield event

    def build_continuation_messages(
        self, history: list[dict[str, Any]], memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        return [{"role": "system", "content": "sys"}]


def _v1_ctx(registry: MockToolRegistry) -> Any:
    """AppContext-stub minimo toccato da DirectTurnExecutor + run_tool_loop.

    Rispetto al ``_Ctx`` di ``test_tool_loop`` servono in più: ``context_manager``
    (il loop lo interroga quando ``context_window > 0``, mentre quei test usano
    0), ``config.llm.context_compression_enabled`` e ``max_tool_iterations`` /
    ``permissions.confirmation_timeout_s`` (letti dall'executor).
    """

    async def _noop(*a: Any, **k: Any) -> None:
        return None

    return SimpleNamespace(
        tool_registry=registry,
        event_bus=SimpleNamespace(emit=_noop),
        context_manager=None,
        config=SimpleNamespace(
            llm=SimpleNamespace(
                max_tool_iterations=4, tools_enabled=True, max_tools=0,
                priority_plugins=[], tool_execution_timeout=120.0,
                context_compression_enabled=False,
            ),
            permissions=SimpleNamespace(
                confirmation_timeout_s=60, confirmations_enabled=True,
            ),
        ),
    )


def _v1_turn(tools: list[dict[str, Any]] | None) -> TurnInput:
    return TurnInput(
        conv_id=uuid.UUID(_CONV), user_msg_id=uuid.uuid4(), user_content="ciao",
        history=[], messages=[{"role": "user", "content": "ciao"}], tools=tools,
        memory_context=None, cached_sys_prompt="sys", attachment_info=None,
        context_window=32768, version_group_id=None, version_index=0,
        client_ip="127.0.0.1", resolved_max_tokens=None,
    )


async def _run_v1(
    *,
    tools: list[dict[str, Any]] | None,
    responses: list[list[dict[str, Any]]],
    registry: MockToolRegistry,
    ws: MockWebSocket | None = None,
    cancel: asyncio.Event | None = None,
) -> list[dict[str, Any]]:
    """Guida l'intero ``DirectTurnExecutor`` legacy e ritorna i frame wire."""
    ws = ws or MockWebSocket()
    executor = DirectTurnExecutor(_v1_ctx(registry), _ScriptedV1LLM(responses))
    await executor.execute(
        turn=_v1_turn(tools), sink=ws, cancel_event=cancel or asyncio.Event(),
        session=MockSession(), channel=ws,
    )
    return ws.sent


# --- v2 (greenfield) runner -------------------------------------------------


class _RecordingTransport:
    """Trasporto WS-like: cattura i frame che WsEventPort gli invia."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    @property
    def connected(self) -> bool:
        return True

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


def _v2_request() -> TurnRequest:
    return TurnRequest(
        conversation_id=_CONV, system_prompt="sys",
        history=[{"role": "user", "content": "ciao"}], tools=[],
        source=TurnSource.CHAT, max_steps=8, context_window=32768,
        resolved_max_tokens=None, client_ip=None,
        version_group_id=None, version_index=None,
    )


async def _run_v2(
    *,
    llm_steps: list[list[ports.LLMEvent]],
    execution: MapExecutionPort,
    verdicts: dict[str, ports.GateVerdict] | None = None,
    confirm: ports.InteractionOutcome = ports.InteractionOutcome.APPROVED,
    cancel: asyncio.Event | None = None,
) -> list[dict[str, Any]]:
    """Guida l'``AgentEngine`` con WsEventPort(to_wire_frames) e ritorna i frame."""
    transport = _RecordingTransport()
    engine = AgentEngine(
        llm=ScriptedLLMPort(steps=llm_steps),
        permissions=StaticPermissionPort(
            verdicts=verdicts or {},
            default=ports.GateVerdict(action=ports.GateAction.EXECUTE, outcome="allow"),
        ),
        interaction=ScriptedInteractionPort(confirm=confirm),
        events=WsEventPort(transport, to_wire_frames),
        persistence=InMemoryPersistence(),
        context=NoopContextPort(),
        execution=execution,
        retry=RetryPolicy(),
    )
    await engine.run(_v2_request(), cancel=cancel or asyncio.Event())
    return transport.sent


def _usage_v1(inp: int, out: int) -> dict[str, Any]:
    return {"type": "usage", "input_tokens": inp, "output_tokens": out, "cost": 0.0}


def _raw_tc(call_id: str, name: str) -> dict[str, Any]:
    return {"type": "tool_call", "id": call_id, "function": {"name": name, "arguments": "{}"}}


# ---------------------------------------------------------------------------
# Scenari di parità
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_scenario_no_tools() -> None:
    """Turno senza tool: solo testo, stesso stream wire su entrambi i motori."""
    v1 = await _run_v1(
        tools=None,
        responses=[[
            {"type": "token", "content": "Hello"}, _usage_v1(3, 2),
            {"type": "done", "finish_reason": "stop"},
        ]],
        registry=MockToolRegistry(),
    )
    v2 = await _run_v2(
        llm_steps=[[
            ports.LLMTextDelta(text="Hello"), ports.LLMUsage(3, 2, 0.0),
            ports.LLMStepDone(finish_reason="stop", tool_calls=()),
        ]],
        execution=MapExecutionPort(tools={}),
    )
    assert _normalized(v1) == _normalized(v2)


@pytest.mark.asyncio
async def test_parity_scenario_one_tool_ok() -> None:
    """Un tool server eseguito con successo, poi risposta finale."""
    v1 = await _run_v1(
        tools=[{"type": "function", "function": {"name": "read"}}],
        responses=[
            [_raw_tc("call_read", "read"), _usage_v1(3, 2),
             {"type": "done", "finish_reason": "tool_calls"}],
            [{"type": "token", "content": "final answer"}, _usage_v1(4, 3),
             {"type": "done", "finish_reason": "stop"}],
        ],
        registry=MockToolRegistry(
            definitions={"read": ToolDefinition(name="read", description="d")},
        ),
    )
    inv = ToolInvocation(call_id="call_read", name="read", args={}, raw_args="{}")
    v2 = await _run_v2(
        llm_steps=[
            [ports.LLMToolCallDelta(payload=_raw_tc("call_read", "read")),
             ports.LLMUsage(3, 2, 0.0),
             ports.LLMStepDone(finish_reason="tool_calls", tool_calls=(inv,))],
            [ports.LLMTextDelta(text="final answer"), ports.LLMUsage(4, 3, 0.0),
             ports.LLMStepDone(finish_reason="stop", tool_calls=())],
        ],
        execution=MapExecutionPort(
            tools={"read": ports.ToolExecutionOutput(ok=True, content="result:read")},
            meta={"read": ToolMeta(exists=True)},
        ),
    )
    assert _normalized(v1) == _normalized(v2)


@pytest.mark.asyncio
async def test_parity_scenario_tool_rejected() -> None:
    """Tool rischioso rifiutato via conferma, poi risposta finale."""
    v1 = await _run_v1(
        tools=[{"type": "function", "function": {"name": "danger"}}],
        responses=[
            [_raw_tc("call_danger", "danger"), _usage_v1(3, 2),
             {"type": "done", "finish_reason": "tool_calls"}],
            [{"type": "token", "content": "Rejected"}, _usage_v1(4, 3),
             {"type": "done", "finish_reason": "stop"}],
        ],
        registry=MockToolRegistry(
            definitions={"danger": ToolDefinition(
                name="danger", description="Dangerous op", requires_confirmation=True,
            )},
        ),
        ws=MockWebSocket(auto_confirm=False),
    )
    inv = ToolInvocation(call_id="call_danger", name="danger", args={}, raw_args="{}")
    v2 = await _run_v2(
        llm_steps=[
            [ports.LLMToolCallDelta(payload=_raw_tc("call_danger", "danger")),
             ports.LLMUsage(3, 2, 0.0),
             ports.LLMStepDone(finish_reason="tool_calls", tool_calls=(inv,))],
            [ports.LLMTextDelta(text="Rejected"), ports.LLMUsage(4, 3, 0.0),
             ports.LLMStepDone(finish_reason="stop", tool_calls=())],
        ],
        execution=MapExecutionPort(
            tools={"danger": ports.ToolExecutionOutput(ok=True, content="x")},
            meta={"danger": ToolMeta(exists=True)},
        ),
        verdicts={"danger": ports.GateVerdict(
            action=ports.GateAction.CONFIRM, outcome="ask",
            risk_level="dangerous", description="Dangerous op",
        )},
        confirm=ports.InteractionOutcome.REJECTED,
    )
    assert _normalized(v1) == _normalized(v2)


@pytest.mark.asyncio
async def test_parity_scenario_cancel_mid_turn() -> None:
    """Cancel a metà: l'esecuzione del tool scatena il cancel; stop dopo persist."""
    cancel_v1 = asyncio.Event()

    async def _v1_exec(name: str, args: dict[str, Any], ctx: Any) -> ToolResult:
        cancel_v1.set()
        return ToolResult.ok("result:read")

    v1 = await _run_v1(
        tools=[{"type": "function", "function": {"name": "read"}}],
        responses=[
            [_raw_tc("call_read", "read"), _usage_v1(3, 2),
             {"type": "done", "finish_reason": "tool_calls"}],
            [{"type": "token", "content": "unreached"}, {"type": "done"}],
        ],
        registry=MockToolRegistry(
            definitions={"read": ToolDefinition(name="read", description="d")},
            execute_fn=_v1_exec,
        ),
        cancel=cancel_v1,
    )

    cancel_v2 = asyncio.Event()

    class _CancellingExec(MapExecutionPort):
        async def execute(
            self, call: ToolInvocation, *, client_ip: str | None, conversation_id: str,
        ) -> ports.ToolExecutionOutput:
            cancel_v2.set()
            return ports.ToolExecutionOutput(ok=True, content="result:read")

    inv = ToolInvocation(call_id="call_read", name="read", args={}, raw_args="{}")
    v2 = await _run_v2(
        llm_steps=[
            [ports.LLMToolCallDelta(payload=_raw_tc("call_read", "read")),
             ports.LLMUsage(3, 2, 0.0),
             ports.LLMStepDone(finish_reason="tool_calls", tool_calls=(inv,))],
            [ports.LLMTextDelta(text="unreached"),
             ports.LLMStepDone(finish_reason="stop", tool_calls=())],
        ],
        execution=_CancellingExec(
            tools={"read": ports.ToolExecutionOutput(ok=True, content="result:read")},
            meta={"read": ToolMeta(exists=True)},
        ),
        cancel=cancel_v2,
    )
    assert _normalized(v1) == _normalized(v2)


def test_known_differences_all_have_motivation() -> None:
    """Ogni voce di KNOWN_DIFFERENCES porta una motivazione non vuota."""
    assert KNOWN_DIFFERENCES, "il registro delle differenze note non è vuoto"
    for key, reason in KNOWN_DIFFERENCES.items():
        assert reason.strip(), f"differenza nota senza motivazione: {key}"
        assert key.split(":", 1)[0] in {"field", "type", "dropkey"}
