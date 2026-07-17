"""Test del trasporto WS greenfield (``adapters/ws.py``).

``FakeWebSocket`` è un doppio locale del ``WebSocket`` Starlette: coda inbound
controllata dal test (``feed``), coda outbound osservabile (``next_sent``),
``disconnect()`` che fa sollevare ``WebSocketDisconnect`` dal ``receive_json``
del pump e ``RuntimeError`` dai ``send_json`` successivi (stesso contratto del
socket reale dopo la close).

I 6 test del brief sono verbatim; gli extra coprono i comportamenti vincolanti
non coperti: cancel che non trapela tra turni, cancel-frame che risolve le
request pendenti a ``None``, ``confirm_tool`` che ritorna ``DISCONNECTED``
come DATO (adjudicazione T4), client/ask_user che propagano
``EngineDisconnected``, forma dei frame legacy validata contro i modelli
Pydantic reali di ``api/ws_schema/chat.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from backend.api.ws_schema.chat import (
    WsAskUserRequired,
    WsClientToolCall,
    WsToolConfirmationRequired,
)
from backend.services.agent.adapters.ws import (
    WsEventPort,
    WsInteractionPort,
    WsTransport,
)
from backend.services.agent.models import ToolInvocation
from backend.services.agent.ports import (
    EngineDisconnected,
    GateAction,
    GateVerdict,
    InteractionOutcome,
)

_DISCONNECT = object()


class FakeWebSocket:
    """Doppio del WebSocket Starlette: inbound pilotato, outbound osservabile."""

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[Any] = asyncio.Queue()
        self._outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self._closed = False

    async def feed(self, frame: dict[str, Any]) -> None:
        """Inietta un frame inbound (come se il client lo avesse inviato)."""
        await self._inbound.put(frame)

    async def receive_json(self) -> Any:
        item = await self._inbound.get()
        if item is _DISCONNECT:
            self._closed = True
            raise WebSocketDisconnect(code=1000)
        return item

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError('Cannot call "send" once a close message has been sent.')
        self.sent.append(payload)
        await self._outbound.put(payload)

    async def next_sent(self) -> dict[str, Any]:
        """Attende e ritorna il prossimo frame outbound."""
        return await self._outbound.get()

    async def disconnect(self) -> None:
        """Simula la caduta del client: receive solleva, send fallisce."""
        self._closed = True
        await self._inbound.put(_DISCONNECT)


async def _until(cond: Callable[[], bool]) -> None:
    """Attende che ``cond()`` diventi vera (poll con sleep 0.005)."""
    while not cond():
        await asyncio.sleep(0.005)


# ---------------------------------------------------------------------------
# Test del brief (verbatim)
# ---------------------------------------------------------------------------


async def test_single_reader_and_cancel_dispatch() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    cancel = t.begin_turn()
    await t.start()
    await ws.feed({"type": "cancel"})
    await asyncio.wait_for(_until(lambda: cancel.is_set()), timeout=1)


async def test_request_roundtrip_with_correlation() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()

    async def _answer() -> None:
        sent = await ws.next_sent()          # frame outbound della request
        await ws.feed({"type": "tool_confirmation_response",
                       "correlation_id": sent["correlation_id"], "approved": True})

    task = asyncio.create_task(_answer())
    resp = await t.request("tool_confirmation", {"type": "tool_confirmation_required"},
                           timeout_s=2, cancel=asyncio.Event())
    await task
    assert resp is not None and resp["approved"] is True


async def test_request_resolves_by_alt_key_when_correlation_absent() -> None:
    """Correlation bridge (Task 16): la FE risponde con ``execution_id`` e NON
    riecheggia il ``correlation_id``. Con ``alt_key`` registrato, il pump risolve
    la request pendente quando l'``execution_id`` inbound combacia e il
    ``correlation_id`` è assente.
    """
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()

    async def _answer() -> None:
        await ws.next_sent()  # frame outbound della request
        # Risposta della FE: SOLO execution_id, nessun correlation_id.
        await ws.feed({"type": "tool_confirmation_response",
                       "execution_id": "exec-9", "approved": True})

    task = asyncio.create_task(_answer())
    resp = await t.request(
        "tool_confirmation",
        {"type": "tool_confirmation_required", "execution_id": "exec-9"},
        timeout_s=2, cancel=asyncio.Event(), alt_key="exec-9",
    )
    await task
    assert resp is not None and resp["approved"] is True
    await t.aclose()


async def test_correlation_id_wins_over_alt_key() -> None:
    """Quando entrambe le chiavi sono presenti, il ``correlation_id`` vince
    (l'alt_key resta solo un fallback per la FE che non lo riecheggia).
    """
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()

    async def _answer() -> None:
        sent = await ws.next_sent()
        await ws.feed({"type": "tool_confirmation_response",
                       "correlation_id": sent["correlation_id"],
                       "execution_id": "exec-7", "approved": False})

    task = asyncio.create_task(_answer())
    resp = await t.request(
        "tool_confirmation",
        {"type": "tool_confirmation_required", "execution_id": "exec-7"},
        timeout_s=2, cancel=asyncio.Event(), alt_key="exec-7",
    )
    await task
    assert resp is not None and resp["approved"] is False
    await t.aclose()


async def test_stale_response_is_discarded() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
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
    t = WsTransport(ws)
    await t.start()
    task = asyncio.create_task(t.request("tool_confirmation", {"type": "x"},
                                         timeout_s=5, cancel=asyncio.Event()))
    await ws.disconnect()
    with pytest.raises(EngineDisconnected):
        await task


async def test_timeout_returns_none_cancel_returns_none() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    resp = await t.request("tool_confirmation", {"type": "tool_confirmation_required"},
                           timeout_s=0.05, cancel=asyncio.Event())
    assert resp is None
    cancelled = asyncio.Event()
    cancelled.set()
    resp2 = await t.request("tool_confirmation", {"type": "tool_confirmation_required"},
                            timeout_s=5, cancel=cancelled)
    assert resp2 is None


async def test_send_after_close_never_raises() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    await ws.disconnect()
    await t.send_json({"type": "token", "content": "x"})   # non deve sollevare
    assert t.connected is False


# ---------------------------------------------------------------------------
# Extra: comportamenti vincolanti del trasporto
# ---------------------------------------------------------------------------


async def test_cancel_does_not_leak_across_turns() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    first = t.begin_turn()
    await t.start()
    await ws.feed({"type": "cancel"})
    await asyncio.wait_for(_until(lambda: first.is_set()), timeout=1)
    second = t.begin_turn()
    assert second is not first
    assert not second.is_set()
    await t.aclose()


async def test_cancel_frame_resolves_pending_request_to_none() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    task = asyncio.create_task(t.request(
        "tool_confirmation", {"type": "tool_confirmation_required"},
        timeout_s=5, cancel=asyncio.Event(),
    ))
    await ws.next_sent()                       # la request è in volo
    await ws.feed({"type": "cancel"})
    resp = await asyncio.wait_for(task, timeout=1)
    assert resp is None
    await t.aclose()


async def test_unmatched_frames_queue_as_user_messages_and_none_on_disconnect() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    await ws.feed({"content": "ciao"})         # frame utente non taggato
    msg = await asyncio.wait_for(t.next_user_message(), timeout=1)
    assert msg == {"content": "ciao"}
    await ws.disconnect()
    end = await asyncio.wait_for(t.next_user_message(), timeout=1)
    assert end is None
    # dopo la sentinella: sempre None, senza bloccare
    assert await asyncio.wait_for(t.next_user_message(), timeout=1) is None


async def test_aclose_cancels_pump_and_unblocks_pending_request() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    task = asyncio.create_task(t.request(
        "tool_confirmation", {"type": "tool_confirmation_required"},
        timeout_s=30, cancel=asyncio.Event(),
    ))
    await ws.next_sent()
    await t.aclose()
    with pytest.raises(EngineDisconnected):
        await asyncio.wait_for(task, timeout=1)
    assert t.connected is False


# ---------------------------------------------------------------------------
# WsEventPort
# ---------------------------------------------------------------------------


async def test_event_port_translates_and_sends_each_frame() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    port = WsEventPort(t, lambda event: [
        {"type": "token", "content": "a"},
        {"type": "token", "content": "b"},
    ])
    await port.emit(object())  # type: ignore[arg-type] — translator banale
    assert ws.sent == [
        {"type": "token", "content": "a"},
        {"type": "token", "content": "b"},
    ]
    await t.aclose()


async def test_event_port_never_raises_after_disconnect() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    await ws.disconnect()
    await asyncio.wait_for(_until(lambda: not t.connected), timeout=1)
    port = WsEventPort(t, lambda event: [{"type": "token", "content": "x"}])
    await port.emit(object())  # type: ignore[arg-type] — non deve sollevare
    await t.aclose()


# ---------------------------------------------------------------------------
# WsInteractionPort
# ---------------------------------------------------------------------------

_CALL = ToolInvocation(
    call_id="exec-1", name="write_file",
    args={"path": "x.txt"}, raw_args='{"path": "x.txt"}',
)
_VERDICT = GateVerdict(
    action=GateAction.CONFIRM, outcome="needs_confirmation",
    reason="fuori scope", risk_level="dangerous", description="scrive un file",
)


def _port(t: WsTransport) -> WsInteractionPort:
    return WsInteractionPort(t)


async def test_confirm_tool_maps_approved_and_rejected() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    port = _port(t)

    async def _respond(approved: bool) -> dict[str, Any]:
        sent = await ws.next_sent()
        await ws.feed({"type": "tool_confirmation_response",
                       "correlation_id": sent["correlation_id"],
                       "approved": approved})
        return sent

    answer = asyncio.create_task(_respond(True))
    outcome = await port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    )
    sent = await answer
    assert outcome is InteractionOutcome.APPROVED
    # il frame legacy valida contro il modello Pydantic reale del contratto
    frame = WsToolConfirmationRequired.model_validate(sent)
    assert frame.execution_id == "exec-1"
    assert frame.tool_name == "write_file"
    assert frame.args == {"path": "x.txt"}
    assert frame.risk_level == "dangerous"

    answer2 = asyncio.create_task(_respond(False))
    outcome2 = await port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    )
    await answer2
    assert outcome2 is InteractionOutcome.REJECTED
    await t.aclose()


async def test_tool_confirmation_request_frame_matches_legacy_contract() -> None:
    """Il frame di RICHIESTA che WsInteractionPort invia per una ToolInvocation
    + GateVerdict pinna la superficie consumata dal contratto legacy.

    Fix review T15 §6: i frame di request delle interazioni sono posseduti
    dall'InteractionPort (non dal translator di parità), quindi la parità su di
    essi si asserisce QUI, sui valori-campo, non nel harness. Non serve il
    motore legacy: si valida contro il modello Pydantic reale del contratto
    (``WsToolConfirmationRequired``) E si asseriscono i valori specifici.
    """
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    port = _port(t)

    async def _respond() -> dict[str, Any]:
        sent = await ws.next_sent()
        await ws.feed({"type": "tool_confirmation_response",
                       "correlation_id": sent["correlation_id"], "approved": True})
        return sent

    answer = asyncio.create_task(_respond())
    await port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    )
    sent = await answer

    # 1. Valida contro il modello Pydantic reale del contratto (extra='forbid').
    frame = WsToolConfirmationRequired.model_validate(sent)
    # 2. Asserisce i VALORI-campo che il contratto legacy richiede.
    assert frame.execution_id == _CALL.call_id          # execution_id == call_id
    assert frame.tool_name == _CALL.name
    assert frame.args == _CALL.args
    assert frame.risk_level == _VERDICT.risk_level       # "dangerous" ∈ vocab
    assert frame.description == _VERDICT.description      # presente, non vuota
    assert frame.description
    assert frame.reasoning == _VERDICT.reason            # reasoning presente
    await t.aclose()


async def test_confirm_tool_resolves_on_execution_id_only_reply() -> None:
    """Correlation bridge end-to-end: ``WsInteractionPort`` registra
    ``alt_key=call_id``, così una risposta FE con SOLO ``execution_id`` (nessun
    ``correlation_id``, come fa il frontend attuale) risolve la conferma.
    """
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    port = _port(t)

    async def _respond() -> None:
        sent = await ws.next_sent()
        assert sent["execution_id"] == _CALL.call_id
        await ws.feed({"type": "tool_confirmation_response",
                       "execution_id": _CALL.call_id, "approved": True})

    answer = asyncio.create_task(_respond())
    outcome = await port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    )
    await answer
    assert outcome is InteractionOutcome.APPROVED
    await t.aclose()


async def test_confirm_tool_timeout_and_cancel_outcomes() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    port = _port(t)
    outcome = await port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=0.05, cancel=asyncio.Event(),
    )
    assert outcome is InteractionOutcome.TIMEOUT
    cancelled = asyncio.Event()
    cancelled.set()
    outcome2 = await port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=5, cancel=cancelled,
    )
    assert outcome2 is InteractionOutcome.CANCELLED
    await t.aclose()


async def test_confirm_tool_disconnect_returns_disconnected_as_data() -> None:
    """Adjudicazione T4: su disconnect la conferma NON propaga l'eccezione."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    port = _port(t)
    task = asyncio.create_task(port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=5, cancel=asyncio.Event(),
    ))
    await ws.next_sent()
    await ws.disconnect()
    outcome = await asyncio.wait_for(task, timeout=1)
    assert outcome is InteractionOutcome.DISCONNECTED
    await t.aclose()


