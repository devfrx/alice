"""Disconnect / LLM-error tests for :class:`DirectTurnExecutor`.

Covers:
    * FIX v2-4: ``WebSocketDisconnect`` raised mid-stream is captured
      and surfaces as ``TurnResult(finish_reason="disconnected")``;
      ``ws_chat`` then handles partial-content recovery without an
      exception escaping the executor.
    * FIX v3-5: a generic LLM exception is captured, the sink receives
      an ``error`` event with detail, and the result reports
      ``finish_reason="error"``.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import WebSocketDisconnect

from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.sink import RecordingEventSink

from ._turn_helpers import StreamingMockLLM, make_ctx, make_turn


@pytest.mark.asyncio
async def test_disconnect_during_stream_returns_disconnected() -> None:
    """``WebSocketDisconnect`` from llm.chat -> finish_reason='disconnected'."""

    class _DisconnectingLLM:
        async def chat(self, messages, **kwargs):
            yield {"type": "token", "content": "before"}
            raise WebSocketDisconnect()

    sink = RecordingEventSink()
    executor = DirectTurnExecutor(make_ctx(), _DisconnectingLLM())

    result = await executor.execute(
        turn=make_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert result.finish_reason == "disconnected"
    # Disconnect during initial stream returns empty content per the
    # executor contract — recovery of any pre-disconnect text is the
    # caller's responsibility (handled in ws_chat).
    assert result.content == ""
    assert result.had_tool_calls is False


@pytest.mark.asyncio
async def test_llm_error_during_stream_emits_error_event() -> None:
    """Generic LLM exception -> sink error event + finish_reason='error'."""
    llm = StreamingMockLLM(raise_exc=RuntimeError("boom"))
    sink = RecordingEventSink()
    executor = DirectTurnExecutor(make_ctx(), llm)

    result = await executor.execute(
        turn=make_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert result.finish_reason == "error"
    assert any(e.get("type") == "error" for e in sink.events)


@pytest.mark.asyncio
async def test_llm_streaming_error_event_marks_finish_error() -> None:
    """An ``error`` event yielded by llm.chat must set finish_reason='error'."""
    llm = StreamingMockLLM(
        events=[
            {"type": "token", "content": "x"},
            {"type": "error", "content": "model unloaded"},
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

    assert result.finish_reason == "error"
    # The error event must have been forwarded to the sink.
    assert any(
        e.get("type") == "error" and e.get("content") == "model unloaded"
        for e in sink.events
    )
