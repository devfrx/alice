"""Unit tests for ``PlannerService`` (Phase 2 of agent loop)."""

from __future__ import annotations

import pytest

from backend.services.agent import Plan, PlannerConfig, PlannerService

from ._recording_llm import RecordingLLM


_VALID_PLAN_JSON = (
    '{"goal":"riassumi e invia",'
    '"steps":['
    '{"index":0,"description":"leggi il file","expected_outcome":"contenuto","tool_hint":"read_file"},'
    '{"index":1,"description":"invia email","expected_outcome":"email ok","tool_hint":"send_email"}'
    "]}"
)


def _tools() -> list[dict]:
    """Two minimal OpenAI-format tool entries for prompt assembly."""
    return [
        {"type": "function", "function": {"name": "read_file"}},
        {"type": "function", "function": {"name": "send_email"}},
    ]


@pytest.mark.asyncio
async def test_plan_valid_json_parses_into_plan() -> None:
    """A clean JSON object must parse into a fully-validated Plan."""
    llm = RecordingLLM([_VALID_PLAN_JSON])
    svc = PlannerService(llm, PlannerConfig())

    plan = await svc.plan(goal="riassumi e invia", available_tools=_tools())

    assert isinstance(plan, Plan)
    assert plan.goal == "riassumi e invia"
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_hint == "read_file"
    assert plan.steps[1].index == 1


@pytest.mark.asyncio
async def test_plan_extracts_json_from_surrounding_prose() -> None:
    """Models often wrap JSON in extra text — we should still recover it."""
    wrapped = "Ecco il piano:\n" + _VALID_PLAN_JSON + "\nFine."
    llm = RecordingLLM([wrapped])
    svc = PlannerService(llm, PlannerConfig())

    plan = await svc.plan(goal="riassumi e invia", available_tools=_tools())

    assert len(plan.steps) == 2


@pytest.mark.asyncio
async def test_plan_invalid_json_falls_back_to_single_step() -> None:
    """Malformed output -> single-step fallback restating the goal."""
    llm = RecordingLLM(["this is not JSON at all"])
    svc = PlannerService(llm, PlannerConfig())

    plan = await svc.plan(goal="fai qualcosa", available_tools=_tools())

    assert plan.goal == "fai qualcosa"
    assert len(plan.steps) == 1
    assert plan.steps[0].index == 0
    assert plan.steps[0].description == "fai qualcosa"
    assert plan.steps[0].expected_outcome == "risposta diretta"


@pytest.mark.asyncio
async def test_plan_llm_error_falls_back() -> None:
    """LLM exception must produce a fallback plan, never raise."""
    llm = RecordingLLM([], raise_on=0)
    svc = PlannerService(llm, PlannerConfig())

    plan = await svc.plan(goal="goal", available_tools=_tools())

    assert len(plan.steps) == 1


@pytest.mark.asyncio
async def test_plan_uses_remaining_goal_when_provided() -> None:
    """Re-planning should focus on the residual goal."""
    llm = RecordingLLM(["nope"])
    svc = PlannerService(llm, PlannerConfig())

    plan = await svc.plan(
        goal="originale",
        available_tools=_tools(),
        remaining_goal="solo step 2",
    )

    assert plan.goal == "solo step 2"


@pytest.mark.asyncio
async def test_plan_require_json_object_strengthens_system_prompt() -> None:
    """The require_json_object flag must reach the LLM via the system prompt."""
    llm = RecordingLLM([_VALID_PLAN_JSON])
    cfg = PlannerConfig(require_json_object=True, max_output_tokens=400)
    svc = PlannerService(llm, cfg)

    await svc.plan(goal="g", available_tools=_tools())

    call = llm.calls[0]
    assert call["max_output_tokens"] == 400
    assert "JSON" in (call["system_prompt"] or "")
    assert "ESCLUSIVAMENTE" in (call["system_prompt"] or "")


@pytest.mark.asyncio
async def test_plan_user_prompt_lists_tool_names() -> None:
    """The prompt must surface the tool names so the planner can pick them."""
    llm = RecordingLLM([_VALID_PLAN_JSON])
    svc = PlannerService(llm, PlannerConfig())

    await svc.plan(goal="g", available_tools=_tools())

    user_msg = llm.calls[0]["messages"][0]["content"]
    assert "read_file" in user_msg
    assert "send_email" in user_msg


@pytest.mark.asyncio
async def test_plan_history_summary_appears_in_prompt() -> None:
    """The optional history summary must be embedded in the user prompt."""
    llm = RecordingLLM([_VALID_PLAN_JSON])
    svc = PlannerService(llm, PlannerConfig())

    await svc.plan(
        goal="g",
        available_tools=_tools(),
        history_summary="step 0 fatto",
    )

    user_msg = llm.calls[0]["messages"][0]["content"]
    assert "step 0 fatto" in user_msg
