"""Unit del translator wire (``to_wire_frames``, adapter di parità).

Ogni ``AgentEvent`` prodotto dal motore deve tradursi in frame che validano il
contratto chat attuale (``validate_chat_server``). Il translator resta in
produzione fino a fine Mossa 2 (poi il motore emette il vocabolario canonico
direttamente); questi test lo pinnano.

Nota storica: questo file conteneva anche un harness end-to-end v1-vs-v2 (Parte
B) che dimostrava l'equivalenza sul wire tra il ``DirectTurnExecutor`` legacy e
l'``AgentEngine``. Con la demolizione di ``services/turn`` (Task 19) quel
compito è concluso — v1 non esiste più — e l'harness è stato rimosso. Restano
qui le sole unit del translator (ex Parte A).
"""

from __future__ import annotations

from backend.api.ws_schema import validate_chat_server
from backend.services.agent import events as ev
from backend.services.agent.adapters.parity import to_wire_frames
from backend.services.agent.models import ToolInvocation


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
        ev.ToolStartedEvent(turn_id="t", call_id="c1", name="read"),
        ev.ToolProgressEvent(
            turn_id="t", call_id="c1", name="read",
            progress={"phase": "run", "percent": 50.0},
        ),
        ev.ToolResultEvent(
            turn_id="t", call_id="c1", name="read", status="ok",
            content_preview="risultato", artifact_id=None,
            result="risultato", content_type="text/plain",
        ),
        ev.ToolResultEvent(
            turn_id="t", call_id="c1", name="cad", status="ok",
            content_preview="art", artifact_id="art-1",
            result="art", content_type="model/gltf-binary",
        ),
        ev.InteractionRequestedEvent(
            turn_id="t", interaction_id="i1", kind="confirm", call_id="c1",
            payload={"outcome": "ask", "risk_level": "medium", "description": "d"},
            tool_name="read",
        ),
        ev.InteractionResolvedEvent(
            turn_id="t", interaction_id="i1", kind="confirm", call_id="c1",
            outcome="approved",
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
        ev.TurnUsageEvent(
            turn_id="t", step=1, input_tokens=10, output_tokens=5, cost=0.01,
            tool_calls=1, max_steps=8,
        ),
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


def test_tool_progress_carries_real_name_and_nested_payload() -> None:
    """ToolProgressEvent → frame tool_progress con tool_name reale + payload annidato."""
    e = ev.ToolProgressEvent(
        turn_id="t", call_id="c9", name="cad_generate_from_image",
        progress={"phase": "sampling", "percent": 50, "step": 7},
    )
    frame = to_wire_frames(e)[0]
    assert frame["type"] == "tool_progress"
    assert frame["tool_name"] == "cad_generate_from_image"
    assert frame["execution_id"] == "c9"
    # il payload del tool viene appiattito nel frame (chiavi best-effort)
    assert frame["phase"] == "sampling"
    assert frame["percent"] == 50
    assert frame["step"] == 7


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
