"""Test del trasporto WS greenfield (``adapters/ws.py``), vocabolario v2.

``FakeWebSocket`` è un doppio locale del ``WebSocket`` Starlette: coda inbound
controllata dal test (``feed``), coda outbound osservabile (``sent``),
``disconnect()`` che fa sollevare ``WebSocketDisconnect`` dal ``receive_json``
del pump e ``RuntimeError`` dai ``send_json`` successivi (stesso contratto del
socket reale dopo la close).

Round-trip interattivo v2 (Task 8): il frame di RICHIESTA è l'evento
``interaction.requested`` del motore (emesso dall'``EventPort``, testato in
``test_wire.py``), NON un frame costruito dalla porta. ``WsInteractionPort``
attende solo la ``interaction.response`` correlata per ``interaction_id`` e non
invia NULLA sul socket. Il read-pump smista ``cancel`` /
``interaction.response`` / messaggi utente; il bridge ``correlation_id``/
``alt_key`` è morto.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

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
    RememberScope,
)

_DISCONNECT = object()


class FakeWebSocket:
    """Doppio del WebSocket Starlette: inbound pilotato, outbound osservabile."""

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[Any] = asyncio.Queue()
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

    async def disconnect(self) -> None:
        """Simula la caduta del client: receive solleva, send fallisce."""
        self._closed = True
        await self._inbound.put(_DISCONNECT)


async def _until(cond: Callable[[], bool]) -> None:
    """Attende che ``cond()`` diventi vera (poll con sleep 0.005)."""
    while not cond():
        await asyncio.sleep(0.005)


async def _registered(t: WsTransport, interaction_id: str) -> None:
    """Attende che il waiter di ``interaction_id`` sia registrato nel transport."""
    await asyncio.wait_for(
        _until(lambda: interaction_id in t._pending), timeout=1,  # noqa: SLF001
    )


# ---------------------------------------------------------------------------
# Transport: pump, cancel, wait_response
# ---------------------------------------------------------------------------


async def test_single_reader_and_cancel_dispatch() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    cancel = t.begin_turn()
    await t.start()
    await ws.feed({"type": "cancel"})
    await asyncio.wait_for(_until(lambda: cancel.is_set()), timeout=1)
    await t.aclose()


async def test_wait_response_resolves_by_interaction_id() -> None:
    """Registrazione sincrona: wait_response, POI il pump riceve la
    interaction.response correlata → il future risolve col frame."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    task = asyncio.create_task(
        t.wait_response("i1", timeout_s=2, cancel=asyncio.Event())
    )
    await _registered(t, "i1")
    await ws.feed({"type": "interaction.response", "interaction_id": "i1", "approved": True})
    resp = await asyncio.wait_for(task, timeout=1)
    assert resp is not None and resp["approved"] is True
    await t.aclose()


async def test_interaction_response_stale_is_dropped() -> None:
    """Una interaction.response con interaction_id sconosciuto è scartata con
    log, NON accodata come messaggio utente."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    await ws.feed({"type": "interaction.response", "interaction_id": "ignota", "approved": True})
    # Un vero messaggio utente successivo deve arrivare per primo: la stale
    # è stata scartata, non messa in coda davanti a lui.
    await ws.feed({"content": "ciao"})
    msg = await asyncio.wait_for(t.next_user_message(), timeout=1)
    assert msg == {"content": "ciao"}
    await t.aclose()


async def test_wait_response_disconnect_raises_engine_disconnected() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    task = asyncio.create_task(
        t.wait_response("i1", timeout_s=5, cancel=asyncio.Event())
    )
    await _registered(t, "i1")
    await ws.disconnect()
    with pytest.raises(EngineDisconnected):
        await asyncio.wait_for(task, timeout=1)


async def test_wait_response_already_disconnected_fast_path() -> None:
    """Registrazione a socket già caduto: esito disconnect immediato, nessun
    waiter lasciato in ``_pending``."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    await ws.disconnect()
    await asyncio.wait_for(_until(lambda: not t.connected), timeout=1)
    with pytest.raises(EngineDisconnected):
        await t.wait_response("i1", timeout_s=5, cancel=asyncio.Event())
    assert "i1" not in t._pending  # noqa: SLF001


