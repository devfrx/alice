"""Contract tests: chat-channel WS frames validate against ws_schema.

Representative frames copied VERBATIM from the emit sites (llm_service
stream forwarding, tool_loop/pipeline, chat _persist/_assembly, turn
events builders, reflective executor, interaction channel).
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
    "token",
    "thinking",
    "tool_call",
    "done",
    "error",
    "tool_execution_start",
    "tool_execution_done",
    "tool_progress",
    "context_info",
    "context_compression_start",
    "context_compression_done",
    "context_compression_failed",
    "llm_requery",
    "warning",
    "tool_confirmation_required",
    "client_tool_call",
    "ask_user_required",
    "turn.started",
    "turn.llm_step",
    "tool.call",
    "tool.result",
    "interaction.requested",
    "interaction.resolved",
    "turn.usage",
    "turn.finished",
    "agent.critic_invoked",
    "agent.warning",
})

EXPECTED_CHAT_CLIENT_TYPES = frozenset({
    "cancel",
    "tool_confirmation_response",
    "client_tool_result",
    "ask_user_response",
})

REPRESENTATIVE_SERVER_FRAMES: list[dict[str, Any]] = [
    {"type": "token", "content": "ciao"},
    {"type": "thinking", "content": "hmm"},
    {
        "type": "tool_call",
        "id": "call_1",
        "function": {"name": "web_search", "arguments": "{\"q\": \"x\"}"},
    },
    {
        "type": "done",
        "conversation_id": "c1",
        "message_id": "m2",
        "user_message_id": "m1",
        "finish_reason": "stop",
        "version_group_id": None,
        "version_index": 0,
    },
    {"type": "error", "content": "boom"},
    {"type": "tool_execution_start", "tool_name": "web_search", "execution_id": "e1"},
    {
        "type": "tool_execution_done",
        "tool_name": "web_search",
        "result": "ok",
        "execution_id": "e1",
        "success": True,
    },
    {
        "type": "tool_progress",
        "tool_name": "cad_generate",
        "execution_id": "e1",
        "phase": "sampling",
        "step": 3,
        "total": 10,
    },
    {
        "type": "context_info",
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
        "type": "context_info",
        "used": 1,
        "available": 2,
        "context_window": 3,
        "percentage": 0.5,
        "was_compressed": True,
        "messages_summarized": 4,
        "is_estimated": False,
        "breakdown": None,
    },
    {"type": "context_compression_start"},
    {"type": "context_compression_done", "messages_summarized": 4},
    {"type": "context_compression_done", "messages_summarized": 4, "summary_message_id": "m9"},
    {"type": "context_compression_failed"},
    {"type": "llm_requery", "iteration": 2},
    {"type": "warning", "content": "budget exceeded"},
    {
        "type": "tool_confirmation_required",
        "execution_id": "e1",
        "tool_name": "write_file",
        "args": {"path": "x"},
        "risk_level": "medium",
        "description": "Writes a file",
        "reasoning": None,
        "allow_remember": True,
    },
    {"type": "client_tool_call", "execution_id": "e1", "tool_name": "ui_tool", "args": {}},
    {
        "type": "ask_user_required",
        "execution_id": "e1",
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
    {"type": "turn.started", "turn_id": "t1", "conversation_id": "c1"},
    {"type": "turn.llm_step", "turn_id": "t1", "step": 1},
    {
        "type": "tool.call",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "web_search",
        "args": {"q": "x"},
    },
    {
        "type": "tool.result",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "web_search",
        "success": True,
        "result": "ok",
    },
    {
        "type": "interaction.requested",
        "turn_id": "t1",
        "execution_id": "e1",
        "kind": "tool_confirmation",
        "tool_name": "write_file",
    },
    {
        "type": "interaction.resolved",
        "turn_id": "t1",
        "execution_id": "e1",
        "kind": "client_tool_call",
        "outcome": "failed",
    },
    {
        "type": "turn.usage",
        "turn_id": "t1",
        "step": 1,
        "input_tokens": 10,
        "output_tokens": 5,
        "tool_calls": 1,
        "max_steps": 24,
    },
    {
        "type": "turn.finished",
        "turn_id": "t1",
        "finish_reason": None,
        "input_tokens": 10,
        "output_tokens": 5,
        "steps": 1,
    },
    {"type": "agent.critic_invoked", "run_id": None, "step_index": 0, "source": "llm"},
    {"type": "agent.warning", "run_id": None, "code": "degenerated_output", "message": "..."},
]

REPRESENTATIVE_CLIENT_FRAMES: list[dict[str, Any]] = [
    {"type": "cancel"},
    {"type": "tool_confirmation_response", "execution_id": "e1", "approved": True},
    {
        "type": "tool_confirmation_response",
        "execution_id": "e1",
        "approved": True,
        "remember": "session",
    },
    {"type": "client_tool_result", "execution_id": "e1", "success": True, "result": "ok"},
    {"type": "client_tool_result", "execution_id": "e1", "success": False, "error": "nope"},
    {
        "type": "ask_user_response",
        "execution_id": "e1",
        "answers": [{"question_id": "q1", "selected": ["a"], "free_text": ""}],
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
