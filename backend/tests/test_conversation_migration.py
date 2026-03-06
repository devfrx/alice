"""Tests for conversation file migration and tool-call round-trips (Phase 3.8).

Complements ``test_conversation_file_manager.py`` with focused tests on
v2 tool_calls serialisation, tool-message round-trip integrity, and
schema version detection.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.services.conversation_file_manager import (
    CURRENT_SCHEMA_VERSION,
    ConversationFileManager,
    _migrate_v1_to_v2,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _v2_conversation_with_tool_calls() -> dict[str, Any]:
    """Return a v2 conversation with an assistant tool_calls message."""
    conv_id = str(uuid.uuid4())
    now = _now_iso()
    return {
        "id": conv_id,
        "title": "Tool call conversation",
        "created_at": now,
        "updated_at": now,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "messages": [
            {
                "id": str(uuid.uuid4()),
                "role": "user",
                "content": "What is 2+2?",
                "tool_calls": None,
                "tool_call_id": None,
                "thinking_content": None,
                "created_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "calculator_add",
                            "arguments": '{"a": 2, "b": 2}',
                        },
                    },
                ],
                "tool_call_id": None,
                "thinking_content": "I should use the calculator",
                "created_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "role": "tool",
                "content": '{"result": 4}',
                "tool_calls": None,
                "tool_call_id": "call_abc123",
                "thinking_content": None,
                "created_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": "The answer is 4.",
                "tool_calls": None,
                "tool_call_id": None,
                "thinking_content": None,
                "created_at": now,
            },
        ],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fm(tmp_path: Path) -> ConversationFileManager:
    """File manager backed by a temp directory."""
    return ConversationFileManager(tmp_path)


# ---------------------------------------------------------------------------
# v2 tool_calls serialisation round-trip
# ---------------------------------------------------------------------------


class TestToolCallsRoundTrip:
    """Verify tool_calls and tool_call_id survive save → load."""

    async def test_assistant_tool_calls_preserved(
        self, fm: ConversationFileManager,
    ) -> None:
        """Save a conversation with assistant tool_calls → load → verify."""
        data = _v2_conversation_with_tool_calls()
        await fm.save(data)
        loaded = await fm.load(data["id"])

        assert loaded is not None
        asst = loaded["messages"][1]
        assert asst["role"] == "assistant"
        assert len(asst["tool_calls"]) == 1
        assert asst["tool_calls"][0]["id"] == "call_abc123"
        assert asst["tool_calls"][0]["function"]["name"] == "calculator_add"

    async def test_tool_message_tool_call_id_preserved(
        self, fm: ConversationFileManager,
    ) -> None:
        """Save a tool-role message with tool_call_id → load → verify."""
        data = _v2_conversation_with_tool_calls()
        await fm.save(data)
        loaded = await fm.load(data["id"])

        assert loaded is not None
        tool_msg = loaded["messages"][2]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_abc123"
        assert tool_msg["content"] == '{"result": 4}'

    async def test_full_round_trip_integrity(
        self, fm: ConversationFileManager,
    ) -> None:
        """All messages survive a full save → load cycle unchanged."""
        data = _v2_conversation_with_tool_calls()
        await fm.save(data)
        loaded = await fm.load(data["id"])

        assert loaded is not None
        assert len(loaded["messages"]) == len(data["messages"])
        for orig, reloaded in zip(data["messages"], loaded["messages"]):
            assert orig["role"] == reloaded["role"]
            assert orig["content"] == reloaded["content"]
            assert orig["tool_calls"] == reloaded["tool_calls"]
            assert orig["tool_call_id"] == reloaded["tool_call_id"]


# ---------------------------------------------------------------------------
# _migrate_v1_to_v2 unit tests
# ---------------------------------------------------------------------------


class TestMigrateV1ToV2:
    """Direct tests for the migration function."""

    def test_adds_missing_tool_fields(self) -> None:
        """Messages without tool_calls/tool_call_id get them set to None."""
        v1 = {
            "schema_version": 1,
            "messages": [{"role": "user", "content": "hi"}],
        }
        result = _migrate_v1_to_v2(v1)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        assert result["messages"][0]["tool_calls"] is None
        assert result["messages"][0]["tool_call_id"] is None

    def test_preserves_existing_tool_calls(self) -> None:
        """Messages that already have tool_calls keep their value."""
        tc = [{"id": "c1", "type": "function", "function": {"name": "f"}}]
        v1 = {
            "messages": [
                {"role": "assistant", "content": "", "tool_calls": tc},
            ],
        }
        result = _migrate_v1_to_v2(v1)
        assert result["messages"][0]["tool_calls"] == tc

    def test_no_schema_version_treated_as_v1(self) -> None:
        """Data without schema_version is migrated as v1."""
        data = {"messages": [{"role": "user", "content": "old"}]}
        result = _migrate_v1_to_v2(data)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Schema version detection via load
# ---------------------------------------------------------------------------


class TestSchemaDetection:
    """Verify that load() detects schema version and migrates if needed."""

    async def test_v1_file_migrated_on_disk(
        self, fm: ConversationFileManager, tmp_path: Path,
    ) -> None:
        """A v1 file is migrated and re-saved on disk."""
        conv_id = str(uuid.uuid4())
        v1 = {
            "id": conv_id,
            "title": "Legacy",
            "messages": [{"role": "user", "content": "old"}],
        }
        (tmp_path / f"{conv_id}.json").write_text(
            json.dumps(v1), encoding="utf-8",
        )
        loaded = await fm.load(conv_id)
        assert loaded is not None
        assert loaded["schema_version"] == CURRENT_SCHEMA_VERSION

        # Re-read from disk to confirm migration was persisted
        raw = json.loads(
            (tmp_path / f"{conv_id}.json").read_text(encoding="utf-8")
        )
        assert raw["schema_version"] == CURRENT_SCHEMA_VERSION

    async def test_v2_file_not_modified(
        self, fm: ConversationFileManager, tmp_path: Path,
    ) -> None:
        """A v2 file is returned as-is; disk file is not rewritten."""
        data = _v2_conversation_with_tool_calls()
        await fm.save(data)
        path = tmp_path / f"{data['id']}.json"
        mtime_before = path.stat().st_mtime_ns
        loaded = await fm.load(data["id"])
        mtime_after = path.stat().st_mtime_ns
        assert loaded is not None
        assert mtime_before == mtime_after
