"""``agent.run_started`` carries ``mode={"agent","bypass"}``.

Bypass paths (TRIVIAL/OPEN_ENDED/SINGLE_TOOL/no_tools) must NOT emit
``agent.plan_created`` / ``agent.step_started``.  The MULTI_STEP path
keeps emitting the full event stream and reports ``mode='agent'``.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.services.agent.models import (
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


def _ok(content: str = "ok", *, had_tool_calls: bool = True) -> TurnResult:
    return TurnResult(
        content=content,
        thinking="",
        input_tokens=1,
        output_tokens=1,
        finish_reason="stop",
        had_tool_calls=had_tool_calls,
    )


# ---------------------------------------------------------------------------
# SINGLE_TOOL bypass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_tool_emits_run_started_with_mode_bypass() -> None:
    direct = MockDirect(default=_ok())
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.SINGLE_TOOL,
        cfg=make_agent_cfg(save_runs=False),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    run_started = next(e for e in sink.events if e["type"] == "agent.run_started")
    assert run_started["mode"] == "bypass"
    assert run_started["plan"] is None
    assert run_started["total_steps"] == 0

    types = [e["type"] for e in sink.events]
    assert "agent.plan_created" not in types
    assert "agent.step_started" not in types


# ---------------------------------------------------------------------------
# TRIVIAL/OPEN_ENDED bypass with critic on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "complexity", [TaskComplexity.TRIVIAL, TaskComplexity.OPEN_ENDED],
)
async def test_trivial_and_open_ended_emit_bypass_mode(
    complexity: TaskComplexity,
) -> None:
    direct = MockDirect(default=_ok(had_tool_calls=False))
    executor = build_executor(
        direct=direct,
        complexity=complexity,
        verdicts=[Verdict(action=VerdictAction.OK, reason="ok", source="llm")],
        cfg=make_agent_cfg(critic_always_run=True),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    run_started = next(e for e in sink.events if e["type"] == "agent.run_started")
    assert run_started["mode"] == "bypass"
    assert run_started["plan"] is None
    assert run_started["total_steps"] == 0

    types = [e["type"] for e in sink.events]
    assert "agent.plan_created" not in types
    assert "agent.step_started" not in types
    assert "agent.critic_invoked" in types
    assert "agent.run_finished" in types


# ---------------------------------------------------------------------------
# MULTI_STEP keeps mode='agent'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_step_emits_run_started_with_mode_agent() -> None:
    direct = MockDirect(results=[_ok("a"), _ok("b")])
    plan = simple_plan("step1", "step2")
    verdicts = [
        Verdict(action=VerdictAction.OK, reason="ok", source="llm"),
        Verdict(action=VerdictAction.OK, reason="ok", source="llm"),
    ]
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.MULTI_STEP,
        plans=[plan],
        verdicts=verdicts,
        cfg=make_agent_cfg(save_runs=False),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    run_started = next(e for e in sink.events if e["type"] == "agent.run_started")
    assert run_started["mode"] == "agent"
    types = [e["type"] for e in sink.events]
    # MULTI_STEP keeps the full event stream.
    assert "agent.plan_created" in types
    assert "agent.step_started" in types
