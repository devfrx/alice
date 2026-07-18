"""Tests for the WebSocket chat endpoint ``/api/ws/chat`` (v2 wire).

The chat channel speaks the canonical v2 vocabulary: the engine streams
``turn.started`` / ``turn.llm_step`` / ``turn.delta`` / ``turn.usage`` and the
turn's final frame is ``turn.finished``; pre-turn validation failures surface
as ``turn.error`` (``code`` + ``message``, no ``turn_id``).  There is no more
``token`` / ``done`` / ``error``-with-``content`` legacy frame.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.tests.agent._llm_shim import ScriptedLLMShim

# ---------------------------------------------------------------------------
# Mock LLM helpers
# ---------------------------------------------------------------------------


def _patch_llm(app: FastAPI) -> None:
    """Replace the real LLM service on *app* with the scripted shim.

    The WHOLE service is swapped (same pattern as
    ``tests/agent/test_ws_chat_live.py``): partially patching the real
    ``LLMService`` instance leaves its live HTTP client/model-resolution
    paths in play, which proved slow and hang-prone on Windows CI runs
    (censused, Mossa 2 T9).
    """
    app.state.context.llm_service = ScriptedLLMShim([
        {"type": "token", "content": "Hello"},
        {"type": "token", "content": " world"},
        {"type": "done", "finish_reason": "stop"},
    ])


def _drain_until(
    ws: Any, terminal_type: str, limit: int = 200,
) -> list[dict[str, Any]]:
    """Receive frames until ``terminal_type`` arrives; return them all."""
    frames: list[dict[str, Any]] = []
    for _ in range(limit):
        frame = ws.receive_json()
        frames.append(frame)
        if frame.get("type") == terminal_type:
            return frames
    raise AssertionError(
        f"terminal frame {terminal_type!r} never arrived: {frames}"
    )


def _finished(ws: Any) -> dict[str, Any]:
    """Drain until the terminal ``turn.finished`` frame and return it."""
    return _drain_until(ws, "turn.finished")[-1]


def _delta_text(frames: list[dict[str, Any]]) -> str:
    """Concatenate the streamed ``turn.delta`` text (kind=text)."""
    return "".join(
        f["text"] for f in frames
        if f["type"] == "turn.delta" and f.get("kind") == "text"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ws_app(app: FastAPI) -> FastAPI:
    """Return the test app with a mocked LLM service."""
    _patch_llm(app)
    return app


# ---------------------------------------------------------------------------
# Tests — basic flow
# ---------------------------------------------------------------------------


class TestWebSocketBasicFlow:
    """Happy-path tests for the streaming chat WebSocket."""

    def test_ws_send_valid_message_streams_deltas(
        self, ws_app: FastAPI,
    ) -> None:
        """Send a message, expect turn.delta stream then turn.finished."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "Hi there"})
            frames = _drain_until(ws, "turn.finished")

        assert _delta_text(frames) == "Hello world"
        finished = frames[-1]
        assert finished["type"] == "turn.finished"
        assert "conversation_id" in finished
        assert finished["message_id"]

    def test_ws_finished_event_contains_valid_uuids(
        self, ws_app: FastAPI,
    ) -> None:
        """The turn.finished payload must carry valid UUID strings."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "test"})
            finished = _finished(ws)

        uuid.UUID(finished["conversation_id"])
        uuid.UUID(finished["message_id"])


# ---------------------------------------------------------------------------
# Tests — error handling
# ---------------------------------------------------------------------------


class TestWebSocketErrors:
    """Edge-case and error handling for the WebSocket endpoint."""

    def test_ws_invalid_json_dropped_then_next_message_processes(
        self, ws_app: FastAPI,
    ) -> None:
        """Malformed JSON is silently dropped by the transport pump; a
        subsequent valid message still processes normally (drop-and-continue).
        """
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_text("not json {{{")
            ws.send_json({"content": "Hi there"})
            finished = _finished(ws)
            assert finished["type"] == "turn.finished"

    def test_ws_empty_message_receives_turn_error(
        self, ws_app: FastAPI,
    ) -> None:
        """An empty ``content`` field should be rejected with turn.error."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": ""})
            resp = ws.receive_json()
            assert resp["type"] == "turn.error"
            assert resp["code"] == "empty_message"

    def test_ws_whitespace_only_message_receives_turn_error(
        self, ws_app: FastAPI,
    ) -> None:
        """A whitespace-only ``content`` should also be rejected."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "   "})
            resp = ws.receive_json()
            assert resp["type"] == "turn.error"
            assert resp["code"] == "empty_message"

    def test_ws_missing_content_field_receives_turn_error(
        self, ws_app: FastAPI,
    ) -> None:
        """Omitting ``content`` entirely should produce a turn.error."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"not_content": "oops"})
            resp = ws.receive_json()
            assert resp["type"] == "turn.error"
            assert resp["code"] == "empty_message"

    def test_ws_stale_interaction_response_does_not_poison_next_turn(
        self, ws_app: FastAPI,
    ) -> None:
        """A stale ``interaction.response`` (unknown interaction_id) is dropped
        by the transport pump and does not become an empty-message turn."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({
                "type": "interaction.response",
                "interaction_id": "stale",
                "kind": "tool_confirmation",
                "approved": True,
            })
            ws.send_json({"content": "Hi there"})

            frames = _drain_until(ws, "turn.finished")
            assert _delta_text(frames) == "Hello world"


# ---------------------------------------------------------------------------
# Tests — conversation management
# ---------------------------------------------------------------------------


class TestWebSocketConversations:
    """Tests verifying conversation creation / reuse via the WS endpoint."""

    def test_ws_no_conversation_id_creates_new_conversation(
        self, ws_app: FastAPI,
    ) -> None:
        """When no ``conversation_id`` is sent, a new one must be created."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "hello"})
            finished = _finished(ws)
            uuid.UUID(finished["conversation_id"])

    def test_ws_with_conversation_id_reuses_conversation(
        self, ws_app: FastAPI,
    ) -> None:
        """Providing a ``conversation_id`` must reuse that conversation."""
        cid = str(uuid.uuid4())
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "first", "conversation_id": cid})
            finished1 = _finished(ws)
            assert finished1["conversation_id"] == cid

            ws.send_json({"content": "second", "conversation_id": cid})
            finished2 = _finished(ws)
            assert finished2["conversation_id"] == cid

    def test_ws_different_messages_can_use_different_conversations(
        self, ws_app: FastAPI,
    ) -> None:
        """Two messages without an id should yield two separate conversations."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "msg1"})
            finished1 = _finished(ws)

            ws.send_json({"content": "msg2"})
            finished2 = _finished(ws)

            assert finished1["conversation_id"] != finished2["conversation_id"]


# ---------------------------------------------------------------------------
# Tests — disconnect behaviour
# ---------------------------------------------------------------------------


class TestWebSocketDisconnect:
    """Graceful disconnect and reconnection tests."""

    def test_ws_graceful_disconnect(self, ws_app: FastAPI) -> None:
        """Client disconnects cleanly — no server crash."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "bye"})
            _finished(ws)
        # Exiting the context manager closes the WS; no exception expected.

    @pytest.mark.skip(
        reason=(
            "PRE-EXISTING hang (censused, Mossa 2 T9): the SECOND "
            "websocket_connect on the same lifespan-booted app never receives "
            "turn frames. Reproduced identically on pre-T9 HEAD (837b4e3) with "
            "the legacy wire, correct venv, clean env - not a T9 regression. "
            "Strongest hypothesis: TestClient opens a new blocking portal per "
            "connection while app services live on the pytest-asyncio loop "
            "(cross-loop primitives); production serves every connection from "
            "one server loop. Tracked in the Mossa 2 ledger/handoff."
        ),
    )
    def test_ws_reconnect_after_disconnect(self, ws_app: FastAPI) -> None:
        """After disconnecting, a new WS connection should work normally."""
        client = TestClient(ws_app)

        # First connection.
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "first"})
            _finished(ws)

        # Second connection.
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "second"})
            finished = _finished(ws)
            assert finished["type"] == "turn.finished"

    def test_ws_multiple_messages_in_single_connection(
        self, ws_app: FastAPI,
    ) -> None:
        """The WS loop should handle multiple sequential messages."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            for i in range(3):
                ws.send_json({"content": f"msg {i}"})
                finished = _finished(ws)
                assert finished["type"] == "turn.finished"
