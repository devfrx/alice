"""Contract tests: events-channel WS frames validate against ws_schema.

The representative frames below are copied VERBATIM from the emit sites
(app.py lifespan bridges, service callbacks, terminal manager, calendar
and config routes). If one stops validating, either the emitter drifted
(fix the emitter) or the contract changed intentionally (update model,
frame here, and the frozen vocabulary).
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.api.ws_schema import (
    EVENTS_CLIENT_TYPES,
    EVENTS_SERVER_TYPES,
    validate_events_client,
    validate_events_server,
)
from pydantic import ValidationError

EXPECTED_EVENTS_SERVER_TYPES = frozenset({
    "pong",
    "heartbeat",
    "mcp.server.connected",
    "mcp.server.disconnected",
    "email.received",
    "email.sent",
    "note.created",
    "note.updated",
    "note.deleted",
    "service.status",
    "service.model_download_progress",
    "knowledge.status",
    "artifact.created",
    "tasks.updated",
    "plan_document.updated",
    "scope.updated",
    "permission_mode.updated",
    "calendar.changed",
    "config.changed",
    "terminal.session_opened",
    "terminal.output",
    "terminal.closed",
    "terminal.renamed",
    "terminal.assigned",
})

EXPECTED_EVENTS_CLIENT_TYPES = frozenset({
    "ping",
    "terminal.input",
    "terminal.resize",
})

REPRESENTATIVE_SERVER_FRAMES: list[dict[str, Any]] = [
    {"type": "pong"},
    {"type": "heartbeat"},
    {"type": "mcp.server.connected", "server": "fs"},
    {"type": "mcp.server.disconnected", "server": "fs", "reason": "eof"},
    {"type": "email.received", "folder": "INBOX"},
    {"type": "email.sent", "message_id": "abc"},
    {"type": "note.created", "note_id": "n1", "title": "t"},
    {"type": "note.updated", "note_id": "n1"},
    {"type": "note.deleted", "note_id": "n1"},
    {
        "type": "service.status",
        "service": "qdrant",
        "status": "ready",
        "detail": None,
        "timestamp": 1718000000.0,
    },
    {
        "type": "service.model_download_progress",
        "service": "stt",
        "model_id": "whisper-small",
        "downloaded_bytes": 10,
        "total_bytes": 100,
        "phase": "downloading",
        "file": "model.bin",
    },
    {
        "type": "knowledge.status",
        "ready": True,
        "reason": None,
        "memory_enabled": True,
        "tool_rag_enabled": False,
    },
    {
        "type": "artifact.created",
        "artifact_id": "a1",
        "kind": "cad_3d_text",
        "conversation_id": "c1",
        "title": "tiny cube",
    },
    {
        "type": "tasks.updated",
        "conversation_id": "c1",
        "steps": [{"step": "do x", "status": "pending"}],
    },
    {
        "type": "plan_document.updated",
        "conversation_id": "c1",
        "title": "",
        "body": "",
        "updated_at": None,
    },
    {"type": "scope.updated", "conversation_id": "c1", "folders": ["C:/ws"]},
    {"type": "permission_mode.updated", "conversation_id": "c1", "mode": "strict"},
    {"type": "calendar.changed", "action": "created", "event_id": "e1"},
    {"type": "config.changed", "path": "llm.temperature", "value": 0.2, "layer": "user"},
    {
        "type": "terminal.session_opened",
        "conversation_id": "c1",
        "session": {
            "id": "s1",
            "conversation_id": "c1",
            "title": "shell",
            "cwd": "C:/ws",
            "rows": 24,
            "cols": 80,
            "agent_assigned": False,
            "created_at": "2026-06-11T00:00:00",
            "pid": 1234,
            "alive": True,
        },
    },
    {"type": "terminal.output", "conversation_id": "c1", "session_id": "s1", "data": "$ "},
    {"type": "terminal.closed", "conversation_id": "c1", "session_id": "s1", "exit_code": None},
    {"type": "terminal.renamed", "conversation_id": "c1", "session_id": "s1", "title": "t"},
    {"type": "terminal.assigned", "conversation_id": "c1", "session_id": "s1"},
]

REPRESENTATIVE_CLIENT_FRAMES: list[dict[str, Any]] = [
    {"type": "ping"},
    {"type": "terminal.input", "conversation_id": "c1", "session_id": "s1", "data": "ls\r"},
    {
        "type": "terminal.resize",
        "conversation_id": "c1",
        "session_id": "s1",
        "rows": 40,
        "cols": 120,
    },
]


def test_events_server_vocabulary_is_frozen() -> None:
    """Adding/removing a frame type must be a conscious, reviewed change."""
    assert EVENTS_SERVER_TYPES == EXPECTED_EVENTS_SERVER_TYPES


def test_events_client_vocabulary_is_frozen() -> None:
    assert EVENTS_CLIENT_TYPES == EXPECTED_EVENTS_CLIENT_TYPES


@pytest.mark.parametrize(
    "frame", REPRESENTATIVE_SERVER_FRAMES, ids=lambda f: str(f["type"]),
)
def test_representative_server_frames_validate(frame: dict[str, Any]) -> None:
    validate_events_server(frame)


@pytest.mark.parametrize(
    "frame", REPRESENTATIVE_CLIENT_FRAMES, ids=lambda f: str(f["type"]),
)
def test_representative_client_frames_validate(frame: dict[str, Any]) -> None:
    validate_events_client(frame)


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_events_server({"type": "no.such.event"})


def test_extra_field_is_rejected() -> None:
    """extra='forbid' makes silent payload drift loud."""
    with pytest.raises(ValidationError):
        validate_events_server({"type": "pong", "surprise": 1})


def test_mode_literal_matches_enum() -> None:
    """The WS Literal must track the PermissionMode enum exactly."""
    import typing

    from backend.api.ws_schema.events import WsPermissionModeUpdated
    from backend.services.permission_mode_service import PermissionMode

    literal = WsPermissionModeUpdated.model_fields["mode"].annotation
    assert set(typing.get_args(literal)) == {m.value for m in PermissionMode}
