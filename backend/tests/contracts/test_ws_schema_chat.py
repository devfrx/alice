"""Contract tests: chat-channel WS frames validate against ws_schema.

Representative frames copied VERBATIM from the emit sites: the v2 AgentEngine's
WS adapter (``services/agent/adapters/wire.py``, which builds every turn-fact
frame through its Pydantic model) and chat ``_persist``/``_assembly`` (typed
conversation-maintenance frames on the same transport). The chat channel speaks
ONLY the canonical v2 vocabulary since Mossa 2 Task 10: legacy and diagnostic
frames are gone from the contract.
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.api.ws_schema import (
    CHAT_CLIENT_TYPES,
    CHAT_SERVER_TYPES,
    validate_chat_client,
    validate_chat_server,
)
from pydantic import ValidationError

EXPECTED_CHAT_SERVER_TYPES = frozenset({
    "turn.started",
    "turn.delta",
    "turn.llm_step",
    "tool.call",
    "tool.started",
    "tool.progress",
    "tool.result",
    "interaction.requested",
    "interaction.resolved",
    "context.usage",
    "context.compaction",
    "turn.warning",
    "turn.error",
    "turn.usage",
    "turn.finished",
})

EXPECTED_CHAT_CLIENT_TYPES = frozenset({
    "cancel",
    "interaction.response",
})

REPRESENTATIVE_SERVER_FRAMES: list[dict[str, Any]] = [
    {"type": "turn.started", "turn_id": "t1", "conversation_id": "c1", "source": "chat"},
    {"type": "turn.delta", "turn_id": "t1", "step": 1, "kind": "text", "text": "ciao"},
    {"type": "turn.delta", "turn_id": "t1", "step": 1, "kind": "thinking", "text": "hmm"},
    {"type": "turn.llm_step", "turn_id": "t1", "step": 1},
    {
        "type": "tool.call",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "web_search",
        "args": {"q": "x"},
        "step": 1,
    },
    {"type": "tool.started", "turn_id": "t1", "execution_id": "e1", "tool_name": "web_search"},
    {
        "type": "tool.progress",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "cad_generate",
        "progress": {"phase": "sampling", "step": 3, "total": 10},
    },
    {
        "type": "tool.result",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "web_search",
        "status": "ok",
        "result": "ok",
    },
    {
        "type": "tool.result",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "cad_generate",
        "status": "ok",
        "result": "art",
        "content_type": "model/gltf-binary",
        "artifact_id": "art-1",
    },
    {
        "type": "interaction.requested",
        "turn_id": "t1",
        "interaction_id": "i1",
        "execution_id": "e1",
        "kind": "tool_confirmation",
        "tool_name": "write_file",
        "args": {"path": "x"},
        "risk_level": "medium",
        "description": "Writes a file",
        "reasoning": "user asked to save",
        "allow_remember": True,
    },
    {
        "type": "interaction.requested",
        "turn_id": "t1",
        "interaction_id": "i2",
        "execution_id": "e2",
        "kind": "ask_user",
        "questions": [
            {
                "id": "q1",
                "text": "Quale?",
                "type": "radio",
                "options": ["a", "b"],
                "allow_free_text": False,
            },
        ],
    },
    {
        "type": "interaction.resolved",
        "turn_id": "t1",
        "interaction_id": "i3",
        "execution_id": "e1",
        "kind": "client_tool_call",
        "outcome": "failed",
    },
    {
        "type": "context.usage",
        "turn_id": "t1",
        "used": 1000,
        "available": 7000,
        "context_window": 8192,
        "percentage": 0.12,
        "was_compressed": False,
        "messages_summarized": 0,
        "is_estimated": True,
        "breakdown": {
            "system": 1,
            "tools": 2,
            "messages": 3,
            "files": 0,
            "tool_results": 0,
            "other": 0,
        },
    },
    {
        "type": "context.usage",
        "used": 1,
        "available": 2,
        "context_window": 3,
        "percentage": 0.5,
    },
    {"type": "context.compaction", "turn_id": "t1", "phase": "started"},
    {
        "type": "context.compaction",
        "turn_id": "t1",
        "phase": "done",
        "messages_summarized": 4,
        "summary_message_id": "m9",
        "tokens_before": 4000,
        "tokens_after": 500,
    },
    {"type": "context.compaction", "turn_id": "t1", "phase": "failed", "error": "boom"},
    {"type": "turn.warning", "turn_id": "t1", "code": "max_steps", "message": "budget exceeded"},
    {"type": "turn.error", "turn_id": "t1", "code": "persist_failed", "message": "boom"},
    {"type": "turn.error", "turn_id": None, "code": "validation_failed", "message": "bad frame"},
    {
        "type": "turn.usage",
        "turn_id": "t1",
        "step": 1,
        "input_tokens": 10,
        "output_tokens": 5,
        "tool_calls": 1,
        "max_steps": 24,
        "cost": 0.0012,
    },
    {
        "type": "turn.finished",
        "turn_id": "t1",
        "finish_reason": "stop",
        "input_tokens": 10,
        "output_tokens": 5,
        "steps": 1,
        "cost": 0.0012,
        "conversation_id": "c1",
        "message_id": "m2",
        "user_message_id": "m1",
        "version_group_id": "vg1",
        "version_index": 0,
        "tool_calls": 1,
    },
]

REPRESENTATIVE_CLIENT_FRAMES: list[dict[str, Any]] = [
    {"type": "cancel"},
    {
        "type": "interaction.response",
        "interaction_id": "i1",
        "kind": "tool_confirmation",
        "approved": True,
        "remember": "session",
    },
    {
        "type": "interaction.response",
        "interaction_id": "i2",
        "kind": "ask_user",
        "answers": [{"question_id": "q1", "selected": ["a"], "free_text": ""}],
    },
    {
        "type": "interaction.response",
        "interaction_id": "i3",
        "kind": "client_tool_call",
        "success": True,
        "result": "ok",
    },
]


def test_chat_server_vocabulary_is_frozen() -> None:
    assert CHAT_SERVER_TYPES == EXPECTED_CHAT_SERVER_TYPES


def test_chat_client_vocabulary_is_frozen() -> None:
    assert CHAT_CLIENT_TYPES == EXPECTED_CHAT_CLIENT_TYPES


@pytest.mark.parametrize(
    "frame", REPRESENTATIVE_SERVER_FRAMES,
    ids=lambda f: f"{f['type']}-{REPRESENTATIVE_SERVER_FRAMES.index(f)}",
)
def test_representative_server_frames_validate(frame: dict[str, Any]) -> None:
    validate_chat_server(frame)


@pytest.mark.parametrize(
    "frame", REPRESENTATIVE_CLIENT_FRAMES,
    ids=lambda f: f"{f['type']}-{REPRESENTATIVE_CLIENT_FRAMES.index(f)}",
)
def test_representative_client_frames_validate(frame: dict[str, Any]) -> None:
    validate_chat_client(frame)


def test_user_message_has_no_type_discriminant() -> None:
    """A plain user message is the UNTAGGED chat frame (legacy wire shape)."""
    from backend.api.ws_schema.chat import WsUserMessage

    msg = WsUserMessage.model_validate({"content": "ciao", "conversation_id": "c1"})
    assert msg.content == "ciao"
    assert "type" not in WsUserMessage.model_fields


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


def test_unknown_chat_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_chat_server({"type": "usage", "input_tokens": 1, "output_tokens": 2})


def test_tool_result_rejects_removed_success_field() -> None:
    """The legacy ``success`` field is gone from ``tool.result`` (extra=forbid)."""
    with pytest.raises(ValidationError):
        validate_chat_server({
            "type": "tool.result",
            "turn_id": "t1",
            "execution_id": "e1",
            "tool_name": "web_search",
            "status": "ok",
            "result": "ok",
            "success": True,
        })
