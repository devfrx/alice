"""Structural intent-mismatch detector in the MULTI_STEP loop.

When the planner declares ``step.tool_hint`` and the inner LLM finishes
the step *without* emitting a tool call, the executor must:

  * skip the critic LLM call entirely;
  * emit ``agent.warning`` with code ``intent_mismatch_no_tool``;
  * yield ``Verdict(action=REPLAN, source='detector', ...)``.

For the SINGLE_TOOL bypass path, missing tool_call yields the soft
``bypass_single_tool_no_call`` warning (non-blocking).
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
)


def _no_tool_call(content: str = "rispondo a parole") -> TurnResult:
    return TurnResult(
        content=content,
        thinking="",
        input_tokens=4,
        output_tokens=2,
        finish_reason="stop",
        had_tool_calls=False,
    )


def _with_tool_call(content: str = "ho chiamato il tool") -> TurnResult:
    return TurnResult(
        content=content,
        thinking="",
        input_tokens=4,
        output_tokens=2,
        finish_reason="stop",
        had_tool_calls=True,
    )


@pytest.mark.asyncio
async def test_step_with_tool_hint_no_tool_call_replans_without_critic() -> None:
    """tool_hint set + had_tool_calls=False → REPLAN by detector, no critic."""
    direct = MockDirect(
        results=[
            _no_tool_call("ho ignorato il tool"),
            _with_tool_call("recupero ed eseguo lo step"),
        ]
    )
    plan = Plan(
        goal="goal",
        steps=[
            Step(
                index=0,
                description="usa lo strumento",
                expected_outcome="risposta dal tool",
                tool_hint="web_search",
            ),
        ],
    )
    # The replan path will request a fresh plan — provide a one-step
    # successor so the loop terminates cleanly.
    successor = Plan(
        goal="goal",
        steps=[
            Step(
                index=0,
                description="prosegui",
                expected_outcome="esito",
                tool_hint=None,
            ),
        ],
    )
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.MULTI_STEP,
        plans=[plan, successor],
        # Only ONE critic verdict needed — the detector short-circuits the
        # LLM call on the first step, so the critic only runs on step #2.
        verdicts=[Verdict(action=VerdictAction.OK, reason="ok", source="llm")],
        cfg=make_agent_cfg(save_runs=False, max_replans=1),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    # The critic must have been invoked at most once (step #2 only).
    critic_calls = executor._critic.calls  # type: ignore[attr-defined]
    assert len(critic_calls) <= 1

    types = [e["type"] for e in sink.events]
    assert "agent.warning" in types
    warn = next(
        e for e in sink.events
        if e["type"] == "agent.warning" and e["code"] == "intent_mismatch_no_tool"
    )
    assert "invocato" in warn["message"].lower() or "tool" in warn["message"].lower()

    # The detector verdict surfaced via agent.step_completed.
    completed = next(e for e in sink.events if e["type"] == "agent.step_completed")
    verdict_dump = completed["verdict"]
    assert verdict_dump["action"] == "replan"
    assert verdict_dump["source"] == "detector"
    assert "strumento" in verdict_dump["reason"].lower()


@pytest.mark.asyncio
async def test_step_without_tool_hint_does_not_warn() -> None:
    """tool_hint=None must let the critic run normally (no warning)."""
    direct = MockDirect(default=_no_tool_call())
    plan = Plan(
        goal="g",
        steps=[Step(index=0, description="d", expected_outcome="e", tool_hint=None)],
    )
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.MULTI_STEP,
        plans=[plan],
        verdicts=[Verdict(action=VerdictAction.OK, reason="ok", source="llm")],
        cfg=make_agent_cfg(save_runs=False),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    # Critic actually ran.
    assert len(executor._critic.calls) == 1  # type: ignore[attr-defined]
    warn_codes = [
        e["code"] for e in sink.events if e["type"] == "agent.warning"
    ]
    assert "intent_mismatch_no_tool" not in warn_codes


@pytest.mark.asyncio
async def test_bypass_single_tool_no_call_emits_soft_warning() -> None:
    """SINGLE_TOOL bypass without tool_call must surface a soft warning."""
    direct = MockDirect(default=_no_tool_call("ho risposto a parole"))
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.SINGLE_TOOL,
        cfg=make_agent_cfg(save_runs=False),
    )
    sink = RecordingEventSink()

    await executor.execute(
        turn=make_agent_turn(), sink=sink,
        cancel_event=asyncio.Event(), session=None,
    )

    warn_codes = [
        e["code"] for e in sink.events if e["type"] == "agent.warning"
    ]
    assert "bypass_single_tool_no_call" in warn_codes
