"""Tests for the branch-conversation feature.

POST /api/chat/conversations/{id}/branch
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from starlette.testclient import TestClient


# ---------------------------------------------------------------------------
# Mock LLM helpers (same pattern as test_message_editing.py)
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
    system_prompt: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    yield {"type": "token", "content": "Reply"}
    yield {"type": "done"}


def _mock_build_messages(
    user_content: str,
    history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, str]] | None = None,
    memory_context: str | None = None,
    system_prompt: str | None = None,
) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "system"},
        {"role": "user", "content": user_content},
    ]


def _patch_llm(app: FastAPI) -> None:
    llm = app.state.context.llm_service
    llm.chat = _mock_chat_generator
    llm.build_messages = _mock_build_messages


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ws_app(app: FastAPI) -> FastAPI:
    _patch_llm(app)
    return app


# ---------------------------------------------------------------------------
# WS helper
# ---------------------------------------------------------------------------


def _ws_send_message(
    test_client: TestClient,
    content: str,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Send a message via WebSocket and return the ``done`` event.

    Opens a single WebSocket connection, sends *content* (optionally
    targeting *conversation_id*), drains all events until the server
    sends ``{"type": "done"}``, then closes the connection and returns
    that done event dict.

    Args:
        test_client: Starlette TestClient wired to the test app.
        content: User message text.
        conversation_id: Existing conversation UUID string to continue,
            or ``None`` to start a new conversation.

    Returns:
        The ``done`` event dict which includes ``conversation_id``,
        ``message_id`` (assistant), and ``user_message_id``.
    """
    payload: dict[str, Any] = {"content": content}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    with test_client.websocket_connect("/api/ws/chat") as ws:
        ws.send_json(payload)
        while True:
            event = ws.receive_json()
            if event.get("type") == "done":
                return event
    # Unreachable — but makes type checkers happy.
    raise RuntimeError("WebSocket closed without done event")  # pragma: no cover


# ---------------------------------------------------------------------------
# Tests — branch conversation
# ---------------------------------------------------------------------------


