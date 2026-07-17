"""Unit del translator wire DEFINITIVO (``to_v2_frames``, adapter v2).

Value-pinned su OGNI classe di ``AgentEvent``: si costruisce l'evento con
valori pinnati e si asserisce il frame risultante CAMPO PER CAMPO (chiavi
``None`` OMESSE via ``exclude_none``, ``origin`` presente col default
``"agent"``, ``correlation_id`` assente). Ogni frame passa anche da
``validate_chat_server`` (garanzia by-construction ridondata a livello di
test). Chiude il debito M1 #6 (``ask_user``/interaction senza value-pin).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.api.ws_schema import validate_chat_server
from backend.services.agent import events as ev
from backend.services.agent.adapters.wire import normalize_questions, to_v2_frames
from backend.services.agent.models import ToolInvocation

_CALL = ToolInvocation(call_id="c1", name="read", args={"q": "x"}, raw_args='{"q":"x"}')


def _assert_valid(frames: list[dict[str, Any]]) -> None:
    """Ogni frame prodotto valida contro il contratto chat (guard strict)."""
    for frame in frames:
        validate_chat_server(frame)


def test_turn_started_frame() -> None:
    frames = to_v2_frames(
        ev.TurnStartedEvent(turn_id="t1", conversation_id="conv", source="chat")
    )
    assert frames == [{
        "type": "turn.started", "origin": "agent", "turn_id": "t1",
        "conversation_id": "conv", "source": "chat",
    }]
    _assert_valid(frames)


def test_turn_delta_text_frame() -> None:
    frames = to_v2_frames(
        ev.TurnDeltaEvent(turn_id="t1", step=1, kind="text", text="ciao")
    )
    assert frames == [{
        "type": "turn.delta", "origin": "agent", "turn_id": "t1", "step": 1,
        "kind": "text", "text": "ciao",
    }]
    _assert_valid(frames)


def test_turn_delta_thinking_frame() -> None:
    frames = to_v2_frames(
        ev.TurnDeltaEvent(turn_id="t1", step=2, kind="thinking", text="rifletto")
    )
    assert frames == [{
        "type": "turn.delta", "origin": "agent", "turn_id": "t1", "step": 2,
        "kind": "thinking", "text": "rifletto",
    }]
    _assert_valid(frames)


def test_llm_step_frame() -> None:
    frames = to_v2_frames(ev.LlmStepEvent(turn_id="t1", step=1))
    assert frames == [{
        "type": "turn.llm_step", "origin": "agent", "turn_id": "t1", "step": 1,
    }]
    _assert_valid(frames)


def test_tool_call_frame() -> None:
    frames = to_v2_frames(ev.ToolCallEvent(turn_id="t1", step=3, call=_CALL))
    assert frames == [{
        "type": "tool.call", "origin": "agent", "turn_id": "t1",
        "execution_id": "c1", "tool_name": "read", "args": {"q": "x"},
        "step": 3,
    }]
    _assert_valid(frames)


def test_tool_started_frame() -> None:
    frames = to_v2_frames(
        ev.ToolStartedEvent(turn_id="t1", call_id="c1", name="read")
    )
    assert frames == [{
        "type": "tool.started", "origin": "agent", "turn_id": "t1",
        "execution_id": "c1", "tool_name": "read",
    }]
    _assert_valid(frames)


def test_tool_progress_frame() -> None:
    frames = to_v2_frames(ev.ToolProgressEvent(
        turn_id="t1", call_id="c9", name="cad_generate_from_image",
        progress={"phase": "sampling", "percent": 50, "step": 7},
    ))
    assert frames == [{
        "type": "tool.progress", "origin": "agent", "turn_id": "t1",
        "execution_id": "c9", "tool_name": "cad_generate_from_image",
        "progress": {"phase": "sampling", "percent": 50, "step": 7},
    }]
    _assert_valid(frames)


def test_tool_result_frame() -> None:
    """Esempio obbligatorio del piano: tool.result denied (``success`` False
    resta fino alla purga del Task 10; ``result`` è il corpo COMPLETO)."""
    frames = to_v2_frames(ev.ToolResultEvent(
        turn_id="t1", call_id="c1", name="web_search", status="denied",
        result="Chiamata negata: plan tier.", artifact_id=None,
    ))
    assert frames == [{
        "type": "tool.result", "origin": "agent", "turn_id": "t1",
        "execution_id": "c1", "tool_name": "web_search", "status": "denied",
        "success": False,  # presente fino alla purga (Task 10 lo rimuove)
        "result": "Chiamata negata: plan tier.",
    }]
    _assert_valid(frames)


def test_tool_result_ok_with_artifact_and_content_type() -> None:
    frames = to_v2_frames(ev.ToolResultEvent(
        turn_id="t1", call_id="c1", name="cad", status="ok",
        result="art", artifact_id="art-1", content_type="model/gltf-binary",
    ))
    assert frames == [{
        "type": "tool.result", "origin": "agent", "turn_id": "t1",
        "execution_id": "c1", "tool_name": "cad", "status": "ok",
        "success": True, "result": "art", "content_type": "model/gltf-binary",
        "artifact_id": "art-1",
    }]
    _assert_valid(frames)


def test_interaction_requested_confirm_value_pinned() -> None:
    frames = to_v2_frames(ev.InteractionRequestedEvent(
        turn_id="t1", interaction_id="i1", kind="confirm", call_id="c1",
        tool_name="read",
        payload={
            "args": {"path": "/x"}, "risk_level": "medium",
            "description": "Scrive un file", "reasoning": "Serve per il task",
            "allow_remember": True,
        },
    ))
    assert frames == [{
        "type": "interaction.requested", "origin": "agent", "turn_id": "t1",
        "interaction_id": "i1", "execution_id": "c1", "kind": "tool_confirmation",
        "tool_name": "read", "args": {"path": "/x"}, "risk_level": "medium",
        "description": "Scrive un file", "reasoning": "Serve per il task",
        "allow_remember": True,
    }]
    _assert_valid(frames)


def test_interaction_requested_ask_user_value_pinned() -> None:
    """Esempio obbligatorio del piano: le questions raw sono normalizzate
    alla forma del contratto (chiavi estranee filtrate, default riempiti)."""
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
    _assert_valid(frames)


def test_interaction_requested_client_value_pinned() -> None:
    frames = to_v2_frames(ev.InteractionRequestedEvent(
        turn_id="t1", interaction_id="i1", kind="client", call_id="c1",
        tool_name="ui_pick", payload={"args": {"choice": 1}},
    ))
    assert frames == [{
        "type": "interaction.requested", "origin": "agent", "turn_id": "t1",
        "interaction_id": "i1", "execution_id": "c1", "kind": "client_tool_call",
        "tool_name": "ui_pick", "args": {"choice": 1},
    }]
    _assert_valid(frames)


def test_interaction_requested_unmapped_kind_raises() -> None:
    """Lookup kind STRICT: un kind interno non mappato deve fallire FORTE
    (KeyError) alla traduzione, non produrre un frame fuori vocabolario che
    l'EventPort scarterebbe lasciando il motore appeso."""
    event = ev.InteractionRequestedEvent(
        turn_id="t1", interaction_id="i1", kind="nuovo_kind", call_id="c1",
        payload={},
    )
    with pytest.raises(KeyError):
        to_v2_frames(event)


