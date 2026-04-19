"""AL\\CE — Turn executor factory.

Selects a :class:`TurnExecutor` implementation based on the application
context.  Phase 3b wires in :class:`AgentTurnExecutor` whenever
``ctx.config.agent.enabled`` is true and an
:class:`~backend.services.agent.AgentComponents` bundle is present;
otherwise the legacy :class:`DirectTurnExecutor` is returned so the
runtime stays bit-equivalent to the pre-agent path.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine

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
        Either a :class:`DirectTurnExecutor` (agent disabled / components
        missing / voice mode bypass) or an
        :class:`~backend.services.turn.agent_executor.AgentTurnExecutor`
        wrapping the direct one.
    """
    direct = DirectTurnExecutor(ctx, llm, sync_fn=sync_fn)

    agent_cfg = getattr(ctx.config, "agent", None)
    if agent_cfg is None or not getattr(agent_cfg, "enabled", False):
        return direct

    components = getattr(ctx, "agent_components", None)
    if components is None:
        logger.debug(
            "Agent enabled but components missing — falling back to Direct"
        )
        return direct

    if (
        getattr(agent_cfg, "voice_mode_bypass", False)
        and getattr(ctx, "_in_voice_mode", False)
    ):
        return direct

    # Lazy import keeps the agent module out of the load graph when the
    # feature flag is off.
    from backend.services.turn.agent_executor import AgentTurnExecutor

    return AgentTurnExecutor(direct=direct, components=components, cfg=agent_cfg)


__all__ = ["create_turn_executor"]
