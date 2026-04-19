"""Unit tests for ``CriticService`` (Phase 2 of agent loop)."""

from __future__ import annotations

import pytest

from backend.services.agent import (
    CriticConfig,
    CriticService,
    Plan,
    Step,
    Verdict,
    VerdictAction,
)

from ._recording_llm import RecordingLLM


def _plan() -> Plan:
    """One-step plan used as the context argument."""
    return Plan(
        goal="g",
        steps=[Step(index=0, description="d", expected_outcome="e")],
    )


def _step() -> Step:
    """The step under evaluation in every test."""
    return Step(index=0, description="d", expected_outcome="e")


def _verdict_json(action: str, *, question: str | None = None) -> str:
    """Build a minimal verdict JSON document for the mock LLM."""
    q = "null" if question is None else f'"{question}"'
    return f'{{"action":"{action}","reason":"because","question":{q}}}'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action_value,expected",
    [
        ("ok", VerdictAction.OK),
        ("retry", VerdictAction.RETRY),
        ("replan", VerdictAction.REPLAN),
        ("abort", VerdictAction.ABORT),
    ],
)
async def test_evaluate_parses_each_action(
    action_value: str, expected: VerdictAction,
) -> None:
    """Every non-ASK_USER action token must round-trip into a Verdict."""
    llm = RecordingLLM([_verdict_json(action_value)])
    svc = CriticService(llm, CriticConfig())

    verdict = await svc.evaluate(
        step=_step(), output="ok", plan=_plan(), retries_used=0,
    )

    assert isinstance(verdict, Verdict)
    assert verdict.action == expected


@pytest.mark.asyncio
async def test_evaluate_ask_user_carries_question() -> None:
    """ASK_USER verdicts must preserve the clarifying question."""
    llm = RecordingLLM([_verdict_json("ask_user", question="quale file?")])
    svc = CriticService(llm, CriticConfig())

    verdict = await svc.evaluate(
        step=_step(), output="ambiguo", plan=_plan(), retries_used=0,
    )

    assert verdict.action == VerdictAction.ASK_USER
    assert verdict.question == "quale file?"


@pytest.mark.asyncio
async def test_evaluate_extracts_json_from_surrounding_prose() -> None:
    """Stray prose around the JSON object must not block parsing."""
    llm = RecordingLLM(["Verdict:\n" + _verdict_json("ok") + "\n--"])
    svc = CriticService(llm, CriticConfig())

    verdict = await svc.evaluate(
        step=_step(), output="ok", plan=_plan(), retries_used=0,
    )

    assert verdict.action == VerdictAction.OK


@pytest.mark.asyncio
async def test_evaluate_fail_open_returns_ok_on_parse_error() -> None:
    """With fail_open=True, malformed output yields OK (don't block user)."""
    llm = RecordingLLM(["not json"])
    svc = CriticService(llm, CriticConfig(fail_open=True))

    verdict = await svc.evaluate(
        step=_step(), output="?", plan=_plan(), retries_used=0,
    )

    assert verdict.action == VerdictAction.OK
    assert "fail-open" in verdict.reason


@pytest.mark.asyncio
async def test_evaluate_fail_closed_returns_retry_on_parse_error() -> None:
    """With fail_open=False, malformed output yields RETRY."""
    llm = RecordingLLM(["still not json"])
    svc = CriticService(llm, CriticConfig(fail_open=False))

    verdict = await svc.evaluate(
        step=_step(), output="?", plan=_plan(), retries_used=0,
    )

    assert verdict.action == VerdictAction.RETRY
    assert "fail-closed" in verdict.reason


@pytest.mark.asyncio
async def test_evaluate_llm_error_uses_fallback() -> None:
    """LLM exception must degrade to fallback, never raise."""
    llm = RecordingLLM([], raise_on=0)
    svc = CriticService(llm, CriticConfig(fail_open=True))

    verdict = await svc.evaluate(
        step=_step(), output="?", plan=_plan(), retries_used=0,
    )

    assert verdict.action == VerdictAction.OK


@pytest.mark.asyncio
async def test_evaluate_user_prompt_includes_retries_and_output() -> None:
    """The critic prompt must surface step metadata, output, retry count."""
    llm = RecordingLLM([_verdict_json("ok")])
    svc = CriticService(llm, CriticConfig())

    await svc.evaluate(
        step=_step(), output="risultato xyz", plan=_plan(), retries_used=2,
    )

    user_msg = llm.calls[0]["messages"][0]["content"]
    assert "risultato xyz" in user_msg
    assert "Retry usati per questo step: 2" in user_msg
    assert "Step #0" in user_msg
