"""Branching of :func:`backend.services.turn.factory.create_turn_executor`.

Asserts the factory returns:
    * a :class:`DirectTurnExecutor` when ``agent.enabled`` is False,
    * a :class:`DirectTurnExecutor` when ``agent.enabled`` is True but
      ``ctx.agent_components`` is ``None``,
    * an :class:`AgentTurnExecutor` when both flags are set,
    * a :class:`DirectTurnExecutor` when voice mode bypass is active.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.services.agent import AgentComponents
from backend.services.agent.models import TaskComplexity
from backend.services.turn.agent_executor import AgentTurnExecutor
from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.factory import create_turn_executor

from ._agent_helpers import MockClassifier, MockCritic, MockPlanner


def _make_ctx(*, agent_enabled: bool, components: Any | None,
              voice_mode: bool = False) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(
            llm=SimpleNamespace(max_tool_iterations=4),
            pc_automation=SimpleNamespace(confirmation_timeout_s=60),
            agent=SimpleNamespace(
                enabled=agent_enabled,
                voice_mode_bypass=True,
                classifier=SimpleNamespace(enabled=True),
                planner=SimpleNamespace(),
                critic=SimpleNamespace(),
                persistence=SimpleNamespace(save_runs=False),
                max_steps=8,
                max_retries_per_step=2,
                max_replans=2,
                step_timeout_seconds=0,
                total_timeout_seconds=0,
                pause_timeout_during_confirmation=True,
            ),
        ),
        agent_components=components,
        _in_voice_mode=voice_mode,
    )


def _components() -> AgentComponents:
    return AgentComponents(
        classifier=MockClassifier(TaskComplexity.MULTI_STEP),
        planner=MockPlanner([]),
        critic=MockCritic([]),
    )


def test_factory_returns_direct_when_agent_disabled() -> None:
    ctx = _make_ctx(agent_enabled=False, components=_components())
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, DirectTurnExecutor)


def test_factory_returns_direct_when_components_missing() -> None:
    ctx = _make_ctx(agent_enabled=True, components=None)
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, DirectTurnExecutor)


def test_factory_returns_agent_when_enabled_and_components_present() -> None:
    ctx = _make_ctx(agent_enabled=True, components=_components())
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, AgentTurnExecutor)


def test_factory_voice_mode_bypass_returns_direct() -> None:
    ctx = _make_ctx(
        agent_enabled=True, components=_components(), voice_mode=True
    )
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, DirectTurnExecutor)
