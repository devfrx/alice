"""REPLAN flow of :class:`AgentTurnExecutor`.

The first verdict is REPLAN; the planner returns a fresh plan; the run
proceeds with the spliced-in tail.  Asserts the planner is called twice
and that the AgentRun (in-memory only here — persistence off) is
reflected in the emitted events.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services.agent.models import (
    Plan,
    Step,
    TaskComplexity,
    Verdict,
    VerdictAction,
)
from backend.services.turn.models import TurnResult
from backend.services.turn.sink import RecordingEventSink

from ._agent_helpers import (
    MockDirect,
    build_executor,
    make_agent_cfg,
    make_agent_turn,
    simple_plan,
)


def _ok_result(text: str) -> TurnResult:
    return TurnResult(
        content=text,
        thinking="",
        input_tokens=5,
        output_tokens=1,
        finish_reason="stop",
        had_tool_calls=False,
    )


@pytest.mark.asyncio
async def test_replan_invokes_planner_twice_and_emits_event() -> None:
    direct = MockDirect(
        results=[
            _ok_result("step iniziale"),
            _ok_result("step replan-1"),
        ]
    )
    initial_plan = simple_plan("vecchio")
    new_tail = Plan(
        goal="goal",
        steps=[Step(index=0, description="nuovo", expected_outcome="esito")],
    )
    verdicts = [
        Verdict(action=VerdictAction.REPLAN, reason="cambio rotta"),
        Verdict(action=VerdictAction.OK, reason="ok"),
    ]
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.MULTI_STEP,
        plans=[initial_plan, new_tail],
        verdicts=verdicts,
        cfg=make_agent_cfg(save_runs=False, max_replans=2),
    )
    sink = RecordingEventSink()

    result = await executor.execute(
        turn=make_agent_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    # Planner called twice (initial + replan).
    assert len(executor._planner.calls) == 2  # type: ignore[attr-defined]
    # Two direct executions: original step + appended step from replan.
    assert len(direct.calls) == 2

    types = [e["type"] for e in sink.events]
    assert "agent.replanned" in types
    assert types[-1] == "agent.run_finished"
    assert sink.events[-1]["state"] == "done"
    assert result.finish_reason == "stop"
