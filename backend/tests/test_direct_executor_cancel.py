"""Cancel-path tests for :class:`DirectTurnExecutor`.

Covers FIX v3-2 from ``agent_loop_plan.md``: when ``cancel_event`` is
set during the initial stream, the executor must return
``finish_reason="cancelled"`` regardless of the LLM's emitted reason.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.sink import RecordingEventSink

from ._turn_helpers import StreamingMockLLM, make_ctx, make_turn


@pytest.mark.asyncio
async def test_cancel_set_before_execute_returns_cancelled() -> None:
    """Cancel already set: the post-stream check overrides finish_reason."""
    llm = StreamingMockLLM(events=[{"type": "done", "finish_reason": "stop"}])
    executor = DirectTurnExecutor(make_ctx(), llm)
    cancel_event = asyncio.Event()
    cancel_event.set()

    result = await executor.execute(
        turn=make_turn(),
        sink=RecordingEventSink(),
        cancel_event=cancel_event,
        session=None,
    )

    assert result.finish_reason == "cancelled"
    assert result.had_tool_calls is False


@pytest.mark.asyncio
async def test_cancel_set_during_stream_short_circuits() -> None:
    """Setting cancel between yields short-circuits the stream cleanly."""

    async def _events_then_cancel():
        cancel_event_holder["evt"].set()
        return None

    cancel_event_holder: dict[str, asyncio.Event] = {}

    class _LateLLM:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def chat(self, messages, **kwargs):
            self.calls.append({"messages": messages, **kwargs})
            yield {"type": "token", "content": "partial"}
            cancel_event_holder["evt"].set()
            yield {"type": "token", "content": "ignored"}
            yield {"type": "done", "finish_reason": "stop"}

    cancel_event_holder["evt"] = asyncio.Event()
    sink = RecordingEventSink()
    executor = DirectTurnExecutor(make_ctx(), _LateLLM())

    result = await executor.execute(
        turn=make_turn(),
        sink=sink,
        cancel_event=cancel_event_holder["evt"],
        session=None,
    )

    # Cancel takes precedence even though the LLM emitted "stop".
    assert result.finish_reason == "cancelled"
    # Partial content collected up to the cancel signal is preserved.
    assert "partial" in result.content
