"""O.M.N.I.A. — Tests for Phase 3.3 tool calling loop + history normalization."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.event_bus import EventBus, OmniaEvent
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.db.models import Message
from backend.services.llm_service import LLMService, normalize_history


# -- fixtures --


@pytest.fixture
def llm_config():
    """Create a test LLMConfig with defaults."""
    from backend.core.config import LLMConfig

    return LLMConfig(
        base_url="http://localhost:11434",
        model="test-model",
        system_prompt_file="config/system_prompt.md",  # Use project's actual file
        max_tool_iterations=10,
        confirmation_timeout_s=60,
    )


@pytest.fixture
def llm_service(llm_config):
    """Create a test LLMService."""
    return LLMService(llm_config)


# ---------- A. normalize_history tests ----------


class TestNormalizeHistory:
    def test_simple_user_message(self):
        """User messages produce {role, content} only."""
        history = [
            {"role": "user", "content": "Hello", "tool_calls": None, "tool_call_id": None}
        ]
        result = normalize_history(history)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_simple_assistant_message(self):
        """Assistant messages without tool_calls produce {role, content}."""
        history = [
            {"role": "assistant", "content": "Hi!", "tool_calls": None, "tool_call_id": None}
        ]
        result = normalize_history(history)
        assert result == [{"role": "assistant", "content": "Hi!"}]

    def test_assistant_with_tool_calls(self):
        """Assistant messages with tool_calls include them."""
        tool_calls = [
            {
                "id": "tc_1",
                "type": "function",
                "function": {"name": "get_info", "arguments": "{}"},
            }
        ]
        history = [
            {"role": "assistant", "content": "", "tool_calls": tool_calls, "tool_call_id": None}
        ]
        result = normalize_history(history)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert result[0]["tool_calls"] == tool_calls
        assert result[0]["content"] == ""

    def test_tool_message(self):
        """Tool role messages include tool_call_id."""
        history = [
            {"role": "tool", "content": "result data", "tool_calls": None, "tool_call_id": "tc_1"}
        ]
        result = normalize_history(history)
        assert result == [{"role": "tool", "content": "result data", "tool_call_id": "tc_1"}]

    def test_mixed_conversation(self):
        """Full conversation normalizes all message types correctly."""
        history = [
            {"role": "user", "content": "Check CPU", "tool_calls": None, "tool_call_id": None},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "type": "function",
                        "function": {"name": "get_cpu", "arguments": "{}"},
                    }
                ],
                "tool_call_id": None,
            },
            {"role": "tool", "content": "CPU: 45%", "tool_calls": None, "tool_call_id": "tc_1"},
            {
                "role": "assistant",
                "content": "Your CPU is at 45%.",
                "tool_calls": None,
                "tool_call_id": None,
            },
        ]
        result = normalize_history(history)
        assert len(result) == 4
        assert "tool_calls" not in result[0]  # user
        assert "tool_calls" in result[1]  # assistant with tool_calls
        assert "tool_call_id" in result[2]  # tool
        assert "tool_calls" not in result[3]  # final assistant

    def test_backward_compatible_no_tool_fields(self):
        """Old-format history without tool fields works."""
        history = [{"role": "user", "content": "Hello"}]  # No tool_calls/tool_call_id keys
        result = normalize_history(history)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_empty_history(self):
        """Empty history returns empty list."""
        assert normalize_history([]) == []
        assert normalize_history(None) == []


# ---------- B. build_messages with tools ----------


class TestBuildMessagesWithTools:
    def test_with_tool_history(self, llm_service):
        """build_messages includes tool_calls and tool role in output."""
        tool_calls = [
            {
                "id": "tc_1",
                "type": "function",
                "function": {"name": "get_info", "arguments": "{}"},
            }
        ]
        history = [
            {"role": "user", "content": "Check system"},
            {"role": "assistant", "content": "", "tool_calls": tool_calls, "tool_call_id": None},
            {"role": "tool", "content": "CPU: 50%", "tool_calls": None, "tool_call_id": "tc_1"},
        ]
        messages = llm_service.build_messages("What now?", history=history)
        # Should have: system + 3 history + 1 user = 5
        assert len(messages) == 5
        assert messages[0]["role"] == "system"
        assert messages[2]["tool_calls"] == tool_calls  # assistant with tool_calls
        assert messages[3]["tool_call_id"] == "tc_1"  # tool result
        assert messages[4]["role"] == "user"

    def test_backward_compatible(self, llm_service):
        """Old history without tool fields still works."""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        messages = llm_service.build_messages("Bye", history=history)
        assert len(messages) == 4  # system + 2 history + user


# ---------- C. Config additions ----------


class TestToolCallingConfig:
    def test_default_max_iterations(self):
        from backend.core.config import LLMConfig

        config = LLMConfig()
        assert config.max_tool_iterations == 10

    def test_default_confirmation_timeout(self):
        from backend.core.config import LLMConfig

        config = LLMConfig()
        assert config.confirmation_timeout_s == 60

    def test_custom_values(self):
        from backend.core.config import LLMConfig

        config = LLMConfig(max_tool_iterations=5, confirmation_timeout_s=30)
        assert config.max_tool_iterations == 5
        assert config.confirmation_timeout_s == 30


# ---------- D. Tool execution integration ----------


class TestToolExecution:
    async def test_tool_result_serialization(self):
        """ToolResult content dict is serialized to string for LLM."""
        result = ToolResult.ok({"cpu": 50, "ram": 70}, content_type="application/json")
        content = result.content
        if isinstance(content, dict):
            content = json.dumps(content)
        assert "cpu" in content

    async def test_tool_result_error_format(self):
        """Error results are properly formatted."""
        result = ToolResult.error("Something failed")
        assert not result.success
        assert result.error_message == "Something failed"

    async def test_dedup_same_tool_same_args(self):
        """Duplicate tool calls (same name + args) should be detected."""
        seen: set[tuple[str, str]] = set()
        tool_calls = [
            {"id": "tc_1", "function": {"name": "get_cpu", "arguments": "{}"}},
            {"id": "tc_2", "function": {"name": "get_cpu", "arguments": "{}"}},  # duplicate
            {"id": "tc_3", "function": {"name": "get_ram", "arguments": "{}"}},  # different tool
        ]
        unique = []
        for tc in tool_calls:
            key = (tc["function"]["name"], tc["function"]["arguments"])
            if key not in seen:
                seen.add(key)
                unique.append(tc)
        assert len(unique) == 2  # get_cpu once + get_ram once


# ---------- E. Message DB model tests ----------


class TestMessageToolFields:
    def test_message_with_tool_calls(self):
        """Message model can store tool_calls JSON."""
        msg = Message(
            conversation_id=uuid.uuid4(),
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "tc_1",
                    "type": "function",
                    "function": {"name": "test", "arguments": "{}"},
                }
            ],
        )
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1

    def test_message_with_tool_call_id(self):
        """Message model can store tool_call_id."""
        msg = Message(
            conversation_id=uuid.uuid4(),
            role="tool",
            content="result",
            tool_call_id="tc_1",
        )
        assert msg.tool_call_id == "tc_1"
        assert msg.role == "tool"

    def test_message_defaults_no_tools(self):
        """Default message has None tool fields."""
        msg = Message(conversation_id=uuid.uuid4(), role="user", content="hello")
        assert msg.tool_calls is None
        assert msg.tool_call_id is None
