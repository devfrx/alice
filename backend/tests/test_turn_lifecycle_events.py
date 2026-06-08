"""AL\\CE — Tests for additive turn-lifecycle event emission (Fase 3 E).

Pins the behaviour wired in Task 3.2a: the turn engine emits the canonical
``turn.started`` / ``turn.llm_step`` / ``turn.usage`` / ``turn.finished``
frames *additively* (alongside the legacy ad-hoc frames) with a single stable
``turn_id`` per turn and accurate step / tool-call counters.

Two complementary surfaces are exercised:

* :class:`DirectTurnExecutor` no-tool path — owns ``turn.started`` /
  ``turn.finished`` and the step-1 ``turn.llm_step`` / ``turn.usage``.
* :func:`run_tool_loop` — owns the per-iteration ``turn.llm_step`` /
  ``turn.usage`` frames (it never emits ``turn.started`` / ``turn.finished``).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.sink import RecordingEventSink
from backend.services.turn.tool_loop import run_tool_loop

from ._turn_helpers import StreamingMockLLM, make_ctx, make_turn
from .test_tool_loop import (
    MockLLM,
    MockSession,
    MockToolRegistry,
    MockWebSocket,
    _Ctx,
    _tc,
)

# ---------------------------------------------------------------------------
# Executor — no-tool path (owns turn.started / turn.finished)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_no_tool_path_emits_full_lifecycle() -> None:
    """A plain token+done turn emits started/llm_step/usage/finished once."""
    llm = StreamingMockLLM(
        events=[
            {"type": "token", "content": "Hello"},
            {"type": "usage", "input_tokens": 10, "output_tokens": 5},
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

    started = [e for e in sink.events if e.get("type") == "turn.started"]
    steps = [e for e in sink.events if e.get("type") == "turn.llm_step"]
    usages = [e for e in sink.events if e.get("type") == "turn.usage"]
    finished = [e for e in sink.events if e.get("type") == "turn.finished"]

    # Exactly one start / step / finish; at least one usage (step 1).
    assert len(started) == 1
    assert len(steps) == 1
    assert steps[0]["step"] == 1
    assert len(usages) >= 1
    assert usages[0]["step"] == 1
    assert usages[0]["tool_calls"] == 0
    assert usages[0]["max_steps"] == 5  # max_tool_iterations(4) + 1
    assert usages[0]["input_tokens"] == 10
    assert usages[0]["output_tokens"] == 5
    assert len(finished) == 1
    assert finished[0]["finish_reason"] == "stop"
    assert finished[0]["input_tokens"] == 10
    assert finished[0]["output_tokens"] == 5
    assert finished[0]["steps"] == 1

    # All four lifecycle frames share one stable turn_id.
    turn_ids = {
        e["turn_id"] for e in started + steps + usages + finished
    }
    assert len(turn_ids) == 1

    # turn.started precedes turn.finished in the emitted stream.
    types = [e.get("type") for e in sink.events]
    assert types.index("turn.started") < types.index("turn.finished")
    # The legacy ``token`` frame is preserved (additive, not replaced).
    # (``done`` / ``usage`` LLM events are consumed internally by the
    # executor and never forwarded to the sink — only ``token`` is.)
    assert "token" in types
    # turn.started must come before the first legacy stream frame.
    assert types.index("turn.started") < types.index("token")

    # Sanity: the existing return contract is unchanged.
    assert result.finish_reason == "stop"
    assert result.content == "Hello"


@pytest.mark.asyncio
async def test_executor_error_path_still_finishes() -> None:
    """An LLM error short-circuit still emits a terminal turn.finished."""
    # No trailing ``done``: a ``done`` after the error would reset
    # finish_reason back to "stop" (mirrors real stream semantics).
    llm = StreamingMockLLM(
        events=[
            {"type": "token", "content": "partial"},
            {"type": "error", "content": "boom"},
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

    started = [e for e in sink.events if e.get("type") == "turn.started"]
    finished = [e for e in sink.events if e.get("type") == "turn.finished"]
    assert len(started) == 1
    assert len(finished) == 1
    assert finished[0]["finish_reason"] == "error"
    assert started[0]["turn_id"] == finished[0]["turn_id"]
    assert result.finish_reason == "error"


# ---------------------------------------------------------------------------
# Tool loop — per-iteration llm_step / usage (no started / finished)
# ---------------------------------------------------------------------------


async def _run_loop(
    tool_calls: list[dict],
    llm_responses: list[list[dict]],
    *,
    max_iterations: int = 5,
) -> MockWebSocket:
    """Drive ``run_tool_loop`` with default mocks (no ``turn_progress``)."""
    ws = MockWebSocket()
    await run_tool_loop(
        channel=ws,
        sink=ws,
        ctx=_Ctx(MockToolRegistry()),
        session=MockSession(),
        conv_id=uuid.uuid4(),
        llm=MockLLM(llm_responses),
        tool_calls_from_llm=tool_calls,
        full_content="",
        thinking_content="",
        max_iterations=max_iterations,
        confirmation_timeout_s=2,
        client_ip="127.0.0.1",
        sync_fn=None,
    )
    return ws


@pytest.mark.asyncio
async def test_tool_loop_emits_llm_step_and_usage_with_minted_turn_id() -> None:
    """One tool call → step-1 llm_step + usage with a self-minted turn_id."""
    ws = await _run_loop(
        [_tc("tool_a")],
        [[
            {"type": "token", "content": "Final answer."},
            {"type": "usage", "input_tokens": 42, "output_tokens": 7},
            {"type": "done", "finish_reason": "stop"},
        ]],
    )

    steps = [m for m in ws.sent if m.get("type") == "turn.llm_step"]
    usages = [m for m in ws.sent if m.get("type") == "turn.usage"]

    assert len(steps) == 1
    assert steps[0]["step"] == 1
    assert len(usages) == 1
    assert usages[0]["step"] == 1
    assert usages[0]["tool_calls"] == 1  # one tool dispatched this turn
    assert usages[0]["max_steps"] == 6   # max_iterations(5) + 1
    assert usages[0]["input_tokens"] == 42
    assert usages[0]["output_tokens"] == 7

    # The loop minted its own turn_id; every lifecycle frame shares it.
    turn_ids = {m["turn_id"] for m in steps + usages}
    assert len(turn_ids) == 1
    assert turn_ids.pop()  # non-empty

    # Additive: the legacy llm_requery frame is still emitted.
    assert any(m.get("type") == "llm_requery" for m in ws.sent)


@pytest.mark.asyncio
async def test_tool_loop_steps_increase_across_iterations() -> None:
    """Two iterations → llm_step/usage steps increase 1→2, tool_calls 1→2."""
    ws = await _run_loop(
        [_tc("tool_a")],
        [
            # iteration 1 re-query: requests another tool call → continue.
            [
                {"type": "tool_call", "id": "call_b",
                 "function": {"name": "tool_b", "arguments": "{}"}},
                {"type": "usage", "input_tokens": 10, "output_tokens": 2},
                {"type": "done", "finish_reason": "tool_calls"},
            ],
            # iteration 2 re-query: final answer → stop.
            [
                {"type": "token", "content": "Done."},
                {"type": "usage", "input_tokens": 20, "output_tokens": 3},
                {"type": "done", "finish_reason": "stop"},
            ],
        ],
    )

    steps = [m for m in ws.sent if m.get("type") == "turn.llm_step"]
    usages = [m for m in ws.sent if m.get("type") == "turn.usage"]

    assert [m["step"] for m in steps] == [1, 2]
    assert [m["step"] for m in usages] == [1, 2]
    # Cumulative tool-call counter: tool_a then tool_b.
    assert [m["tool_calls"] for m in usages] == [1, 2]

    turn_ids = {m["turn_id"] for m in steps + usages}
    assert len(turn_ids) == 1