async def test_wait_response_precedence_disconnect_over_cancel() -> None:
    """Precedenza invariata: disconnect > cancel > timeout. Cancel armato e
    disconnect nello stesso giro: il future risolto eccezionalmente dal
    disconnect è controllato per primo → vince."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    cancel = asyncio.Event()
    task = asyncio.create_task(t.wait_response("i1", timeout_s=5, cancel=cancel))
    await _registered(t, "i1")
    cancel.set()  # cancel armato...
    t._mark_disconnected()  # ...e disconnect nello stesso giro  # noqa: SLF001
    with pytest.raises(EngineDisconnected):
        await asyncio.wait_for(task, timeout=1)
    await t.aclose()


async def test_wait_response_timeout_and_cancel_return_none() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    resp = await t.wait_response("i1", timeout_s=0.05, cancel=asyncio.Event())
    assert resp is None
    cancelled = asyncio.Event()
    cancelled.set()
    resp2 = await t.wait_response("i2", timeout_s=5, cancel=cancelled)
    assert resp2 is None
    await t.aclose()


async def test_cancel_frame_resolves_pending_interaction_to_none() -> None:
    """Il frame ``cancel`` risolve a ``None`` le interazioni pendenti
    (percorso ``_resolve_all_pending_to_none`` preservato — review T6)."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    task = asyncio.create_task(
        t.wait_response("i1", timeout_s=5, cancel=asyncio.Event())
    )
    await _registered(t, "i1")
    await ws.feed({"type": "cancel"})
    resp = await asyncio.wait_for(task, timeout=1)
    assert resp is None
    await t.aclose()


async def test_send_after_close_never_raises() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    await ws.disconnect()
    await t.send_json({"type": "turn.delta", "text": "x"})  # non deve sollevare
    assert t.connected is False


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


async def test_unmatched_frames_queue_as_user_messages_and_none_on_disconnect() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    await ws.feed({"content": "ciao"})  # frame utente non taggato
    msg = await asyncio.wait_for(t.next_user_message(), timeout=1)
    assert msg == {"content": "ciao"}
    await ws.disconnect()
    end = await asyncio.wait_for(t.next_user_message(), timeout=1)
    assert end is None
    # dopo la sentinella: sempre None, senza bloccare
    assert await asyncio.wait_for(t.next_user_message(), timeout=1) is None


async def test_aclose_cancels_pump_and_unblocks_pending_interaction() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    task = asyncio.create_task(
        t.wait_response("i1", timeout_s=30, cancel=asyncio.Event())
    )
    await _registered(t, "i1")
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
        {"type": "turn.delta", "text": "a"},
        {"type": "turn.delta", "text": "b"},
    ])
    await port.emit(object())  # type: ignore[arg-type] — translator banale
    assert ws.sent == [
        {"type": "turn.delta", "text": "a"},
        {"type": "turn.delta", "text": "b"},
    ]
    await t.aclose()


async def test_event_port_never_raises_after_disconnect() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    await t.start()
    await ws.disconnect()
    await asyncio.wait_for(_until(lambda: not t.connected), timeout=1)
    port = WsEventPort(t, lambda event: [{"type": "turn.delta", "text": "x"}])
    await port.emit(object())  # type: ignore[arg-type] — non deve sollevare
    await t.aclose()


# ---------------------------------------------------------------------------
# WsInteractionPort (vocabolario v2: nessun frame outbound dalla porta)
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


