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

    from backend.core.config import PROJECT_ROOT

    return LLMConfig(
        base_url="http://localhost:11434",
        model="test-model",
        system_prompt_file=str(PROJECT_ROOT / "config" / "system_prompt.md"),
        max_tool_iterations=10,
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
        assert config.max_tool_iterations == 25

    def test_default_confirmation_timeout(self):
        from backend.core.config import PcAutomationConfig

        config = PcAutomationConfig()
        assert config.confirmation_timeout_s == 60

    def test_custom_values(self):
        from backend.core.config import LLMConfig, PcAutomationConfig

        llm_config = LLMConfig(max_tool_iterations=5)
        assert llm_config.max_tool_iterations == 5

        pc_config = PcAutomationConfig(confirmation_timeout_s=30)
        assert pc_config.confirmation_timeout_s == 30


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


# ---------- F. SSE streaming — reasoning_content tests ----------


def _sse_line(delta: dict, finish_reason: str | None = None) -> str:
    """Build a single SSE data line from a delta dict."""
    choice: dict = {"delta": delta}
    if finish_reason:
        choice["finish_reason"] = finish_reason
    return f"data: {json.dumps({'choices': [choice]})}"


class _FakeStreamResponse:
    """Fake httpx streaming response that yields pre-built SSE lines."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _make_llm(*, supports_thinking: bool) -> LLMService:
    """Create an LLMService with a fake system prompt and given thinking flag."""
    from backend.core.config import LLMConfig, PROJECT_ROOT

    cfg = LLMConfig(
        base_url="http://localhost:1234",
        model="test-model",
        system_prompt_file=str(PROJECT_ROOT / "config" / "system_prompt.md"),
        supports_thinking=supports_thinking,
    )
    return LLMService(cfg)


async def _collect_events(
    llm: LLMService, lines: list[str],
) -> list[dict]:
    """Run LLMService.chat() against fake SSE lines, return all events."""
    fake_resp = _FakeStreamResponse(lines)

    with patch.object(llm._client, "stream", return_value=fake_resp):
        events = []
        async for event in llm.chat(
            [{"role": "user", "content": "hi"}],
        ):
            events.append(event)
    return events


class TestReasoningContentStreaming:
    """Verify reasoning_content in SSE deltas is always yielded."""

    @pytest.mark.asyncio
    async def test_reasoning_content_yielded_when_thinking_disabled(self):
        """reasoning_content in SSE delta → thinking event even with supports_thinking=False."""
        llm = _make_llm(supports_thinking=False)
        lines = [
            _sse_line({"reasoning_content": "Let me think..."}),
            _sse_line({"content": "The answer is 42."}),
            _sse_line({}, finish_reason="stop"),
            "data: [DONE]",
        ]
        events = await _collect_events(llm, lines)

        thinking_events = [e for e in events if e["type"] == "thinking"]
        token_events = [e for e in events if e["type"] == "token"]
        done_events = [e for e in events if e["type"] == "done"]

        assert len(thinking_events) == 1
        assert thinking_events[0]["content"] == "Let me think..."
        assert len(token_events) == 1
        assert token_events[0]["content"] == "The answer is 42."
        assert len(done_events) == 1

    @pytest.mark.asyncio
    async def test_reasoning_content_yielded_when_thinking_enabled(self):
        """reasoning_content in SSE delta → thinking event with supports_thinking=True."""
        llm = _make_llm(supports_thinking=True)
        lines = [
            _sse_line({"reasoning_content": "Step 1: analyze"}),
            _sse_line({"content": "Result here."}),
            _sse_line({}, finish_reason="stop"),
            "data: [DONE]",
        ]
        events = await _collect_events(llm, lines)

        thinking_events = [e for e in events if e["type"] == "thinking"]
        token_events = [e for e in events if e["type"] == "token"]

        assert len(thinking_events) == 1
        assert thinking_events[0]["content"] == "Step 1: analyze"
        assert len(token_events) == 1
        assert token_events[0]["content"] == "Result here."

    @pytest.mark.asyncio
    async def test_both_reasoning_and_content_in_same_delta(self):
        """A single delta with both reasoning_content and content yields both events."""
        llm = _make_llm(supports_thinking=False)
        lines = [
            _sse_line({
                "reasoning_content": "thinking part",
                "content": "visible part",
            }),
            _sse_line({}, finish_reason="stop"),
            "data: [DONE]",
        ]
        events = await _collect_events(llm, lines)

        thinking_events = [e for e in events if e["type"] == "thinking"]
        token_events = [e for e in events if e["type"] == "token"]

        assert len(thinking_events) == 1
        assert thinking_events[0]["content"] == "thinking part"
        assert len(token_events) == 1
        assert token_events[0]["content"] == "visible part"

    @pytest.mark.asyncio
    async def test_think_tags_always_parsed_regardless_of_config(self):
        """Inline <think> tags are parsed even when supports_thinking=False.

        The ``supports_thinking`` flag controls API-level reasoning
        requests, not inline tag detection — tags are always stripped.
        """
        llm = _make_llm(supports_thinking=False)
        lines = [
            _sse_line({"content": "<think>some reasoning</think>The answer"}),
            _sse_line({}, finish_reason="stop"),
            "data: [DONE]",
        ]
        events = await _collect_events(llm, lines)

        token_events = [e for e in events if e["type"] == "token"]
        thinking_events = [e for e in events if e["type"] == "thinking"]

        # ThinkTagParser is always active → tags extracted
        assert len(thinking_events) == 1
        assert thinking_events[0]["content"] == "some reasoning"
        assert len(token_events) == 1
        assert token_events[0]["content"] == "The answer"

    @pytest.mark.asyncio
    async def test_think_tags_parsed_when_thinking_enabled(self):
        """Inline <think> tags are separated into thinking events when enabled."""
        llm = _make_llm(supports_thinking=True)
        lines = [
            _sse_line({"content": "<think>reasoning</think>answer"}),
            _sse_line({}, finish_reason="stop"),
            "data: [DONE]",
        ]
        events = await _collect_events(llm, lines)

        thinking_events = [e for e in events if e["type"] == "thinking"]
        token_events = [e for e in events if e["type"] == "token"]

        assert len(thinking_events) == 1
        assert thinking_events[0]["content"] == "reasoning"
        assert len(token_events) == 1
        assert token_events[0]["content"] == "answer"
