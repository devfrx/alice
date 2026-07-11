"""Stage: Fondamenta Jarvis — background tasks, attention, triggers (Fase 8)."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from backend.core.context import AppContext


async def stage_jarvis(ctx: AppContext) -> None:
    """Create the Fase 8 kernel services and wire the autonomous-turn seam.

    Runs LAST: it needs the event bus (platform), the events-WS bridges
    (surfaces) and the fully-wired turn pipeline (workspace) already up.
    The headless turn runner lives in the api layer; injecting it here is
    the sanctioned composition-root exception
    (``backend.core.bootstrap.* -> backend.api.**``).
    """
    from backend.api.routes.chat.headless import run_headless_turn
    from backend.services.attention_service import AttentionService
    from backend.services.background_tasks import BackgroundTaskService
    from backend.services.trigger_service import TriggerService

    ctx.background_task_service = BackgroundTaskService(event_bus=ctx.event_bus)

    ctx.attention_service = AttentionService(
        event_bus=ctx.event_bus,
        enabled=ctx.config.attention.enabled,
        cooldown_s=ctx.config.attention.cooldown_s,
    )

    trigger_service = TriggerService(
        event_bus=ctx.event_bus,
        turn_runner=partial(run_headless_turn, ctx),
        background_tasks=ctx.background_task_service,
        attention=ctx.attention_service,
        enabled=ctx.config.triggers.enabled,
        max_concurrent_turns=ctx.config.triggers.max_concurrent_turns,
    )
    ctx.trigger_service = trigger_service
    await trigger_service.start()

    logger.info(
        "Jarvis foundations ready (triggers={}, attention={})",
        ctx.config.triggers.enabled,
        ctx.config.attention.enabled,
    )
