"""Streaming-only tests for :class:`DirectTurnExecutor`.

Verifies that token / thinking / done events flow into the
:class:`RecordingEventSink` in the exact order produced by the LLM,
that ``TurnResult`` carries the accumulated content and finish reason,
and that the ``was_compressed`` flag forces ``user_content=None`` on
the LLM call (FIX v2-2 / §3.5 of ``agent_loop_plan.md``).
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.sink import RecordingEventSink

from ._turn_helpers import StreamingMockLLM, make_ctx, make_turn


@pytest.mark.asyncio
async def test_stream_relays_tokens_and_done_in_order() -> None:
    """Token/thinking events flow through the sink and aggregate in result."""
    llm = StreamingMockLLM(
        events=[
            {"type": "token", "content": "Ciao "},
            {"type": "thinking", "content": "(reasoning)"},
            {"type": "token", "content": "mondo"},
            {"type": "usage", "input_tokens": 12, "output_tokens": 3},
            {"type": "done", "finish_reason": "stop"},
        ],
    )
    sink = RecordingEventSink()
    executor = DirectTurnExecutor(make_ctx(), llm)

    result = await executor.execute(
        turn=make_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    types = [e["type"] for e in sink.events]
    assert types == ["token", "thinking", "token"]
    assert sink.events[0]["content"] == "Ciao "
    assert sink.events[2]["content"] == "mondo"

    assert result.content == "Ciao mondo"
    assert result.thinking == "(reasoning)"
    assert result.input_tokens == 12
    assert result.output_tokens == 3
    assert result.finish_reason == "stop"
    assert result.had_tool_calls is False
    assert result.final_assistant_message_id is None


@pytest.mark.asyncio
async def test_stream_was_compressed_forces_user_content_none() -> None:
    """``was_compressed=True`` must suppress ``user_content`` on llm.chat (v2-2)."""
    llm = StreamingMockLLM(events=[{"type": "done", "finish_reason": "stop"}])
    executor = DirectTurnExecutor(make_ctx(), llm)

    await executor.execute(
        turn=make_turn(was_compressed=True),
        sink=RecordingEventSink(),
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert llm.calls[0]["user_content"] is None


@pytest.mark.asyncio
async def test_stream_default_passes_user_content_through() -> None:
    """When NOT compressed, ``user_content`` must reach the LLM unchanged."""
    llm = StreamingMockLLM(events=[{"type": "done", "finish_reason": "stop"}])
    executor = DirectTurnExecutor(make_ctx(), llm)

    await executor.execute(
        turn=make_turn(user_content="hello"),
        sink=RecordingEventSink(),
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert llm.calls[0]["user_content"] == "hello"


@pytest.mark.asyncio
async def test_stream_propagates_finish_reason_length() -> None:
    """Non-default ``finish_reason`` from done event surfaces in TurnResult."""
    llm = StreamingMockLLM(
        events=[
            {"type": "token", "content": "long"},
            {"type": "done", "finish_reason": "length"},
        ],
    )
    executor = DirectTurnExecutor(make_ctx(), llm)

    result = await executor.execute(
        turn=make_turn(),
        sink=RecordingEventSink(),
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert result.finish_reason == "length"