async def test_confirm_tool_builds_no_frame() -> None:
    """La conferma NON invia frame outbound: il frame di richiesta è l'evento
    ``interaction.requested`` del motore. Il transport double non registra send."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    port = _port(t)
    task = asyncio.create_task(port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    ))
    await _registered(t, "ix")
    await ws.feed({"type": "interaction.response", "interaction_id": "ix", "approved": True})
    result = await asyncio.wait_for(task, timeout=1)
    assert result.outcome is InteractionOutcome.APPROVED
    assert ws.sent == []  # nessun frame costruito dalla porta
    await t.aclose()


async def test_confirm_tool_maps_response() -> None:
    """approved True/False → APPROVED/REJECTED."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    port = _port(t)

    task = asyncio.create_task(port.confirm_tool(
        _CALL, interaction_id="ia", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    ))
    await _registered(t, "ia")
    await ws.feed({"type": "interaction.response", "interaction_id": "ia", "approved": True})
    result = await asyncio.wait_for(task, timeout=1)
    assert result.outcome is InteractionOutcome.APPROVED

    task2 = asyncio.create_task(port.confirm_tool(
        _CALL, interaction_id="ib", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    ))
    await _registered(t, "ib")
    await ws.feed({"type": "interaction.response", "interaction_id": "ib", "approved": False})
    result2 = await asyncio.wait_for(task2, timeout=1)
    assert result2.outcome is InteractionOutcome.REJECTED
    await t.aclose()


async def test_confirm_tool_extracts_remember_choice() -> None:
    """La scelta ``remember`` della risposta approvata arriva nel risultato
    (fix smoke Fase 1: la porta la SCARTAVA e nessuna regola veniva salvata)."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    port = _port(t)

    task = asyncio.create_task(port.confirm_tool(
        _CALL, interaction_id="ir1", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    ))
    await _registered(t, "ir1")
    await ws.feed({
        "type": "interaction.response", "interaction_id": "ir1",
        "approved": True, "remember": "conversation",
    })
    result = await asyncio.wait_for(task, timeout=1)
    assert result.outcome is InteractionOutcome.APPROVED
    assert result.remember is RememberScope.CONVERSATION

    task2 = asyncio.create_task(port.confirm_tool(
        _CALL, interaction_id="ir2", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    ))
    await _registered(t, "ir2")
    await ws.feed({
        "type": "interaction.response", "interaction_id": "ir2",
        "approved": True, "remember": "persistent",
    })
    result2 = await asyncio.wait_for(task2, timeout=1)
    assert result2.remember is RememberScope.PERSISTENT
    await t.aclose()


async def test_confirm_tool_remember_defaults_to_none_when_absent_invalid_or_rejected() -> None:
    """remember assente o non nel vocabolario → NONE; su rifiuto la scelta è
    IGNORATA (una call declinata non va mai ricordata, difesa in profondità
    oltre al 'none' forzato dal FE)."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    port = _port(t)

    for interaction_id, frame_extra in (
        ("in1", {}),                                     # assente
        ("in2", {"remember": "sempre"}),                 # fuori vocabolario
        ("in3", {"remember": 42}),                       # tipo sbagliato
    ):
        task = asyncio.create_task(port.confirm_tool(
            _CALL, interaction_id=interaction_id, verdict=_VERDICT,
            timeout_s=2, cancel=asyncio.Event(),
        ))
        await _registered(t, interaction_id)
        await ws.feed({
            "type": "interaction.response", "interaction_id": interaction_id,
            "approved": True, **frame_extra,
        })
        result = await asyncio.wait_for(task, timeout=1)
        assert result.outcome is InteractionOutcome.APPROVED
        assert result.remember is RememberScope.NONE

    task = asyncio.create_task(port.confirm_tool(
        _CALL, interaction_id="in4", verdict=_VERDICT, timeout_s=2, cancel=asyncio.Event(),
    ))
    await _registered(t, "in4")
    await ws.feed({
        "type": "interaction.response", "interaction_id": "in4",
        "approved": False, "remember": "persistent",
    })
    result = await asyncio.wait_for(task, timeout=1)
    assert result.outcome is InteractionOutcome.REJECTED
    assert result.remember is RememberScope.NONE
    await t.aclose()


