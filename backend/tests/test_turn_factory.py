"""Branching of :func:`backend.services.turn.factory.create_turn_executor`.

The model-driven loop is the only execution path, so the factory has exactly
two outcomes:

    * a bare :class:`DirectTurnExecutor` when reflection is disabled
      (the default), and
    * a :class:`ReflectiveTurnExecutor` wrapping it when
      ``agent.reflection.enabled`` is True.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.factory import create_turn_executor
from backend.services.turn.reflective_executor import ReflectiveTurnExecutor


def _make_ctx(*, reflection_enabled: bool) -> Any:
    """Build a minimal context exposing ``config.agent.reflection``."""
    return SimpleNamespace(
        config=SimpleNamespace(
            agent=SimpleNamespace(
                planning=True,
                delegation=True,
                reflection=SimpleNamespace(
                    enabled=reflection_enabled,
                    tool_turns_only=True,
                    max_output_tokens=80,
                    temperature=0.0,
                    fail_open=True,
                    degeneration_detector_enabled=True,
                ),
            ),
        ),
    )


def test_factory_default_returns_direct() -> None:
    # Reflection disabled (default) → the bare engine.
    ctx = _make_ctx(reflection_enabled=False)
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, DirectTurnExecutor)


def test_factory_returns_reflective_when_reflection_enabled() -> None:
    ctx = _make_ctx(reflection_enabled=True)
    executor = create_turn_executor(ctx, llm=object())
    assert isinstance(executor, ReflectiveTurnExecutor)