def test_interaction_resolved_frame() -> None:
    frames = to_v2_frames(ev.InteractionResolvedEvent(
        turn_id="t1", interaction_id="i1", kind="confirm", call_id="c1",
        outcome="approved",
    ))
    assert frames == [{
        "type": "interaction.resolved", "origin": "agent", "turn_id": "t1",
        "interaction_id": "i1", "execution_id": "c1", "kind": "tool_confirmation",
        "outcome": "approved",
    }]
    _assert_valid(frames)


def test_context_usage_frame_percentage_is_fraction() -> None:
    frames = to_v2_frames(
        ev.ContextUsageEvent(turn_id="t1", tokens=1000, context_window=32768)
    )
    assert frames == [{
        "type": "context.usage", "origin": "agent", "turn_id": "t1",
        "used": 1000, "available": 31768, "context_window": 32768,
        "percentage": 0.0305, "was_compressed": False,
        "messages_summarized": 0, "is_estimated": True,
    }]
    _assert_valid(frames)


def test_compaction_started_frame() -> None:
    frames = to_v2_frames(ev.CompactionEvent(
        turn_id="t1", phase="started", tokens_before=None, tokens_after=None,
        error=None,
    ))
    assert frames == [{
        "type": "context.compaction", "origin": "agent", "turn_id": "t1",
        "phase": "started",
    }]
    _assert_valid(frames)


def test_compaction_done_frame() -> None:
    frames = to_v2_frames(ev.CompactionEvent(
        turn_id="t1", phase="done", tokens_before=1000, tokens_after=500,
        error=None,
    ))
    assert frames == [{
        "type": "context.compaction", "origin": "agent", "turn_id": "t1",
        "phase": "done", "tokens_before": 1000, "tokens_after": 500,
    }]
    _assert_valid(frames)


