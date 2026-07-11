"""AL\\CE — Ordered service shutdown (Fase 5).

Mirrors the historical ``finally`` block of the lifespan: same order,
one isolated try/except per step, reading every service from the
context (with guards) instead of pre-bound locals.
"""

from __future__ import annotations

from loguru import logger

from backend.core.context import AppContext


async def shutdown_services(ctx: AppContext | None) -> None:
    """Close every started service in the historical order.

    Args:
        ctx: The application context, or ``None`` when startup failed
            before it was constructed (nothing to close).
    """
    if ctx is None:
        return

    # Stop autonomous-turn triggers first: nothing new should fire while
    # the rest of the platform is tearing down.
    if ctx.trigger_service is not None:
        try:
            await ctx.trigger_service.shutdown()
        except Exception as exc:
            logger.error("Trigger service shutdown error: {}", exc)

    # Stop orchestrator polling first so health probes don't race with
    # the legacy per-service shutdown calls below.
    if ctx.orchestrator is not None:
        try:
            await ctx.orchestrator.shutdown_polling()
        except Exception as exc:
            logger.error("Orchestrator shutdown error: {}", exc)
    if ctx.terminal_session_manager is not None:
        try:
            await ctx.terminal_session_manager.shutdown()
        except Exception as exc:
            logger.error("Terminal manager shutdown error: {}", exc)
    if ctx.plugin_manager is not None:
        try:
            await ctx.plugin_manager.shutdown()
        except Exception as exc:
            logger.error("Plugin system shutdown error: {}", exc)
    if ctx.lmstudio_manager is not None:
        try:
            await ctx.lmstudio_manager.close()
        except Exception as exc:
            logger.error("LMStudio manager shutdown error: {}", exc)
    if ctx.llm_service is not None:
        try:
            await ctx.llm_service.close()
        except Exception as exc:
            logger.error("LLM service shutdown error: {}", exc)
    if ctx.stt_service:
        try:
            await ctx.stt_service.stop()
        except Exception as exc:
            logger.error("STT shutdown error: {}", exc)
    if ctx.tts_service:
        try:
            await ctx.tts_service.stop()
        except Exception as exc:
            logger.error("TTS shutdown error: {}", exc)
    if ctx.vram_monitor:
        try:
            await ctx.vram_monitor.stop()
        except Exception as exc:
            logger.error("VRAM monitor shutdown error: {}", exc)
    if ctx.memory_service:
        try:
            await ctx.memory_service.close()
        except Exception as exc:
            logger.error("Memory service shutdown error: {}", exc)
    if ctx.email_service:
        try:
            await ctx.email_service.close()
        except Exception as exc:
            logger.error("Email service shutdown error: {}", exc)
    if ctx.qdrant_service:
        try:
            await ctx.qdrant_service.close()
        except Exception as exc:
            logger.error("Qdrant service shutdown error: {}", exc)
    if ctx.embedding_client:
        try:
            await ctx.embedding_client.close()
        except Exception as exc:
            logger.error("Embedding client shutdown error: {}", exc)
    if ctx.engine is not None:
        try:
            await ctx.engine.dispose()
        except Exception as exc:
            logger.error("Engine disposal error: {}", exc)
