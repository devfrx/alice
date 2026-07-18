"""Test WS live end-to-end del percorso completo /api/ws/chat (carry #5 addendum M1).

Boot dell'app di test (lifespan via la fixture ``app`` di ``tests/conftest.py``),
LLM scriptato, socket WS REALE (``starlette.testclient.TestClient``): esercita
``WsTransport`` (read-pump), ``run_agent_turn``, ``_persist_final_turn`` e il DB.

È il sismografo del cambio contratto della Mossa 2. Stato al Task 9 (stream
unico): il canale chat parla SOLO il vocabolario v2. Il MOTORE emette i fatti
del turno (``turn.started``/``turn.delta``/``turn.usage``/``turn.finished``,
``tool.call``/``tool.result``); il persist path emette gli ultimi frame di
manutenzione (``context.usage``) attraverso lo STESSO trasporto. ``done``,
``context_info`` e ``error`` legacy sono MORTI: il frame finale del turno è
``turn.finished``.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.tests.agent._llm_shim import ScriptedLLMShim


def _drain_until(ws: Any, terminal_type: str, limit: int = 200) -> list[dict[str, Any]]:
    """Riceve frame finché arriva ``terminal_type`` (o esplode il limite)."""
    frames: list[dict[str, Any]] = []
    for _ in range(limit):
        frame = ws.receive_json()
        frames.append(frame)
        if frame.get("type") == terminal_type:
            return frames
    raise AssertionError(f"terminal frame {terminal_type!r} mai arrivato: {frames}")


def test_text_turn_full_wire_sequence(app: FastAPI) -> None:
    """Turno di solo testo: il turno chiude con ``turn.finished`` (nessun
    ``done``). Il ``context.usage`` reale post-turno arriva DOPO
    ``turn.finished`` — si drena fino al terminale e si asserisce sul prefisso.
    """
    ctx = app.state.context
    ctx.llm_service = ScriptedLLMShim([
        {"type": "token", "content": "Ciao dal wire live."},
        {"type": "usage", "input_tokens": 12, "output_tokens": 6, "cost": 0.0},
        {"type": "done", "finish_reason": "stop"},
    ])
    client = TestClient(app)
    with client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json({"content": "ciao"})
        frames = _drain_until(ws, "turn.finished")

    types = [f["type"] for f in frames]
    # Vocabolario legacy MORTO: nessun done/context_info/error sul canale.
    assert "done" not in types
    assert "context_info" not in types
    assert "error" not in types
    assert "token" not in types  # motore emette turn.delta
    # Ordine saliente del wire v2.
    assert types.index("turn.started") < types.index("turn.llm_step")
    assert "turn.delta" in types
    assert "turn.usage" in types
    # Il testo streammato arriva nel/nei turn.delta (kind=text).
    text = "".join(
        f["text"] for f in frames
        if f["type"] == "turn.delta" and f["kind"] == "text"
    )
    assert text == "Ciao dal wire live."
    # turn.finished è il frame finale del turno: id valorizzati.
    finished = frames[-1]
    assert finished["type"] == "turn.finished"
    assert finished["finish_reason"] == "stop"
    assert finished["conversation_id"]
    assert finished["message_id"]  # messaggio assistant persistito
    assert "user_message_id" in finished
    assert ctx.llm_service.chat_calls == 1


def test_tool_step_turn_wire_sequence(app: FastAPI) -> None:
    """Turno con tool call verso un tool sconosciuto: esercita il gate, la
    tool response sintetica (§6.1.1), il secondo step e la persistenza. Chiude
    con ``turn.finished`` (nessun ``done``)."""
    ctx = app.state.context
    ctx.llm_service = ScriptedLLMShim([
        # step 1: il modello chiama un tool inesistente. Formato chunk
        # verificato contro backend/services/agent/adapters/llm.py: una
        # tool-call GIA COMPLETA per chunk (non un delta incrementale).
        [
            {
                "type": "tool_call",
                "id": "call_live_1",
                "function": {"name": "tool_inesistente", "arguments": "{}"},
            },
            {"type": "usage", "input_tokens": 10, "output_tokens": 4, "cost": 0.0},
            {"type": "done", "finish_reason": "tool_calls"},
        ],
        # step 2: risposta finale, dopo la tool response sintetica.
        [
            {"type": "token", "content": "Fatto."},
            {"type": "usage", "input_tokens": 20, "output_tokens": 3, "cost": 0.0},
            {"type": "done", "finish_reason": "stop"},
        ],
    ])
    client = TestClient(app)
    with client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json({"content": "usa il tool"})
        frames = _drain_until(ws, "turn.finished")

    types = [f["type"] for f in frames]
    assert "tool.call" in types
    assert "tool.result" in types
    tool_result = next(f for f in frames if f["type"] == "tool.result")
    assert tool_result["execution_id"] == "call_live_1"
    # Tool response sintetica (§6.1.1): status v2 e corpo COMPLETO sul wire.
    assert tool_result["status"] == "unknown_tool"
    assert tool_result["result"] == "Tool sconosciuto: tool_inesistente."
    # Vocabolario legacy morto su TUTTO il canale (motore + persist path).
    assert "llm_requery" not in types
    assert "tool_execution_start" not in types
    assert "tool_execution_done" not in types
    assert "done" not in types
    assert frames[-1]["type"] == "turn.finished"
    assert frames[-1]["finish_reason"] == "stop"
    assert ctx.llm_service.chat_calls == 2


def test_empty_message_emits_turn_error(app: FastAPI) -> None:
    """Messaggio vuoto: errore di validazione pre-turno → ``turn.error`` con
    ``code`` = ``empty_message`` e nessun ``turn_id`` (errore pre-turno)."""
    ctx = app.state.context
    ctx.llm_service = ScriptedLLMShim([
        {"type": "token", "content": "mai raggiunto"},
        {"type": "done", "finish_reason": "stop"},
    ])
    client = TestClient(app)
    with client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json({"content": ""})
        frame = ws.receive_json()

    assert frame["type"] == "turn.error"
    assert frame["code"] == "empty_message"
    assert "turn_id" not in frame  # errore pre-turno: turn_id assente
