"""Tool-loop dispatch tests for :class:`DirectTurnExecutor`.

The executor delegates to :func:`backend.api.routes._tool_loop.run_tool_loop`
when the LLM emits at least one ``tool_call`` event.  The tool-loop path now
requires an :class:`InteractionChannel`, so we exercise two complementary
scenarios:

* **Refuse-to-loop fast path** — with no channel (``channel is None``)
  the executor must NOT call ``run_tool_loop`` and must return
  ``finish_reason="error"`` along with ``had_tool_calls=True``.  This
  protects production code from silently dropping tool calls when the
  channel is missing.
* **Patched ``run_tool_loop``** — with the helper monkey-patched and a
  channel supplied, the executor delegates exactly once and propagates the
  loop's tuple result (content, thinking, tokens, finish_reason).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

import backend.api.routes._tool_loop as tool_loop_mod
from backend.services.turn.channel import ScriptedInteractionChannel
from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.sink import RecordingEventSink

from ._turn_helpers import StreamingMockLLM, make_ctx, make_turn


def _tool_call_event() -> dict[str, Any]:
    """Build a synthetic ``tool_call`` event consumed by the executor."""
    return {
        "type": "tool_call",
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "name": "noop",
        "arguments": "{}",
    }


@pytest.mark.asyncio
async def test_tool_calls_with_recording_sink_short_circuit_to_error() -> None:
    """Recording sink has no real WebSocket -> executor must refuse safely."""
    llm = StreamingMockLLM(
        events=[
            {"type": "token", "content": "thinking..."},
            _tool_call_event(),
            {"type": "done", "finish_reason": "tool_calls"},
        ],
    )
    sink = RecordingEventSink()
    executor = DirectTurnExecutor(make_ctx(), llm)

    result = await executor.execute(
        turn=make_turn(tools=[{"type": "function", "function": {"name": "noop"}}]),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert result.had_tool_calls is True
    assert result.finish_reason == "error"


@pytest.mark.asyncio
async def test_tool_calls_delegate_to_run_tool_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a real WS is available, run_tool_loop runs and its tuple wins."""
    captured: dict[str, Any] = {}

    async def _fake_loop(**kwargs: Any) -> tuple[str, str, int, int, str]:
        captured.update(kwargs)
        return ("final answer", "post-thinking", 100, 50, "stop")

    monkeypatch.setattr(tool_loop_mod, "run_tool_loop", _fake_loop)

    llm = StreamingMockLLM(
        events=[
            _tool_call_event(),
            {"type": "done", "finish_reason": "tool_calls"},
        ],
    )

    sink = RecordingEventSink()
    executor = DirectTurnExecutor(make_ctx(), llm)

    # A non-None channel is what enables the tool-loop path now (the
    # patched run_tool_loop never touches it).
    result = await executor.execute(
        turn=make_turn(tools=[{"type": "function", "function": {"name": "noop"}}]),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
        channel=ScriptedInteractionChannel(),
    )

    assert captured, "run_tool_loop was never invoked"
    assert captured["max_iterations"] == 4  # from make_ctx
    assert captured["tools"] is not None

    assert result.content == "final answer"
    assert result.thinking == "post-thinking"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.finish_reason == "stop"
    assert result.had_tool_calls is True


@pytest.mark.asyncio
async def test_tool_loop_cancel_overrides_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v3-2: cancel set during tool loop -> finish_reason becomes 'cancelled'."""
    cancel_event = asyncio.Event()

    async def _fake_loop(**kwargs: Any) -> tuple[str, str, int, int, str]:
        cancel_event.set()  # simulate cancel during tool execution
        return ("partial", "", 5, 1, "stop")

    monkeypatch.setattr(tool_loop_mod, "run_tool_loop", _fake_loop)

    llm = StreamingMockLLM(
        events=[
            _tool_call_event(),
            {"type": "done", "finish_reason": "tool_calls"},
        ],
    )
    executor = DirectTurnExecutor(make_ctx(), llm)

    result = await executor.execute(
        turn=make_turn(tools=[{"type": "function", "function": {"name": "noop"}}]),
        sink=RecordingEventSink(),
        cancel_event=cancel_event,
        session=None,
        channel=ScriptedInteractionChannel(),
    )

    assert result.finish_reason == "cancelled"
    assert result.had_tool_calls is True
