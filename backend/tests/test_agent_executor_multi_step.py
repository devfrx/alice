"""MULTI_STEP strategy of :class:`AgentTurnExecutor`.

Two-step plan, classifier returns MULTI_STEP, both critic verdicts OK.

Asserts:
    * the planner runs once and the critic twice,
    * :meth:`MockDirect.execute` is invoked once per step,
    * each step's sub-turn carries the step prompt + accumulated context,
    * the agent.* event sequence is well-formed,
    * the final :class:`TurnResult` aggregates contents/tokens correctly,
    * (no DB) the run id is ``None`` because persistence is off.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services.agent.models import TaskComplexity, Verdict, VerdictAction
from backend.services.turn.models import TurnResult
from backend.services.turn.sink import RecordingEventSink

from ._agent_helpers import (
    MockDirect,
    build_executor,
    make_agent_cfg,
    make_agent_turn,
    simple_plan,
)


@pytest.mark.asyncio
async def test_multi_step_runs_each_step_with_critic() -> None:
    direct = MockDirect(
        results=[
            TurnResult(
                content="risultato A",
                thinking="rA",
                input_tokens=10,
                output_tokens=2,
                finish_reason="stop",
                had_tool_calls=True,
            ),
            TurnResult(
                content="risultato B",
                thinking="rB",
                input_tokens=12,
                output_tokens=3,
                finish_reason="stop",
                had_tool_calls=False,
            ),
        ]
    )
    plan = simple_plan("primo step", "secondo step")
    verdicts = [
        Verdict(action=VerdictAction.OK, reason="ok 1"),
        Verdict(action=VerdictAction.OK, reason="ok 2"),
    ]
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
        cancel_event=asyncio.Event(),
        session=None,
    )

    # Two delegated direct executions.
    assert len(direct.calls) == 2

    # First sub-turn embeds step 0 prompt; second includes accumulated A.
    first_msgs = direct.calls[0].messages
    assert "[Agent step 1]" in first_msgs[-1]["content"]
    assert "primo step" in first_msgs[-1]["content"]
    second_msgs = direct.calls[1].messages
    assert "[Agent step 2]" in second_msgs[-1]["content"]
    assert "risultato A" in second_msgs[-1]["content"]

    # Critic invoked once per step.
    assert len(executor._critic.calls) == 2  # type: ignore[attr-defined]

    # Event sequence well-formed.
    types = [e["type"] for e in sink.events]
    assert types[0] == "agent.run_started"
    assert types[1] == "agent.plan_created"
    step_started = [i for i, t in enumerate(types) if t == "agent.step_started"]
    step_completed = [
        i for i, t in enumerate(types) if t == "agent.step_completed"
    ]
    assert len(step_started) == 2
    assert len(step_completed) == 2
    assert types[-1] == "agent.run_finished"
    assert sink.events[-1]["state"] == "done"

    # Aggregated result.
    assert "risultato A" in result.content and "risultato B" in result.content
    assert result.input_tokens == 22
    assert result.output_tokens == 5
    assert result.finish_reason == "stop"
    assert result.had_tool_calls is True
    assert result.agent_run_id is None