async def test_run_client_tool_roundtrip_and_disconnect_raises() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    port = _port(t)

    async def _respond() -> dict[str, Any]:
        sent = await ws.next_sent()
        await ws.feed({"type": "client_tool_result",
                       "correlation_id": sent["correlation_id"],
                       "success": True, "result": "fatto"})
        return sent

    answer = asyncio.create_task(_respond())
    out = await port.run_client_tool(
        _CALL, interaction_id="ix", timeout_s=2, cancel=asyncio.Event(),
    )
    sent = await answer
    assert out.ok is True and out.content == "fatto"
    frame = WsClientToolCall.model_validate(sent)
    assert frame.execution_id == "exec-1" and frame.tool_name == "write_file"

    task = asyncio.create_task(
        port.run_client_tool(_CALL, interaction_id="ix", timeout_s=5, cancel=asyncio.Event())
    )
    await ws.next_sent()
    await ws.disconnect()
    with pytest.raises(EngineDisconnected):
        await asyncio.wait_for(task, timeout=1)
    await t.aclose()


async def test_ask_user_roundtrip_timeout_and_frame_shape() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    port = _port(t)
    call = ToolInvocation(
        call_id="exec-2", name="ask_user",
        args={"questions": [{"id": "q1", "text": "Quale?", "type": "radio",
                             "options": ["a", "b"]}]},
        raw_args="{}",
    )

    async def _respond() -> dict[str, Any]:
        sent = await ws.next_sent()
        await ws.feed({"type": "ask_user_response",
                       "correlation_id": sent["correlation_id"],
                       "answers": [{"question_id": "q1", "selected": ["a"],
                                    "free_text": None}]})
        return sent

    answer = asyncio.create_task(_respond())
    out = await port.ask_user(call, interaction_id="ix", timeout_s=2, cancel=asyncio.Event())
    sent = await answer
    assert out.ok is True and "q1" in out.content and "a" in out.content
    frame = WsAskUserRequired.model_validate(sent)
    assert frame.execution_id == "exec-2"
    assert frame.questions[0].id == "q1"
    assert frame.questions[0].options == ["a", "b"]

    timed_out = await port.ask_user(
        call, interaction_id="ix", timeout_s=0.05, cancel=asyncio.Event(),
    )
    assert timed_out.ok is False and timed_out.error is not None
    await t.aclose()
