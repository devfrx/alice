"""Tests for the message edit / version-switching feature.

Covers:
- ``_filter_messages_by_active_versions`` helper
- ``POST /chat/conversations/{id}/switch-version`` REST endpoint
- WebSocket edit-message flow (``edit_message_id`` in payload)
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

from backend.api.routes.chat import _filter_messages_by_active_versions


# ---------------------------------------------------------------------------
# Mock LLM helpers (same pattern as test_websocket.py)
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
    max_output_tokens: int | None = None,
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


def _recv_done(ws) -> dict:
    """Drain WS events until a ``done`` event is received and return it."""
    for _ in range(20):
        msg = ws.receive_json()
        if msg.get("type") == "done":
            return msg
    raise RuntimeError("Never received a 'done' event")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ws_app(app: FastAPI) -> FastAPI:
    _patch_llm(app)
    return app


# ---------------------------------------------------------------------------
# Tests — _filter_messages_by_active_versions
# ---------------------------------------------------------------------------


class TestFilterMessagesByActiveVersions:
    """Unit tests for the version-filter helper."""

    def test_no_version_group_passes_through(self) -> None:
        """Messages without version_group_id are always included."""
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = _filter_messages_by_active_versions(msgs, {})
        assert len(result) == 2

    def test_active_version_included(self) -> None:
        """Only the active version's messages pass through."""
        gid = str(uuid.uuid4())
        msgs = [
            {"role": "user", "content": "v0", "version_group_id": gid, "version_index": 0},
            {"role": "assistant", "content": "r0", "version_group_id": gid, "version_index": 0},
            {"role": "user", "content": "v1", "version_group_id": gid, "version_index": 1},
            {"role": "assistant", "content": "r1", "version_group_id": gid, "version_index": 1},
        ]
        result = _filter_messages_by_active_versions(msgs, {gid: 1})
        assert len(result) == 2
        assert result[0]["content"] == "v1"
        assert result[1]["content"] == "r1"

    def test_default_active_index_is_zero(self) -> None:
        """When a group is not in active_versions, version 0 is used."""
        gid = str(uuid.uuid4())
        msgs = [
            {"role": "user", "content": "v0", "version_group_id": gid, "version_index": 0},
            {"role": "user", "content": "v1", "version_group_id": gid, "version_index": 1},
        ]
        result = _filter_messages_by_active_versions(msgs, {})
        assert len(result) == 1
        assert result[0]["content"] == "v0"

    def test_mixed_versioned_and_unversioned(self) -> None:
        """Unversioned messages coexist with versioned ones."""
        gid = str(uuid.uuid4())
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "v0", "version_group_id": gid, "version_index": 0},
            {"role": "assistant", "content": "r0", "version_group_id": gid, "version_index": 0},
            {"role": "user", "content": "v1", "version_group_id": gid, "version_index": 1},
            {"role": "assistant", "content": "r1", "version_group_id": gid, "version_index": 1},
        ]
        result = _filter_messages_by_active_versions(msgs, {gid: 1})
        assert len(result) == 4
        assert result[0]["content"] == "first"
        assert result[1]["content"] == "ok"
        assert result[2]["content"] == "v1"
        assert result[3]["content"] == "r1"

    def test_multiple_version_groups(self) -> None:
        """Multiple groups each filter independently."""
        gid_a = str(uuid.uuid4())
        gid_b = str(uuid.uuid4())
        msgs = [
            {"role": "user", "content": "a0", "version_group_id": gid_a, "version_index": 0},
            {"role": "user", "content": "a1", "version_group_id": gid_a, "version_index": 1},
            {"role": "user", "content": "b0", "version_group_id": gid_b, "version_index": 0},
            {"role": "user", "content": "b1", "version_group_id": gid_b, "version_index": 1},
        ]
        result = _filter_messages_by_active_versions(
            msgs, {gid_a: 0, gid_b: 1},
        )
        assert len(result) == 2
        assert result[0]["content"] == "a0"
        assert result[1]["content"] == "b1"

    def test_orphaned_group_excluded(self) -> None:
        """When active_versions references an index that no message has, those messages are excluded."""
        gid = str(uuid.uuid4())
        msgs = [
            {"role": "user", "content": "unversioned"},
            {"role": "user", "content": "v0", "version_group_id": gid, "version_index": 0},
            {"role": "user", "content": "v1", "version_group_id": gid, "version_index": 1},
        ]
        # active_versions says index 3, but no message has version_index=3 for this gid.
        result = _filter_messages_by_active_versions(msgs, {gid: 3})
        # Only the unversioned message passes through.
        assert len(result) == 1
        assert result[0]["content"] == "unversioned"


# ---------------------------------------------------------------------------
# Tests — switch-version REST endpoint
# ---------------------------------------------------------------------------


