"""Branching of :func:`backend.services.turn.factory.create_turn_executor`.

Asserts the factory returns:
    * a :class:`DirectTurnExecutor` when ``agent.enabled`` is False (lite),
    * a :class:`DirectTurnExecutor` for the model-driven default
      (``agent.enabled`` True, ``structured_mode`` False, reflection off),
    * a :class:`ReflectiveTurnExecutor` when reflection is enabled,
    * an :class:`AgentTurnExecutor` when ``structured_mode`` is True,
    * a :class:`DirectTurnExecutor` when voice mode bypass is active.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.services.agent import AgentComponents
from backend.services.agent.models import TaskComplexity
from backend.services.turn.agent_executor import AgentTurnExecutor
from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.factory import create_turn_executor
from backend.services.turn.reflective_executor import ReflectiveTurnExecutor

from ._agent_helpers import MockClassifier, MockCritic, MockPlanner


def _make_ctx(
    *,
    agent_enabled: bool,
    components: Any | None,
    voice_mode: bool = False,
    structured_mode: bool = False,
    reflection_enabled: bool = False,
) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(
            llm=SimpleNamespace(max_tool_iterations=4),
            pc_automation=SimpleNamespace(confirmation_timeout_s=60),
            agent=SimpleNamespace(
                enabled=agent_enabled,
                structured_mode=structured_mode,
                voice_mode_bypass=True,
                reflection=SimpleNamespace(
                    enabled=reflection_enabled,
                    tool_turns_only=True,
                ),
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


def test_factory_model_driven_default_returns_direct() -> None:
    # agent on, structured_mode off, reflection off → lite engine + meta-tools.
    ctx = _make_ctx(agent_enabled=True, components=_components())
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, DirectTurnExecutor)


def test_factory_model_driven_without_components_returns_direct() -> None:
    ctx = _make_ctx(agent_enabled=True, components=None)
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, DirectTurnExecutor)


def test_factory_returns_reflective_when_reflection_enabled() -> None:
    ctx = _make_ctx(
        agent_enabled=True, components=_components(), reflection_enabled=True,
    )
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, ReflectiveTurnExecutor)


def test_factory_reflection_without_components_returns_direct() -> None:
    # Reflection needs the critic component; without it, stay model-driven.
    ctx = _make_ctx(
        agent_enabled=True, components=None, reflection_enabled=True,
    )
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, DirectTurnExecutor)


def test_factory_returns_agent_when_structured_mode() -> None:
    ctx = _make_ctx(
        agent_enabled=True, components=_components(), structured_mode=True,
    )
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, AgentTurnExecutor)


def test_factory_structured_mode_without_components_returns_direct() -> None:
    ctx = _make_ctx(
        agent_enabled=True, components=None, structured_mode=True,
    )
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, DirectTurnExecutor)


def test_factory_voice_mode_bypass_returns_direct() -> None:
    # Voice mode uses the lite path even with structured_mode + reflection on.
    ctx = _make_ctx(
        agent_enabled=True,
        components=_components(),
        voice_mode=True,
        structured_mode=True,
        reflection_enabled=True,
    )
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, DirectTurnExecutor)
