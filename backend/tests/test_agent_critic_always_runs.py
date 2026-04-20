"""Tests for the always-on critic on bypass paths of ``AgentTurnExecutor``.

When ``cfg.critic.always_run`` is true the critic must run after every
direct execution — including the TRIVIAL / OPEN_ENDED / SINGLE_TOOL
bypass branches — and emit ``agent.critic_invoked`` events.  Recovery
behaviour is also exercised: SINGLE_TOOL with a REPLAN verdict must
promote the turn to a mini-plan handled by the multi-step machinery.
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


def _stop_result(content: str = "ok") -> TurnResult:
    return TurnResult(
        content=content,
        thinking="",
        input_tokens=10,
        output_tokens=2,
        finish_reason="stop",
        had_tool_calls=False,
    )


# ---------------------------------------------------------------------------
# TRIVIAL / OPEN_ENDED with always_run=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "complexity",
    [TaskComplexity.TRIVIAL, TaskComplexity.OPEN_ENDED],
)
async def test_critic_runs_on_trivial_and_open_ended(complexity: TaskComplexity) -> None:
    """Critic + critic_invoked event must fire on bypass paths when enabled."""
    direct = MockDirect(default=_stop_result("risposta breve"))
    executor = build_executor(
        direct=direct,
        complexity=complexity,
        verdicts=[Verdict(action=VerdictAction.OK, reason="ok", source="llm")],
        cfg=make_agent_cfg(critic_always_run=True),
    )
    sink = RecordingEventSink()

    result = await executor.execute(
        turn=make_agent_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert len(direct.calls) == 1
    assert result.content == "risposta breve"
    # Critic must have been invoked exactly once.
    assert len(executor._critic.calls) == 1  # type: ignore[attr-defined]
    types = [e["type"] for e in sink.events]
    assert "agent.critic_invoked" in types
    # New contract: bypass paths with critic on emit run_started{mode=bypass}.
    assert "agent.run_started" in types
    run_started = next(e for e in sink.events if e["type"] == "agent.run_started")
    assert run_started["mode"] == "bypass"
    assert run_started["plan"] is None
    assert run_started["total_steps"] == 0


@pytest.mark.asyncio
async def test_critic_disabled_keeps_legacy_bypass() -> None:
    """``critic_always_run=False`` must restore the original silent bypass."""
    direct = MockDirect(default=_stop_result())
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.TRIVIAL,
        cfg=make_agent_cfg(critic_always_run=False),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    assert len(executor._critic.calls) == 0  # type: ignore[attr-defined]
    assert all(not e["type"].startswith("agent.") for e in sink.events)


@pytest.mark.asyncio
async def test_critic_non_ok_on_trivial_emits_warning() -> None:
    """A non-OK critic on TRIVIAL must surface ``agent.warning`` (no recovery)."""
    direct = MockDirect(default=_stop_result("risposta sospetta"))
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.TRIVIAL,
        verdicts=[
            Verdict(action=VerdictAction.REPLAN, reason="ripetizione", source="detector"),
        ],
        cfg=make_agent_cfg(critic_always_run=True),
    )
    sink = RecordingEventSink()

    result = await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    assert result.content == "risposta sospetta"  # original returned untouched
    types = [e["type"] for e in sink.events]
    assert "agent.warning" in types
    warn = next(e for e in sink.events if e["type"] == "agent.warning")
    assert warn["code"] == "degenerated_output"


# ---------------------------------------------------------------------------
# SINGLE_TOOL with always_run=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critic_runs_on_single_tool() -> None:
    """SINGLE_TOOL must invoke the critic and emit critic_invoked + run events."""
    direct = MockDirect(default=_stop_result("tool ok"))
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.SINGLE_TOOL,
        verdicts=[Verdict(action=VerdictAction.OK, reason="ok", source="llm")],
        cfg=make_agent_cfg(critic_always_run=True, save_runs=False),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    assert len(executor._critic.calls) == 1  # type: ignore[attr-defined]
    types = [e["type"] for e in sink.events]
    assert "agent.run_started" in types
    assert "agent.critic_invoked" in types
    assert "agent.run_finished" in types


@pytest.mark.asyncio
async def test_single_tool_retry_on_critic_retry_verdict() -> None:
    """RETRY verdict must re-run direct.execute up to max_retries_per_step."""
    direct = MockDirect(
        results=[_stop_result("tentativo 1"), _stop_result("tentativo 2")],
        default=_stop_result("tentativo finale"),
    )
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.SINGLE_TOOL,
        verdicts=[
            Verdict(action=VerdictAction.RETRY, reason="non valida", source="llm"),
            Verdict(action=VerdictAction.OK, reason="ok", source="llm"),
        ],
        cfg=make_agent_cfg(
            critic_always_run=True, max_retries_per_step=2, save_runs=False,
        ),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    # Second direct.execute carries the reinforcement nudge.
    assert len(direct.calls) == 2
    last_msg = direct.calls[1].messages[-1]["content"]
    assert "Retry 1" in last_msg
    # Two critic calls (initial + post-retry).
    assert len(executor._critic.calls) == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_single_tool_replan_promotes_to_multi_step() -> None:
    """REPLAN verdict on SINGLE_TOOL must trigger the multi-step machinery."""
    direct = MockDirect(default=_stop_result("contenuto pianificato"))
    plan = simple_plan("step pianificato")
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.SINGLE_TOOL,
        plans=[plan],
        verdicts=[
            # First (bypass) verdict requests REPLAN -> promotion.
            Verdict(action=VerdictAction.REPLAN, reason="serve un piano", source="llm"),
            # Verdict for the single planned step in the multi-step loop.
            Verdict(action=VerdictAction.OK, reason="ok", source="llm"),
        ],
        cfg=make_agent_cfg(critic_always_run=True, save_runs=False),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    types = [e["type"] for e in sink.events]
    # Promotion warning + plan_created from the multi-step path.
    assert "agent.warning" in types
    assert any(
        e.get("code") == "single_tool_promoted"
        for e in sink.events
        if e["type"] == "agent.warning"
    )
    assert "agent.plan_created" in types
    assert "agent.step_started" in types
    assert "agent.step_completed" in types
