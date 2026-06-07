"""AL\\CE — Turn executor factory.

Selects a :class:`TurnExecutor` implementation from ``ctx.config.agent``:

* ``agent.enabled = False`` → :class:`DirectTurnExecutor` (lite path: a
  plain tool loop, no agentic affordances). Also used for voice mode.
* ``agent.enabled = True`` (default) → the **model-driven** path. The agentic
  behaviour comes from the ``agent`` plugin's meta-tools (``update_plan`` /
  ``spawn_subagent``) already in the tool registry, so the engine is just the
  :class:`DirectTurnExecutor`. When ``agent.reflection.enabled`` is set it is
  wrapped in a :class:`ReflectiveTurnExecutor` for an optional self-check.
* ``agent.structured_mode = True`` → the opt-in legacy
  :class:`AgentTurnExecutor` (classifier → planner → critic).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from loguru import logger

from backend.core.context import AppContext
from backend.services.llm_service import LLMService
from backend.services.turn.direct_executor import DirectTurnExecutor

SyncFn = Callable[..., Coroutine[Any, Any, None]]


def create_turn_executor(
    ctx: AppContext,
    llm: LLMService,
    sync_fn: SyncFn | None = None,
) -> Any:
    """Return the executor strategy for the current configuration.

    Args:
        ctx: Application context (config + services).
        llm: Active LLM service.
        sync_fn: Optional ``_sync_conversation_to_file`` callback handed
            down to the legacy tool loop. ``None`` disables file sync.

    Returns:
        A :class:`DirectTurnExecutor` (lite / model-driven default / voice),
        a :class:`~backend.services.turn.reflective_executor.ReflectiveTurnExecutor`
        (model-driven + reflection), or the legacy
        :class:`~backend.services.turn.agent_executor.AgentTurnExecutor`
        (``structured_mode``).
    """
    direct = DirectTurnExecutor(ctx, llm, sync_fn=sync_fn)

    agent_cfg = getattr(ctx.config, "agent", None)
    if agent_cfg is None or not getattr(agent_cfg, "enabled", False):
        return direct  # lite path — no agentic affordances

    # Voice mode always uses the lite path: low latency, no agentic loop.
    if (
        getattr(agent_cfg, "voice_mode_bypass", False)
        and getattr(ctx, "_in_voice_mode", False)
    ):
        return direct

    components = getattr(ctx, "agent_components", None)

    # Opt-in legacy structured pipeline (classifier → planner → critic).
    if getattr(agent_cfg, "structured_mode", False):
        if components is None:
            logger.warning(
                "agent.structured_mode is on but components are missing — "
                "falling back to the model-driven path",
            )
        else:
            # Lazy import keeps the heavy agent module out of the load
            # graph unless structured mode is actually selected.
            from backend.services.turn.agent_executor import AgentTurnExecutor

            return AgentTurnExecutor(
                direct=direct, components=components, cfg=agent_cfg,
            )

    # Default: model-driven loop. DirectTurnExecutor IS the engine — the
    # agentic behaviour comes from the registry's update_plan / spawn_subagent
    # meta-tools. Optionally add a single non-blocking reflection pass.
    reflection = getattr(agent_cfg, "reflection", None)
    if (
        reflection is not None
        and getattr(reflection, "enabled", False)
        and components is not None
    ):
        from backend.services.turn.reflective_executor import (
            ReflectiveTurnExecutor,
        )

        return ReflectiveTurnExecutor(
            direct=direct, critic=components.critic, cfg=agent_cfg,
        )

    return direct


__all__ = ["create_turn_executor"]
