"""ASK_USER verdict short-circuits the agent loop."""

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
async def test_ask_user_breaks_loop_with_event() -> None:
    direct = MockDirect(
        results=[
            TurnResult(
                content="parziale",
                thinking="",
                input_tokens=4,
                output_tokens=1,
                finish_reason="stop",
                had_tool_calls=False,
            )
        ]
    )
    plan = simple_plan("step1", "step2", "step3")
    verdicts = [
        Verdict(
            action=VerdictAction.ASK_USER,
            reason="serve un dato",
            question="Qual è la data?",
        ),
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

    # Only the first step ran.
    assert len(direct.calls) == 1
    assert result.finish_reason == "asked_user"

    types = [e["type"] for e in sink.events]
    assert "agent.ask_user" in types
    ask_event = next(e for e in sink.events if e["type"] == "agent.ask_user")
    assert ask_event["question"] == "Qual è la data?"
    assert sink.events[-1]["type"] == "agent.run_finished"
    assert sink.events[-1]["state"] == "asked_user"