async def test_confirm_tool_timeout_and_cancel_outcomes() -> None:
    """None + cancel set → CANCELLED; None (timeout) → TIMEOUT."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    port = _port(t)
    result = await port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=0.05, cancel=asyncio.Event(),
    )
    assert result.outcome is InteractionOutcome.TIMEOUT
    cancelled = asyncio.Event()
    cancelled.set()
    result2 = await port.confirm_tool(
        _CALL, interaction_id="iy", verdict=_VERDICT, timeout_s=5, cancel=cancelled,
    )
    assert result2.outcome is InteractionOutcome.CANCELLED
    await t.aclose()


async def test_confirm_tool_disconnect_returns_disconnected_as_data() -> None:
    """Adjudicazione T4: su disconnect la conferma NON propaga l'eccezione,
    ritorna ``DISCONNECTED`` come DATO."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    port = _port(t)
    task = asyncio.create_task(port.confirm_tool(
        _CALL, interaction_id="ix", verdict=_VERDICT, timeout_s=5, cancel=asyncio.Event(),
    ))
    await _registered(t, "ix")
    await ws.disconnect()
    result = await asyncio.wait_for(task, timeout=1)
    assert result.outcome is InteractionOutcome.DISCONNECTED
    await t.aclose()


async def test_ask_user_and_client_parse_v2_response() -> None:
    """answers → testo via _format_answers; success/result/error →
    ToolExecutionOutput (string passthrough, dict/list json-dumped, error)."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    port = _port(t)
    call = ToolInvocation(
        call_id="exec-2", name="ask_user",
        args={"questions": [{"id": "q1", "text": "Quale?"}]}, raw_args="{}",
    )

    # ask_user: answers → testo formattato, nessun frame outbound.
    task = asyncio.create_task(
        port.ask_user(call, interaction_id="ia", timeout_s=2, cancel=asyncio.Event())
    )
    await _registered(t, "ia")
    await ws.feed({
        "type": "interaction.response", "interaction_id": "ia",
        "answers": [{"question_id": "q1", "selected": ["a"], "free_text": None}],
    })
    out = await asyncio.wait_for(task, timeout=1)
    assert out.ok is True and "q1" in out.content and "a" in out.content
    assert ws.sent == []

    # client tool: success + string result → passthrough.
    task = asyncio.create_task(
        port.run_client_tool(_CALL, interaction_id="ib", timeout_s=2, cancel=asyncio.Event())
    )
    await _registered(t, "ib")
    await ws.feed({
        "type": "interaction.response", "interaction_id": "ib",
        "success": True, "result": "fatto",
    })
    out = await asyncio.wait_for(task, timeout=1)
    assert out.ok is True and out.content == "fatto"

    # client tool: dict result → json dump.
    task = asyncio.create_task(
        port.run_client_tool(_CALL, interaction_id="ic", timeout_s=2, cancel=asyncio.Event())
    )
    await _registered(t, "ic")
    await ws.feed({
        "type": "interaction.response", "interaction_id": "ic",
        "success": True, "result": {"k": "v"},
    })
    out = await asyncio.wait_for(task, timeout=1)
    assert out.ok is True and '"k"' in out.content and '"v"' in out.content

    # client tool: error string.
    task = asyncio.create_task(
        port.run_client_tool(_CALL, interaction_id="id", timeout_s=2, cancel=asyncio.Event())
    )
    await _registered(t, "id")
    await ws.feed({
        "type": "interaction.response", "interaction_id": "id",
        "success": False, "error": "boom",
    })
    out = await asyncio.wait_for(task, timeout=1)
    assert out.ok is False and out.error == "boom"
    await t.aclose()


async def test_client_and_ask_user_propagate_disconnect() -> None:
    """run_client_tool/ask_user PROPAGANO ``EngineDisconnected`` (il loro tipo
    di ritorno non può codificarla — §6.5)."""
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    port = _port(t)
    task = asyncio.create_task(
        port.run_client_tool(_CALL, interaction_id="ix", timeout_s=5, cancel=asyncio.Event())
    )
    await _registered(t, "ix")
    await ws.disconnect()
    with pytest.raises(EngineDisconnected):
        await asyncio.wait_for(task, timeout=1)


async def test_ask_user_timeout_returns_interrupted_output() -> None:
    ws = FakeWebSocket()
    t = WsTransport(ws)
    t.begin_turn()
    await t.start()
    port = _port(t)
    call = ToolInvocation(call_id="exec-2", name="ask_user", args={}, raw_args="{}")
    out = await port.ask_user(call, interaction_id="ix", timeout_s=0.05, cancel=asyncio.Event())
    assert out.ok is False and out.error is not None
    await t.aclose()
