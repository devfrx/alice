"""Tests for the WebSocket chat endpoint ``/api/ws/chat``."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Mock LLM helpers
# ---------------------------------------------------------------------------


async def _mock_chat_generator(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    cancel_event: asyncio.Event | None = None,
    *,
    user_content: str | None = None,
    conversation_id: str | None = None,
    attachments: list[dict[str, str]] | None = None,
    memory_context: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield a few tokens then done — stands in for ``LLMService.chat``."""
    yield {"type": "token", "content": "Hello"}
    yield {"type": "token", "content": " world"}
    yield {"type": "done"}


def _mock_build_messages(
    user_content: str,
    history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, str]] | None = None,
    memory_context: str | None = None,
) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": user_content},
    ]


def _patch_llm(app: FastAPI) -> None:
    """Replace the real LLM service on *app* with a deterministic mock."""
    llm = app.state.context.llm_service
    llm.chat = _mock_chat_generator
    llm.build_messages = _mock_build_messages


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

    def test_ws_send_valid_message_receives_tokens(
        self, ws_app: FastAPI,
    ) -> None:
        """Send a message, expect token events followed by a done event."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "Hi there"})

            token1 = ws.receive_json()
            assert token1["type"] == "token"
            assert token1["content"] == "Hello"

            token2 = ws.receive_json()
            assert token2["type"] == "token"
            assert token2["content"] == " world"

            done = ws.receive_json()
            assert done["type"] == "done"
            assert "conversation_id" in done
            assert "message_id" in done

    def test_ws_done_event_contains_valid_uuids(
        self, ws_app: FastAPI,
    ) -> None:
        """The done payload must carry valid UUID strings."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "test"})
            # Drain tokens.
            ws.receive_json()
            ws.receive_json()

            done = ws.receive_json()
            uuid.UUID(done["conversation_id"])
            uuid.UUID(done["message_id"])


# ---------------------------------------------------------------------------
# Tests — error handling
# ---------------------------------------------------------------------------


class TestWebSocketErrors:
    """Edge-case and error handling for the WebSocket endpoint."""

    def test_ws_invalid_json_receives_error(
        self, ws_app: FastAPI,
    ) -> None:
        """Sending non-JSON text should return an error frame."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_text("not json {{{")
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "Invalid JSON" in resp["content"]

    def test_ws_empty_message_receives_error(
        self, ws_app: FastAPI,
    ) -> None:
        """An empty ``content`` field should be rejected."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": ""})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "Empty message" in resp["content"]

    def test_ws_whitespace_only_message_receives_error(
        self, ws_app: FastAPI,
    ) -> None:
        """A whitespace-only ``content`` should also be rejected."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "   "})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "Empty message" in resp["content"]

    def test_ws_missing_content_field_receives_error(
        self, ws_app: FastAPI,
    ) -> None:
        """Omitting ``content`` entirely should produce an error."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"not_content": "oops"})
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "Empty message" in resp["content"]


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
            ws.receive_json()  # token
            ws.receive_json()  # token
            done = ws.receive_json()
            assert done["type"] == "done"
            conv_id = done["conversation_id"]
            # Must be a valid UUID.
            uuid.UUID(conv_id)

    def test_ws_with_conversation_id_reuses_conversation(
        self, ws_app: FastAPI,
    ) -> None:
        """Providing a ``conversation_id`` must reuse that conversation."""
        cid = str(uuid.uuid4())
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "first", "conversation_id": cid})
            ws.receive_json()
            ws.receive_json()
            done1 = ws.receive_json()
            assert done1["conversation_id"] == cid

            ws.send_json({"content": "second", "conversation_id": cid})
            ws.receive_json()
            ws.receive_json()
            done2 = ws.receive_json()
            assert done2["conversation_id"] == cid

    def test_ws_different_messages_can_use_different_conversations(
        self, ws_app: FastAPI,
    ) -> None:
        """Two messages without an id should yield two separate conversations."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "msg1"})
            ws.receive_json()
            ws.receive_json()
            done1 = ws.receive_json()

            ws.send_json({"content": "msg2"})
            ws.receive_json()
            ws.receive_json()
            done2 = ws.receive_json()

            assert done1["conversation_id"] != done2["conversation_id"]


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
            ws.receive_json()
            ws.receive_json()
            ws.receive_json()  # done
        # Exiting the context manager closes the WS; no exception expected.

    def test_ws_reconnect_after_disconnect(self, ws_app: FastAPI) -> None:
        """After disconnecting, a new WS connection should work normally."""
        client = TestClient(ws_app)

        # First connection.
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "first"})
            ws.receive_json()
            ws.receive_json()
            ws.receive_json()

        # Second connection.
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "second"})
            token1 = ws.receive_json()
            assert token1["type"] == "token"
            ws.receive_json()
            done = ws.receive_json()
            assert done["type"] == "done"

    def test_ws_multiple_messages_in_single_connection(
        self, ws_app: FastAPI,
    ) -> None:
        """The WS loop should handle multiple sequential messages."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            for i in range(3):
                ws.send_json({"content": f"msg {i}"})
                ws.receive_json()  # token
                ws.receive_json()  # token
                done = ws.receive_json()
                assert done["type"] == "done"
