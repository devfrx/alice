"""Shared helpers for ``AgentTurnExecutor`` unit tests.

Provides:
    * :class:`MockDirect` — drop-in for :class:`DirectTurnExecutor` whose
      ``execute`` returns canned :class:`TurnResult`s.
    * Helpers to build mock classifier / planner / critic services and
      a fully assembled :class:`AgentTurnExecutor` instance.
    * :func:`make_agent_turn` — :class:`TurnInput` factory mirroring the
      direct-executor helper but defaulting to a non-empty ``tools``
      list so the executor doesn't bypass on the "no tools" guard.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable

from backend.services.agent import AgentComponents
from backend.services.agent.models import (
    Plan,
    Step,
    TaskComplexity,
    Verdict,
    VerdictAction,
)
from backend.services.turn.agent_executor import AgentTurnExecutor
from backend.services.turn.models import TurnInput, TurnResult


# ---------------------------------------------------------------------------
# Mock direct executor
# ---------------------------------------------------------------------------


@dataclass
class MockDirect:
    """Stand-in for :class:`DirectTurnExecutor` used by agent tests.

    Each call to :meth:`execute` pops one canned result from
    :attr:`results` (or returns the configured ``default`` once
    exhausted) and records the received :class:`TurnInput` for later
    assertions.
    """

    results: list[TurnResult] = field(default_factory=list)
    default: TurnResult | None = None
    calls: list[TurnInput] = field(default_factory=list)
    on_call: Callable[[TurnInput], None] | None = None

    async def execute(
        self,
        turn: TurnInput,
        sink: Any,
        cancel_event: asyncio.Event,
        session: Any,
    ) -> TurnResult:
        self.calls.append(turn)
        if self.on_call is not None:
            self.on_call(turn)
        if self.results:
            return self.results.pop(0)
        if self.default is not None:
            return self.default
        return TurnResult(
            content="ok",
            thinking="",
            input_tokens=0,
            output_tokens=0,
            finish_reason="stop",
            had_tool_calls=False,
        )


# ---------------------------------------------------------------------------
# Mock services
# ---------------------------------------------------------------------------


class MockClassifier:
    """Classifier returning a fixed :class:`TaskComplexity`."""

    def __init__(self, complexity: TaskComplexity) -> None:
        self.complexity = complexity
        self.calls: list[str] = []

    async def classify(
        self,
        user_content: str,
        *,
        has_tools: bool,
        cancel_event: asyncio.Event | None = None,
    ) -> TaskComplexity:
        self.calls.append(user_content)
        return self.complexity


class MockPlanner:
    """Planner returning canned :class:`Plan` objects in order."""

    def __init__(self, plans: list[Plan]) -> None:
        self._plans = list(plans)
        self.calls: list[dict[str, Any]] = []

    async def plan(
        self,
        *,
        goal: str,
        available_tools: list[dict[str, Any]],
        history_summary: str | None = None,
        remaining_goal: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Plan:
        self.calls.append(
            {
                "goal": goal,
                "remaining_goal": remaining_goal,
                "history_summary": history_summary,
            }
        )
        if self._plans:
            return self._plans.pop(0)
        # Fallback identical to the real PlannerService fallback shape.
        return Plan(
            goal=goal,
            steps=[Step(index=0, description=goal, expected_outcome="risposta")],
        )


class MockCritic:
    """Critic returning canned :class:`Verdict` objects in order."""

    def __init__(self, verdicts: list[Verdict]) -> None:
        self._verdicts = list(verdicts)
        self.calls: list[dict[str, Any]] = []

    async def evaluate(
        self,
        *,
        step: Step,
        output: str,
        plan: Plan,
        retries_used: int,
        cancel_event: asyncio.Event | None = None,
    ) -> Verdict:
        self.calls.append(
            {"step_index": step.index, "output": output, "retries_used": retries_used}
        )
        if self._verdicts:
            return self._verdicts.pop(0)
        return Verdict(action=VerdictAction.OK, reason="default")


# ---------------------------------------------------------------------------
# Config / context helpers
# ---------------------------------------------------------------------------


def make_agent_cfg(
    *,
    enabled: bool = True,
    classifier_enabled: bool = True,
    max_steps: int = 8,
    max_retries_per_step: int = 2,
    max_replans: int = 2,
    step_timeout_seconds: int = 0,
    total_timeout_seconds: int = 0,
    save_runs: bool = False,
    voice_mode_bypass: bool = True,
) -> Any:
    """Lightweight ``AgentConfig`` stub matching the attribute surface used."""
    return SimpleNamespace(
        enabled=enabled,
        voice_mode_bypass=voice_mode_bypass,
        max_steps=max_steps,
        max_retries_per_step=max_retries_per_step,
        max_replans=max_replans,
        step_timeout_seconds=step_timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        pause_timeout_during_confirmation=True,
        classifier=SimpleNamespace(enabled=classifier_enabled),
        planner=SimpleNamespace(),
        critic=SimpleNamespace(),
        persistence=SimpleNamespace(save_runs=save_runs),
    )


def build_executor(
    *,
    direct: MockDirect,
    complexity: TaskComplexity,
    plans: list[Plan] | None = None,
    verdicts: list[Verdict] | None = None,
    cfg: Any | None = None,
) -> AgentTurnExecutor:
    """Construct a fully wired :class:`AgentTurnExecutor` for a test."""
    components = AgentComponents(
        classifier=MockClassifier(complexity),
        planner=MockPlanner(plans or []),
        critic=MockCritic(verdicts or []),
    )
    return AgentTurnExecutor(
        direct=direct,
        components=components,
        cfg=cfg or make_agent_cfg(),
    )


# ---------------------------------------------------------------------------
# TurnInput factory
# ---------------------------------------------------------------------------


def make_agent_turn(
    *,
    user_content: str = "fai qualcosa",
    tools: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]] | None = None,
) -> TurnInput:
    """Default :class:`TurnInput` with at least one tool wired in."""
    if tools is None:
        tools = [
            {
                "type": "function",
                "function": {"name": "demo", "description": "demo"},
            }
        ]
    if messages is None:
        messages = [{"role": "user", "content": user_content}]
    return TurnInput(
        conv_id=uuid.uuid4(),
        user_msg_id=uuid.uuid4(),
        user_content=user_content,
        history=[],
        messages=messages,
        tools=tools,
        memory_context=None,
        cached_sys_prompt=None,
        attachment_info=None,
        context_window=4096,
        version_group_id=None,
        version_index=0,
        client_ip="127.0.0.1",
        resolved_max_tokens=None,
    )


def simple_plan(*descriptions: str) -> Plan:
    """Build a :class:`Plan` from a list of step descriptions."""
    return Plan(
        goal="goal",
        steps=[
            Step(index=i, description=d, expected_outcome=f"esito {i}")
            for i, d in enumerate(descriptions)
        ],
    )