class TestBranchConversation:
    """Integration tests for POST /chat/conversations/{id}/branch."""

    # ------------------------------------------------------------------
    # Happy-path tests
    # ------------------------------------------------------------------

    def test_branch_creates_new_conversation(self, ws_app: FastAPI) -> None:
        """Branching from the first assistant message creates a new conversation
        with exactly 2 messages while leaving the source unchanged (4 messages)."""
        tc = TestClient(ws_app)

        # Build a conversation with 2 message pairs (4 messages total).
        with tc.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "First message"})
            while True:
                ev = ws.receive_json()
                if ev.get("type") == "done":
                    done1 = ev
                    break

            conv_id = done1["conversation_id"]
            asst_msg_id_1 = done1["message_id"]

            ws.send_json({"content": "Second message", "conversation_id": conv_id})
            while True:
                ev = ws.receive_json()
                if ev.get("type") == "done":
                    break  # done2 consumed — source now has 4 messages

        # Branch from the FIRST assistant message.
        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": asst_msg_id_1},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Response structure assertions.
        assert data["id"] != conv_id
        assert data["message_count"] == 2
        assert data["title"] is not None
        assert "diramazione" in data["title"]
        assert data["created_at"]   # ISO string present
        assert data["updated_at"]   # ISO string present

        new_id = data["id"]

        # New conversation has exactly 2 messages (user + assistant).
        get_resp = tc.get(f"/api/chat/conversations/{new_id}")
        assert get_resp.status_code == 200
        assert len(get_resp.json()["messages"]) == 2

        # Source conversation is untouched — still 4 messages.
        src_resp = tc.get(f"/api/chat/conversations/{conv_id}")
        assert src_resp.status_code == 200
        assert len(src_resp.json()["messages"]) == 4

    def test_branch_from_last_message(self, ws_app: FastAPI) -> None:
        """Branching from the only assistant message gives 2 messages."""
        tc = TestClient(ws_app)
        done = _ws_send_message(tc, "Only message")
        conv_id = done["conversation_id"]
        asst_msg_id = done["message_id"]

        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": asst_msg_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message_count"] == 2

        # Verify via GET.
        get_resp = tc.get(f"/api/chat/conversations/{data['id']}")
        assert get_resp.status_code == 200
        assert len(get_resp.json()["messages"]) == 2

    def test_branch_with_custom_title(self, ws_app: FastAPI) -> None:
        """Supplying an explicit title uses that title verbatim."""
        tc = TestClient(ws_app)
        done = _ws_send_message(tc, "Some message")
        conv_id = done["conversation_id"]
        asst_msg_id = done["message_id"]

        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": asst_msg_id, "title": "My Branch Title"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "My Branch Title"

    def test_branch_source_unchanged(self, ws_app: FastAPI) -> None:
        """Branching from the middle of a 3-pair conversation leaves the
        source with 6 messages and returns 4 messages in the branch."""
        tc = TestClient(ws_app)

        # Build 3 message pairs (6 messages).
        with tc.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "Msg 1"})
            while True:
                ev = ws.receive_json()
                if ev.get("type") == "done":
                    done1 = ev
                    break

            conv_id = done1["conversation_id"]

            ws.send_json({"content": "Msg 2", "conversation_id": conv_id})
            while True:
                ev = ws.receive_json()
                if ev.get("type") == "done":
                    done2 = ev
                    break

            asst_msg_id_2 = done2["message_id"]

            ws.send_json({"content": "Msg 3", "conversation_id": conv_id})
            while True:
                ev = ws.receive_json()
                if ev.get("type") == "done":
                    break  # third pair consumed

        # Branch from second assistant — expect 4 messages (2 pairs).
        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": asst_msg_id_2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message_count"] == 4

        get_resp = tc.get(f"/api/chat/conversations/{data['id']}")
        assert get_resp.status_code == 200
        assert len(get_resp.json()["messages"]) == 4

        # Source is untouched.
        src_resp = tc.get(f"/api/chat/conversations/{conv_id}")
        assert src_resp.status_code == 200
        assert len(src_resp.json()["messages"]) == 6

    def test_branch_messages_have_no_version_metadata(self, ws_app: FastAPI) -> None:
        """All messages in the branch have version_group_id=null and version_index=0."""
        tc = TestClient(ws_app)
        done = _ws_send_message(tc, "Version metadata test")
        conv_id = done["conversation_id"]
        asst_msg_id = done["message_id"]

        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": asst_msg_id},
        )
        assert resp.status_code == 200
        new_id = resp.json()["id"]

        get_resp = tc.get(f"/api/chat/conversations/{new_id}")
        assert get_resp.status_code == 200
        messages = get_resp.json()["messages"]
        assert len(messages) > 0, "Branch must contain at least one message"
        for msg in messages:
            assert msg["version_group_id"] is None, (
                f"message {msg['id']} has unexpected version_group_id"
            )
            assert msg["version_index"] == 0, (
                f"message {msg['id']} has unexpected version_index"
            )

    def test_branch_preserves_message_content(self, ws_app: FastAPI) -> None:
        """Copied messages retain their original content."""
        tc = TestClient(ws_app)
        unique_content = "unique-content-xyz-test-branch"
        done = _ws_send_message(tc, unique_content)
        conv_id = done["conversation_id"]
        asst_msg_id = done["message_id"]

        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": asst_msg_id},
        )
        assert resp.status_code == 200
        new_id = resp.json()["id"]

        get_resp = tc.get(f"/api/chat/conversations/{new_id}")
        assert get_resp.status_code == 200
        messages = get_resp.json()["messages"]
        contents = [m["content"] for m in messages]
        assert any(unique_content in c for c in contents), (
            f"Expected '{unique_content}' in one of: {contents}"
        )

    # ------------------------------------------------------------------
    # Error-path tests
    # ------------------------------------------------------------------

    def test_branch_invalid_conversation_id(self, ws_app: FastAPI) -> None:
        """Non-UUID conversation_id in path returns 400."""
        tc = TestClient(ws_app)
        resp = tc.post(
            "/api/chat/conversations/not-a-uuid/branch",
            json={"from_message_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 400

    def test_branch_conversation_not_found(self, ws_app: FastAPI) -> None:
        """Valid but non-existent conversation UUID returns 404."""
        tc = TestClient(ws_app)
        resp = tc.post(
            f"/api/chat/conversations/{uuid.uuid4()}/branch",
            json={"from_message_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    def test_branch_message_not_found(self, ws_app: FastAPI) -> None:
        """Random message UUID that doesn't exist in the conversation returns 404."""
        tc = TestClient(ws_app)
        done = _ws_send_message(tc, "Some message for 404 test")
        conv_id = done["conversation_id"]

        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    def test_branch_message_from_wrong_conversation(self, ws_app: FastAPI) -> None:
        """Using a message_id that belongs to a different conversation returns 404."""
        tc = TestClient(ws_app)

        # Create conversation A.
        done_a = _ws_send_message(tc, "Conversation A message")
        conv_a_id = done_a["conversation_id"]

        # Create conversation B (independent new conversation).
        done_b = _ws_send_message(tc, "Conversation B message")
        asst_msg_id_b = done_b["message_id"]

        # Attempt to branch A using a message that belongs to B.
        resp = tc.post(
            f"/api/chat/conversations/{conv_a_id}/branch",
            json={"from_message_id": asst_msg_id_b},
        )
        assert resp.status_code == 404

    def test_branch_with_empty_from_message_id(self, ws_app: FastAPI) -> None:
        """Empty string for from_message_id returns 400."""
        tc = TestClient(ws_app)
        done = _ws_send_message(tc, "Message for empty-id test")
        conv_id = done["conversation_id"]

        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": ""},
        )
        assert resp.status_code == 400

    # ------------------------------------------------------------------
    # Additional assertion tests
    # ------------------------------------------------------------------

    def test_branch_response_id_is_valid_uuid(self, ws_app: FastAPI) -> None:
        """The id in the branch response is a valid UUID string."""
        tc = TestClient(ws_app)
        done = _ws_send_message(tc, "UUID validation test")
        conv_id = done["conversation_id"]
        asst_msg_id = done["message_id"]

        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": asst_msg_id},
        )
        assert resp.status_code == 200
        new_id = resp.json()["id"]
        # Should parse without error.
        parsed = uuid.UUID(new_id)
        assert str(parsed) == new_id

    def test_branch_new_conversation_retrievable(self, ws_app: FastAPI) -> None:
        """The newly created conversation can be fetched via GET."""
        tc = TestClient(ws_app)
        done = _ws_send_message(tc, "Retrieve test")
        conv_id = done["conversation_id"]
        asst_msg_id = done["message_id"]

        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": asst_msg_id},
        )
        assert resp.status_code == 200
        new_id = resp.json()["id"]

        get_resp = tc.get(f"/api/chat/conversations/{new_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == new_id

    def test_branch_user_message_also_copied(self, ws_app: FastAPI) -> None:
        """The branch includes both the user message and the assistant reply."""
        tc = TestClient(ws_app)
        done = _ws_send_message(tc, "Role check")
        conv_id = done["conversation_id"]
        asst_msg_id = done["message_id"]

        resp = tc.post(
            f"/api/chat/conversations/{conv_id}/branch",
            json={"from_message_id": asst_msg_id},
        )
        assert resp.status_code == 200
        new_id = resp.json()["id"]

        get_resp = tc.get(f"/api/chat/conversations/{new_id}")
        assert get_resp.status_code == 200
        messages = get_resp.json()["messages"]
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles
