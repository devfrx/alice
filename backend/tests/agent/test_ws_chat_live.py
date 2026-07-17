"""Test WS live end-to-end del percorso completo /api/ws/chat (carry #5 addendum M1).

Boot dell'app di test (lifespan via la fixture ``app`` di ``tests/conftest.py``),
LLM scriptato, socket WS REALE (``starlette.testclient.TestClient``): esercita
``WsTransport`` (read-pump), ``run_agent_turn``, ``_persist_final_turn`` e il DB.

È il sismografo del cambio contratto della Mossa 2: i task 7-9 lo aggiornano
deliberatamente al vocabolario v2 — quando lo fanno, questo file è IL posto
dove il diff del wire deve saltare all'occhio.

Stato al Task 7 (wire v2 switch): il MOTORE emette ora SOLO frame v2
(``turn.delta`` al posto di ``token``, niente ``llm_requery``, niente
``tool_execution_*``), mentre ``done``/``context_info``/compressione arrivano
ANCORA dal persist path legacy (fino al Task 9). Le richieste interattive
legacy restano su ``WsInteractionPort`` (Task 8).
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
    """Turno di solo testo: pin dell'ordine dei frame salienti sul wire v2.

    Il motore emette ``turn.delta`` (non più ``token``); ``done`` è ancora del
    persist path legacy (Task 9 lo sostituirà con ``turn.finished`` come frame
    finale)."""
    ctx = app.state.context
    ctx.llm_service = ScriptedLLMShim([
        {"type": "token", "content": "Ciao dal wire live."},
        {"type": "usage", "input_tokens": 12, "output_tokens": 6, "cost": 0.0},
        {"type": "done", "finish_reason": "stop"},
    ])
    client = TestClient(app)
    with client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json({"content": "ciao"})
        frames = _drain_until(ws, "done")

    types = [f["type"] for f in frames]
    # Ordine saliente del wire v2: il turno apre con turn.started, ogni step
    # annuncia turn.llm_step, il testo streamma via turn.delta (NON più token),
    # lo usage per-step arriva, turn.finished chiude il motore, done chiude
    # ancora il persist path legacy.
    assert types.index("turn.started") < types.index("turn.llm_step")
    assert "token" not in types  # vocabolario legacy morto sul motore
    assert "turn.delta" in types
    assert "turn.usage" in types
    assert types.index("turn.finished") < types.index("done")
    # Il testo streammato arriva nel/nei turn.delta (kind=text).
    text = "".join(
        f["text"] for f in frames
        if f["type"] == "turn.delta" and f["kind"] == "text"
    )
    assert text == "Ciao dal wire live."
    done = frames[-1]
    assert done["finish_reason"] == "stop"
    assert done["conversation_id"]
    assert done["message_id"]  # messaggio assistant persistito
    assert ctx.llm_service.chat_calls == 1


def test_tool_step_turn_wire_sequence(app: FastAPI) -> None:
    """Turno con tool call verso un tool sconosciuto: esercita il gate, la
    tool response sintetica (§6.1.1), il secondo step e la persistenza."""
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
        frames = _drain_until(ws, "done")

    types = [f["type"] for f in frames]
    assert "tool.call" in types
    assert "tool.result" in types
    tool_result = next(f for f in frames if f["type"] == "tool.result")
    assert tool_result["execution_id"] == "call_live_1"
    # Tool response sintetica (§6.1.1): status v2 e corpo COMPLETO sul wire.
    assert tool_result["status"] == "unknown_tool"
    assert tool_result["result"] == "Tool sconosciuto: tool_inesistente."
    # Vocabolario legacy morto sul motore: niente più llm_requery né
    # tool_execution_start/done nello stream v2.
    assert "llm_requery" not in types
    assert "tool_execution_start" not in types
    assert "tool_execution_done" not in types
    assert frames[-1]["finish_reason"] == "stop"
    assert ctx.llm_service.chat_calls == 2
