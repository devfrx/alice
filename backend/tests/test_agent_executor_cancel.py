"""Cooperative cancellation mid-loop."""

from __future__ import annotations

import asyncio

import pytest

from backend.services.agent.models import TaskComplexity, Verdict, VerdictAction
from backend.services.turn.models import TurnInput, TurnResult
from backend.services.turn.sink import RecordingEventSink

from ._agent_helpers import (
    MockDirect,
    build_executor,
    make_agent_cfg,
    make_agent_turn,
    simple_plan,
)


@pytest.mark.asyncio
async def test_cancel_event_breaks_loop_after_step() -> None:
    cancel_event = asyncio.Event()

    def _trip_cancel(_turn: TurnInput) -> None:
        cancel_event.set()

    direct = MockDirect(
        results=[
            TurnResult(
                content="primo step",
                thinking="",
                input_tokens=3,
                output_tokens=1,
                finish_reason="stop",
                had_tool_calls=False,
            )
        ],
        on_call=_trip_cancel,
    )
    plan = simple_plan("uno", "due", "tre")
    verdicts = [Verdict(action=VerdictAction.OK, reason="ok")]
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.MULTI_STEP,
        plans=[plan],
        verdicts=verdicts,
        cfg=make_agent_cfg(save_runs=False),
    )
    sink = RecordingEventSink()

    result = await executor.execute(
        turn=make_agent_turn(),
        sink=sink,
        cancel_event=cancel_event,
        session=None,
    )

    # Only the first step executed before cancel was observed.
    assert len(direct.calls) == 1
    assert result.finish_reason == "cancelled"
    assert sink.events[-1]["type"] == "agent.run_finished"
    assert sink.events[-1]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_set_before_first_step_aborts_immediately() -> None:
    direct = MockDirect()
    plan = simple_plan("uno", "due")
    verdicts = [Verdict(action=VerdictAction.OK, reason="ok")]
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.MULTI_STEP,
        plans=[plan],
        verdicts=verdicts,
        cfg=make_agent_cfg(save_runs=False),
    )
    sink = RecordingEventSink()

    cancel_event = asyncio.Event()
    cancel_event.set()

    result = await executor.execute(
        turn=make_agent_turn(),
        sink=sink,
        cancel_event=cancel_event,
        session=None,
    )

    assert direct.calls == []
    assert result.finish_reason == "cancelled"
    assert sink.events[-1]["state"] == "cancelled"
