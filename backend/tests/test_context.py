"""Tests for backend.core.context and backend.services.context_manager."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.core.config import AliceConfig, LLMConfig
from backend.core.context import AppContext, create_context
from backend.core.event_bus import EventBus
from backend.services.context_manager import (
    CompressionError,
    ContextManager,
    ContextUsage,
)


# ---------------------------------------------------------------------------
# AppContext tests
# ---------------------------------------------------------------------------


def test_create_context_returns_app_context(config: AliceConfig) -> None:
    ctx = create_context(config)
    assert isinstance(ctx, AppContext)


def test_create_context_has_config_and_event_bus(config: AliceConfig) -> None:
    ctx = create_context(config)
    assert ctx.config is config
    assert isinstance(ctx.event_bus, EventBus)


def test_optional_fields_default_to_none(config: AliceConfig) -> None:
    ctx = create_context(config)
    assert ctx.db is None
    assert ctx.plugin_manager is None
    assert ctx.llm_service is None
    assert ctx.stt_service is None
    assert ctx.tts_service is None


# ---------------------------------------------------------------------------
# ContextManager — helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(
        context_compression_enabled=True,
        context_compression_threshold=0.75,
        context_compression_reserve=4096,
    )


@pytest.fixture
def cm(llm_config: LLMConfig) -> ContextManager:
    return ContextManager(llm_config)


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


def test_estimate_tokens_empty_string(cm: ContextManager) -> None:
    assert cm.estimate_tokens("") == 1


def test_estimate_tokens_short_string(cm: ContextManager) -> None:
    assert cm.estimate_tokens("hi") == 1  # 2 // 4 == 0, max(1,0)==1


def test_estimate_tokens_normal(cm: ContextManager) -> None:
    assert cm.estimate_tokens("a" * 100) == 25


# ---------------------------------------------------------------------------
# estimate_message_tokens
# ---------------------------------------------------------------------------


def test_estimate_message_tokens_none_content(cm: ContextManager) -> None:
    """Messages with content=None (e.g. tool_call messages) must not crash."""
    msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]}
    tokens = cm.estimate_message_tokens(msg)
    assert tokens > 4  # overhead + tool_calls


def test_estimate_message_tokens_missing_content(cm: ContextManager) -> None:
    msg = {"role": "user"}
    tokens = cm.estimate_message_tokens(msg)
    assert tokens == 4 + 1  # overhead + estimate_tokens("")


def test_estimate_message_tokens_tool_calls_string(cm: ContextManager) -> None:
    msg = {"role": "assistant", "content": "", "tool_calls": '{"fn":"a"}'}
    tokens = cm.estimate_message_tokens(msg)
    assert tokens > 4


def test_estimate_message_tokens_multimodal_content(cm: ContextManager) -> None:
    """Multimodal content (list of parts) must not crash and account for images."""
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }
    tokens = cm.estimate_message_tokens(msg)
    # 4 (overhead) + text tokens + 765 (image flat cost)
    assert tokens > 765


# ---------------------------------------------------------------------------
# get_usage_estimated / get_usage_real — boundary conditions
# ---------------------------------------------------------------------------


def test_get_usage_estimated_zero_context_window(cm: ContextManager) -> None:
    usage = cm.get_usage_estimated([{"role": "user", "content": "hi"}], 0)
    assert usage.percentage == 0.0
    assert usage.available_tokens == 0
    assert usage.is_estimated is True


def test_get_usage_real_zero_context_window(cm: ContextManager) -> None:
    usage = cm.get_usage_real(100, 0)
    assert usage.percentage == 0.0
    assert usage.available_tokens == 0
    assert usage.is_estimated is False


def test_get_usage_real_normal(cm: ContextManager) -> None:
    usage = cm.get_usage_real(4000, 8000)
    assert usage.used_tokens == 4000
    assert usage.available_tokens == 4000
    assert usage.percentage == 0.5


# ---------------------------------------------------------------------------
# should_compress
# ---------------------------------------------------------------------------


def test_should_compress_below_threshold(cm: ContextManager) -> None:
    usage = ContextUsage(
        used_tokens=5000, available_tokens=5000,
        context_window=10000, percentage=0.50,
        was_compressed=False, messages_summarized=0, is_estimated=True,
    )
    assert cm.should_compress(usage) is False


def test_should_compress_at_threshold(cm: ContextManager) -> None:
    usage = ContextUsage(
        used_tokens=7500, available_tokens=2500,
        context_window=10000, percentage=0.75,
        was_compressed=False, messages_summarized=0, is_estimated=True,
    )
    assert cm.should_compress(usage) is True


def test_should_compress_reserve_trigger(cm: ContextManager) -> None:
    """Low available tokens trigger compression even below percentage."""
    usage = ContextUsage(
        used_tokens=5000, available_tokens=3000,
        context_window=10000, percentage=0.50,
        was_compressed=False, messages_summarized=0, is_estimated=True,
    )
    assert cm.should_compress(usage) is True  # 3000 <= 4096 reserve


# ---------------------------------------------------------------------------
# compress — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compress_too_few_messages(cm: ContextManager) -> None:
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
    ]
    with pytest.raises(CompressionError, match="Not enough messages"):
        await cm.compress(msgs, AsyncMock(), 8192, 1024)


@pytest.mark.asyncio
async def test_compress_too_few_conv_messages(cm: ContextManager) -> None:
    msgs = [
        {"role": "system", "content": "a"},
        {"role": "system", "content": "b"},
        {"role": "system", "content": "c"},
        {"role": "user", "content": "hi"},
    ]
    with pytest.raises(CompressionError, match="Not enough conversation"):
        await cm.compress(msgs, AsyncMock(), 8192, 1024)


@pytest.mark.asyncio
async def test_compress_empty_summary_raises(cm: ContextManager) -> None:
    llm = AsyncMock()
    llm.complete_nonstreaming.return_value = "   "
    pad = "x" * 400  # ~100 tokens per message
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
    ]
    with pytest.raises(CompressionError, match="empty summary"):
        await cm.compress(msgs, llm, 1000, 200)


@pytest.mark.asyncio
async def test_compress_success(cm: ContextManager) -> None:
    llm = AsyncMock()
    llm.complete_nonstreaming.return_value = "Summary of earlier conversation."
    pad = "x" * 400
    msgs = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
    ]
    result = await cm.compress(msgs, llm, 1000, 200)
    assert result.usage.was_compressed is True
    assert result.usage.messages_summarized > 0
    assert "[Context summary of" in result.messages[1]["content"]


@pytest.mark.asyncio
async def test_compress_handles_none_content(cm: ContextManager) -> None:
    """Messages with content=None in archive must not crash."""
    llm = AsyncMock()
    llm.complete_nonstreaming.return_value = "Summary OK."
    pad = "x" * 400
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": pad},
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
    ]
    result = await cm.compress(msgs, llm, 1000, 200)
    assert result.usage.was_compressed is True


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_config_threshold_clamped_above_1() -> None:
    cfg = LLMConfig(context_compression_threshold=1.5)
    assert cfg.context_compression_threshold == 0.95


def test_config_threshold_clamped_below_0() -> None:
    cfg = LLMConfig(context_compression_threshold=-0.5)
    assert cfg.context_compression_threshold == 0.50


def test_config_reserve_clamped_negative() -> None:
    cfg = LLMConfig(context_compression_reserve=-100)
    assert cfg.context_compression_reserve == 512


# ---------------------------------------------------------------------------
# _filter_history_for_llm
# ---------------------------------------------------------------------------


def test_filter_history_excludes_context_excluded_keeps_summary() -> None:
    """context_excluded messages are dropped; is_context_summary messages survive."""
    from backend.api.routes.chat import _filter_history_for_llm

    raw = [
        {"role": "system", "content": "sys", "_db_pos": 0},
        {"role": "user", "content": "old question", "context_excluded": True, "_db_pos": 1},
        {
            "role": "assistant",
            "content": "[Context summary of 2 earlier messages]:\nSummary.",
            "context_excluded": True,
            "is_context_summary": True,
            "_db_pos": 2,
        },
        {"role": "user", "content": "new question", "_db_pos": 3},
    ]
    result = _filter_history_for_llm(raw, {})
    contents = [m.get("content", "") for m in result]

    # system + summary + new user = 3 messages
    assert len(result) == 3
    assert "old question" not in contents
    assert any("[Context summary of" in c for c in contents)
    # All internal metadata fields must be stripped
    for m in result:
        assert "context_excluded" not in m
        assert "is_context_summary" not in m
        assert "_db_pos" not in m


def test_filter_history_summary_not_neutralized_by_step4() -> None:
    """Short context summary messages must never be replaced with [Incomplete response]."""
    from backend.api.routes.chat import _filter_history_for_llm

    # A summary whose total length is < 80 chars and doesn't end with punctuation
    summary_content = "[Context summary of 1 earlier messages]:\nOK"
    raw = [
        {"role": "system", "content": "s", "_db_pos": 0},
        {
            "role": "assistant",
            "content": summary_content,
            "is_context_summary": True,
            "_db_pos": 1,
        },
        {"role": "user", "content": "hi", "_db_pos": 2},
    ]
    result = _filter_history_for_llm(raw, {})
    assert any("[Context summary of" in (m.get("content") or "") for m in result), (
        "Summary was wrongly neutralized by step 4"
    )


# ---------------------------------------------------------------------------
# compress — tool_tokens and prior summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compress_tool_tokens_affects_target_budget(cm: ContextManager) -> None:
    """tool_tokens are subtracted from the compression target budget."""
    llm_no_tools = AsyncMock()
    llm_no_tools.complete_nonstreaming.return_value = "Summary A."
    llm_with_tools = AsyncMock()
    llm_with_tools.complete_nonstreaming.return_value = "Summary B."

    pad = "x" * 400
    msgs = [
        {"role": "system", "content": "sys"},
        *[
            {"role": "user" if i % 2 == 0 else "assistant", "content": pad}
            for i in range(6)
        ],
    ]
    # Use a small context window so compression always triggers.
    # target_tokens (no tools) = int(800 * 0.60) - 200 = 280.
    # target_tokens (500 tool tokens) = 280 - 500 = -220 → capped by min keep.
    res_no_tools = await cm.compress(msgs, llm_no_tools, 800, 200, tool_tokens=0)
    res_with_tools = await cm.compress(msgs, llm_with_tools, 800, 200, tool_tokens=500)

    # With tool_tokens the target budget is effectively exhausted, so
    # the minimum keep (2) applies → more messages are archived.
    assert res_with_tools.split_index >= res_no_tools.split_index
    # Usage returned must account for tool tokens.
    assert res_with_tools.usage.used_tokens >= 500


@pytest.mark.asyncio
async def test_compress_prior_summary_in_archive_text(cm: ContextManager) -> None:
    """A second compression must include any prior summary in the archive prompt."""
    from typing import Any

    captured: list[list[dict[str, Any]]] = []

    async def _capture(messages: list[dict[str, Any]], **kwargs: Any) -> str:
        captured.append(messages)
        return "New summary."

    llm = AsyncMock()
    llm.complete_nonstreaming.side_effect = _capture

    pad = "x" * 400
    msgs = [
        {"role": "system", "content": "sys"},
        {
            "role": "assistant",
            "content": "[Context summary of 3 earlier messages]:\nOld summary.",
        },
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
        {"role": "user", "content": pad},
        {"role": "assistant", "content": pad},
        {"role": "user", "content": pad},
    ]
    await cm.compress(msgs, llm, 1000, 200)

    assert captured, "LLM was not called"
    archive_content = captured[0][1]["content"]
    assert "[Previous summary]" in archive_content, (
        "Prior summary was not included in the compression prompt"
    )
