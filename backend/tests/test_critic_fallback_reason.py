"""Critic fallback verdicts must use plain italian, user-facing reasons.

The implementation reserves technical detail (parse exception, raw
output …) for ``logger.warning`` and only surfaces conservative,
non-jargon italian sentences via :class:`Verdict.reason`.
"""

from __future__ import annotations

import pytest

from backend.services.agent import (
    CriticConfig,
    CriticService,
    Plan,
    Step,
    VerdictAction,
)

from ._recording_llm import RecordingLLM


def _plan() -> Plan:
    return Plan(
        goal="g", steps=[Step(index=0, description="d", expected_outcome="e")],
    )


@pytest.mark.asyncio
async def test_fallback_open_returns_italian_reason() -> None:
    """fail_open=True + JSON parse fail → reason='Verifica completata.'"""
    llm = RecordingLLM(["definitely not json"])
    svc = CriticService(llm, CriticConfig(fail_open=True))

    verdict = await svc.evaluate(
        step=Step(index=0, description="d", expected_outcome="e"),
        output="output",
        plan=_plan(),
        retries_used=0,
    )

    assert verdict.action == VerdictAction.OK
    assert verdict.reason == "Verifica completata."
    assert verdict.source == "fallback"
    # No technical jargon must leak into reason.
    assert "fail-open" not in verdict.reason.lower()
    assert "parse" not in verdict.reason.lower()


@pytest.mark.asyncio
async def test_fallback_closed_returns_italian_reason() -> None:
    """fail_open=False + parse fail → reason='Verifica non riuscita...'"""
    llm = RecordingLLM(["still not json"])
    svc = CriticService(llm, CriticConfig(fail_open=False))

    verdict = await svc.evaluate(
        step=Step(index=0, description="d", expected_outcome="e"),
        output="output",
        plan=_plan(),
        retries_used=0,
    )

    assert verdict.action == VerdictAction.RETRY
    assert verdict.reason == "Verifica non riuscita, riprovo lo step."
    assert verdict.source == "fallback"


@pytest.mark.asyncio
async def test_fallback_on_llm_exception_keeps_italian_reason() -> None:
    """An LLM exception must produce the same italian fallback reason."""
    llm = RecordingLLM([], raise_on=0)
    svc = CriticService(llm, CriticConfig(fail_open=True))

    verdict = await svc.evaluate(
        step=Step(index=0, description="d", expected_outcome="e"),
        output="output",
        plan=_plan(),
        retries_used=0,
    )

    assert verdict.action == VerdictAction.OK
    assert verdict.reason == "Verifica completata."
    assert verdict.source == "fallback"