class TestSwitchVersion:
    """Integration tests for POST /chat/conversations/{id}/switch-version."""

    def _create_conversation_with_versions(
        self, test_client: TestClient,
    ) -> tuple[str, str]:
        """Helper: create a conversation, send a message, then edit it.

        Uses ``test_client`` for both WS and REST so all operations share
        the same AppContext / in-memory DB instance.

        Returns (conversation_id, version_group_id).
        """
        with test_client.websocket_connect("/api/ws/chat") as ws:
            # Send the first message.
            ws.send_json({"content": "original message"})
            done = _recv_done(ws)
            conv_id = done["conversation_id"]
            msg_id = done["user_message_id"]

            # Edit the message — this creates a new version branch.
            ws.send_json({
                "content": "edited message",
                "conversation_id": conv_id,
                "edit_message_id": msg_id,
            })
            done2 = _recv_done(ws)
            vg_id = done2.get("version_group_id")

        return conv_id, vg_id

    def test_switch_version_success(self, ws_app: FastAPI) -> None:
        """Switching to a valid version updates active_versions."""
        test_client = TestClient(ws_app)
        conv_id, vg_id = self._create_conversation_with_versions(test_client)
        if not vg_id:
            pytest.fail("version_group_id not returned from edit flow")

        resp = test_client.post(
            f"/api/chat/conversations/{conv_id}/switch-version",
            json={"version_group_id": vg_id, "version_index": 0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_versions"][vg_id] == 0

    def test_switch_version_not_found(self, ws_app: FastAPI) -> None:
        """Switching to a non-existent version returns 404."""
        test_client = TestClient(ws_app)
        conv_id, vg_id = self._create_conversation_with_versions(test_client)
        if not vg_id:
            pytest.fail("version_group_id not returned from edit flow")

        resp = test_client.post(
            f"/api/chat/conversations/{conv_id}/switch-version",
            json={"version_group_id": vg_id, "version_index": 999},
        )
        assert resp.status_code == 404

    async def test_switch_version_missing_params(
        self, client: AsyncClient,
    ) -> None:
        """Missing body fields return 400."""
        fake_conv = str(uuid.uuid4())
        resp = await client.post(
            f"/api/chat/conversations/{fake_conv}/switch-version",
            json={},
        )
        assert resp.status_code == 400

    async def test_switch_version_invalid_group_id(
        self, client: AsyncClient,
    ) -> None:
        """Invalid version_group_id returns 400."""
        fake_conv = str(uuid.uuid4())
        resp = await client.post(
            f"/api/chat/conversations/{fake_conv}/switch-version",
            json={"version_group_id": "not-a-uuid", "version_index": 0},
        )
        assert resp.status_code == 400

    async def test_switch_version_conversation_not_found(
        self, client: AsyncClient,
    ) -> None:
        """Non-existent conversation returns 404."""
        resp = await client.post(
            f"/api/chat/conversations/{uuid.uuid4()}/switch-version",
            json={
                "version_group_id": str(uuid.uuid4()),
                "version_index": 0,
            },
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — WebSocket edit-message flow
# ---------------------------------------------------------------------------


class TestWebSocketEditMessage:
    """Tests for the edit-message flow via WebSocket."""

    def test_edit_message_creates_new_version(
        self, ws_app: FastAPI,
    ) -> None:
        """Editing a user message streams a new response."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            # Send original message.
            ws.send_json({"content": "original"})
            done = _recv_done(ws)
            conv_id = done["conversation_id"]
            user_msg_id = done["user_message_id"]

            # Edit the message.
            ws.send_json({
                "content": "edited",
                "conversation_id": conv_id,
                "edit_message_id": user_msg_id,
            })
            done2 = _recv_done(ws)
            assert done2["conversation_id"] == conv_id
            # Should have version metadata.
            assert done2.get("version_group_id") is not None
            assert done2.get("version_index") is not None
            assert done2["version_index"] >= 1

    def test_edit_invalid_message_id_returns_error(
        self, ws_app: FastAPI,
    ) -> None:
        """Editing with an invalid message_id returns an error event."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            # Send a message first to get a conversation.
            ws.send_json({"content": "test"})
            done = _recv_done(ws)
            conv_id = done["conversation_id"]

            # Try to edit with a non-existent message_id.
            ws.send_json({
                "content": "edited",
                "conversation_id": conv_id,
                "edit_message_id": str(uuid.uuid4()),
            })
            resp = ws.receive_json()
            assert resp["type"] == "error"

    def test_edit_invalid_uuid_returns_error(
        self, ws_app: FastAPI,
    ) -> None:
        """Editing with a malformed UUID returns an error event."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "test"})
            done = _recv_done(ws)
            conv_id = done["conversation_id"]

            ws.send_json({
                "content": "edited",
                "conversation_id": conv_id,
                "edit_message_id": "not-a-uuid",
            })
            resp = ws.receive_json()
            assert resp["type"] == "error"

    def test_edit_assistant_message_rejected(self, ws_app: FastAPI) -> None:
        """Editing a message with role=assistant is rejected with 'Invalid edit target'."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "hello"})
            done = _recv_done(ws)
            conv_id = done["conversation_id"]
            asst_msg_id = done["message_id"]  # assistant message ID

            ws.send_json({
                "content": "tampered",
                "conversation_id": conv_id,
                "edit_message_id": asst_msg_id,
            })
            resp = ws.receive_json()
            assert resp["type"] == "error"
            assert "Invalid edit target" in resp["content"]

    def test_edit_message_from_different_conversation_rejected(
        self, ws_app: FastAPI,
    ) -> None:
        """Editing a message that belongs to a different conversation is rejected."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            # Create conversation A.
            ws.send_json({"content": "conversation A"})
            done_a = _recv_done(ws)
            msg_a_id = done_a["user_message_id"]

            # Create conversation B (no conversation_id → new conversation).
            ws.send_json({"content": "conversation B"})
            done_b = _recv_done(ws)
            conv_b_id = done_b["conversation_id"]

            # Attempt to edit a message from A while targeting conversation B.
            ws.send_json({
                "content": "cross-conversation edit",
                "conversation_id": conv_b_id,
                "edit_message_id": msg_a_id,
            })
            resp = ws.receive_json()
            assert resp["type"] == "error"

    def test_edit_preserves_conversation_history(
        self, ws_app: FastAPI,
    ) -> None:
        """After editing, the conversation should contain both versions."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "first message"})
            done1 = _recv_done(ws)
            conv_id = done1["conversation_id"]
            user_msg_id = done1["user_message_id"]

            ws.send_json({
                "content": "edited first message",
                "conversation_id": conv_id,
                "edit_message_id": user_msg_id,
            })
            _recv_done(ws)

        # Verify both versions are in the conversation via REST using the same
        # TestClient so we read from the same in-memory DB.
        resp = client.get(f"/api/chat/conversations/{conv_id}")
        assert resp.status_code == 200
        data = resp.json()
        msgs = data["messages"]
        user_msgs = [m for m in msgs if m["role"] == "user"]
        # Should have at least 2 user messages (original + edit).
        assert len(user_msgs) >= 2

    def test_multiple_edits_increment_version_index(
        self, ws_app: FastAPI,
    ) -> None:
        """Each edit bumps the version_index."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "v0"})
            done0 = _recv_done(ws)
            conv_id = done0["conversation_id"]
            msg_id = done0["user_message_id"]

            # Edit #1
            ws.send_json({
                "content": "v1",
                "conversation_id": conv_id,
                "edit_message_id": msg_id,
            })
            done1 = _recv_done(ws)
            assert done1["version_index"] == 1

            # Edit #2 — use the same original message_id.
            ws.send_json({
                "content": "v2",
                "conversation_id": conv_id,
                "edit_message_id": msg_id,
            })
            done2 = _recv_done(ws)
            assert done2["version_index"] == 2

    def test_new_message_inherits_version_context(
        self, ws_app: FastAPI,
    ) -> None:
        """A new message after an edit inherits the active branch's version."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            # Send original message.
            ws.send_json({"content": "v0"})
            done0 = _recv_done(ws)
            conv_id = done0["conversation_id"]
            msg_id = done0["user_message_id"]

            # Edit to create v1.
            ws.send_json({
                "content": "v1",
                "conversation_id": conv_id,
                "edit_message_id": msg_id,
            })
            done1 = _recv_done(ws)
            assert done1["version_index"] == 1
            vg_id = done1["version_group_id"]

            # Send a NEW message (not an edit) in the v1 branch.
            ws.send_json({
                "content": "follow up in v1",
                "conversation_id": conv_id,
            })
            done2 = _recv_done(ws)
            # The new message should inherit the active version context.
            assert done2["version_group_id"] == vg_id
            assert done2["version_index"] == 1

    def test_new_message_no_version_when_no_edits(
        self, ws_app: FastAPI,
    ) -> None:
        """A new message in a conversation without edits has no version metadata."""
        client = TestClient(ws_app)
        with client.websocket_connect("/api/ws/chat") as ws:
            ws.send_json({"content": "hello"})
            done = _recv_done(ws)
            assert done.get("version_group_id") is None
            # version_index may be 0 or None for unversioned messages.
            assert done.get("version_index") in (0, None)

            # Second message — still no version groups.
            ws.send_json({
                "content": "follow up",
                "conversation_id": done["conversation_id"],
            })
            done2 = _recv_done(ws)
            assert done2.get("version_group_id") is None
            assert done2.get("version_index") in (0, None)