def test_compaction_failed_frame() -> None:
    frames = to_v2_frames(ev.CompactionEvent(
        turn_id="t1", phase="failed", tokens_before=None, tokens_after=None,
        error="boom",
    ))
    assert frames == [{
        "type": "context.compaction", "origin": "agent", "turn_id": "t1",
        "phase": "failed", "error": "boom",
    }]
    _assert_valid(frames)


def test_turn_warning_frame() -> None:
    frames = to_v2_frames(
        ev.TurnWarningEvent(turn_id="t1", code="max_steps", message="attenzione")
    )
    assert frames == [{
        "type": "turn.warning", "origin": "agent", "turn_id": "t1",
        "code": "max_steps", "message": "attenzione",
    }]
    _assert_valid(frames)


def test_turn_error_frame() -> None:
    frames = to_v2_frames(
        ev.TurnErrorEvent(turn_id="t1", code="engine_error", message="errore")
    )
    assert frames == [{
        "type": "turn.error", "origin": "agent", "turn_id": "t1",
        "code": "engine_error", "message": "errore",
    }]
    _assert_valid(frames)


def test_turn_usage_frame_carries_cost() -> None:
    frames = to_v2_frames(ev.TurnUsageEvent(
        turn_id="t1", step=1, input_tokens=10, output_tokens=5, cost=0.01,
        tool_calls=1, max_steps=8,
    ))
    assert frames == [{
        "type": "turn.usage", "origin": "agent", "turn_id": "t1", "step": 1,
        "input_tokens": 10, "output_tokens": 5, "cost": 0.01, "tool_calls": 1,
        "max_steps": 8,
    }]
    _assert_valid(frames)


def test_turn_finished_frame_full() -> None:
    frames = to_v2_frames(ev.TurnFinishedEvent(
        turn_id="t1", finish_reason="stop", conversation_id="conv",
        final_message_id="m1", user_message_id="u1", version_group_id="vg",
        version_index=0, steps=2, tool_calls=1,
        input_tokens=30, output_tokens=8, cost=0.02,
    ))
    assert frames == [{
        "type": "turn.finished", "origin": "agent", "turn_id": "t1",
        "finish_reason": "stop", "conversation_id": "conv", "message_id": "m1",
        "user_message_id": "u1", "version_group_id": "vg", "version_index": 0,
        "steps": 2, "tool_calls": 1, "input_tokens": 30, "output_tokens": 8,
        "cost": 0.02,
    }]
    _assert_valid(frames)


def test_turn_finished_frame_empty_message_id_when_no_final_message() -> None:
    """``final_message_id`` None → ``message_id`` = "" (nessun msg finale)."""
    frames = to_v2_frames(ev.TurnFinishedEvent(
        turn_id="t1", finish_reason="tool_calls", conversation_id="conv",
        final_message_id=None, user_message_id=None, version_group_id=None,
        version_index=0, steps=1, tool_calls=1,
        input_tokens=10, output_tokens=2, cost=0.0,
    ))
    assert frames == [{
        "type": "turn.finished", "origin": "agent", "turn_id": "t1",
        "finish_reason": "tool_calls", "conversation_id": "conv",
        "message_id": "", "version_index": 0, "steps": 1, "tool_calls": 1,
        "input_tokens": 10, "output_tokens": 2, "cost": 0.0,
    }]
    _assert_valid(frames)


def test_raw_tool_call_delta_produces_no_frame() -> None:
    """Il diagnostico Mossa 1 non ha frame v2 (muore nel Task 10)."""
    frames = to_v2_frames(ev.RawToolCallDeltaEvent(
        turn_id="t1",
        payload={"id": "call_1", "function": {"name": "read", "arguments": "{}"}},
    ))
    assert frames == []


def test_normalize_questions_filters_and_defaults() -> None:
    """Chiavi estranee filtrate; default riempiti; type non valido → radio;
    id/text mancanti → fallback; non-dict/non-list scartati."""
    out = normalize_questions([
        {"id": "q1", "text": "A?", "type": "checkbox", "options": ["x", 1],
         "allow_free_text": True, "junk": "drop"},
        {"type": "weird"},   # id/text/options mancanti, type non valido
        "not-a-dict",        # scartato
    ])
    assert out == [
        {"id": "q1", "text": "A?", "type": "checkbox", "options": ["x", "1"],
         "allow_free_text": True},
        {"id": "q2", "text": "", "type": "radio", "options": [],
         "allow_free_text": False},
    ]


def test_normalize_questions_non_list_is_empty() -> None:
    assert normalize_questions(None) == []
    assert normalize_questions("nope") == []
