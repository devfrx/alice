"""Bypass paths of :class:`AgentTurnExecutor`.

TRIVIAL / OPEN_ENDED classifications must delegate 1:1 to the wrapped
:class:`DirectTurnExecutor` and must NOT persist an :class:`AgentRun`
row nor emit any ``agent.*`` event.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services.agent.models import TaskComplexity
from backend.services.turn.models import TurnResult
from backend.services.turn.sink import RecordingEventSink

from ._agent_helpers import (
    MockDirect,
    build_executor,
    make_agent_cfg,
    make_agent_turn,
)


def _direct_result() -> TurnResult:
    return TurnResult(
        content="diretto",
        thinking="",
        input_tokens=11,
        output_tokens=3,
        finish_reason="stop",
        had_tool_calls=False,
    )


@pytest.mark.asyncio
async def test_trivial_delegates_to_direct() -> None:
    direct = MockDirect(default=_direct_result())
    executor = build_executor(direct=direct, complexity=TaskComplexity.TRIVIAL)
    sink = RecordingEventSink()

    result = await executor.execute(
        turn=make_agent_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert len(direct.calls) == 1
    assert result.content == "diretto"
    assert result.agent_run_id is None
    assert all(not e["type"].startswith("agent.") for e in sink.events)


@pytest.mark.asyncio
async def test_open_ended_delegates_to_direct() -> None:
    direct = MockDirect(default=_direct_result())
    executor = build_executor(direct=direct, complexity=TaskComplexity.OPEN_ENDED)
    sink = RecordingEventSink()

    result = await executor.execute(
        turn=make_agent_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert len(direct.calls) == 1
    assert result.content == "diretto"
    assert result.agent_run_id is None


@pytest.mark.asyncio
async def test_no_tools_bypasses_classifier() -> None:
    """When no tools are wired in, the classifier is never even invoked."""
    direct = MockDirect(default=_direct_result())
    executor = build_executor(direct=direct, complexity=TaskComplexity.MULTI_STEP)
    sink = RecordingEventSink()

    result = await executor.execute(
        turn=make_agent_turn(tools=[]),  # empty tools triggers bypass
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert len(direct.calls) == 1
    assert result.agent_run_id is None
    # Bypass happens BEFORE the classifier call, so no calls were recorded.
    assert executor._classifier.calls == []  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_classifier_disabled_bypasses_loop() -> None:
    direct = MockDirect(default=_direct_result())
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.MULTI_STEP,
        cfg=make_agent_cfg(classifier_enabled=False),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert len(direct.calls) == 1
    assert all(not e["type"].startswith("agent.") for e in sink.events)
