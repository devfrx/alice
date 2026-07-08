"""AL\\CE — Bootstrap stage: sensory services (Fase 5).

Email, STT, TTS, VRAM monitor, TRELLIS external processes, and the VRAM
pressure event handlers (logging only).
"""

from __future__ import annotations

import asyncio

from loguru import logger

from backend.core.context import AppContext
from backend.core.event_bus import AliceEvent
from backend.core.managed_services import (
    STTManagedService,
    TrellisManagedService,
    TTSManagedService,
    VRAMManagedService,
    resolve_trellis_launcher,
)
from backend.services.stt_service import STTService
from backend.services.tts_service import TTSService
from backend.services.vram_monitor import VRAMMonitor


async def stage_senses(ctx: AppContext) -> None:
    """Start email/STT/TTS/VRAM/TRELLIS services and wire VRAM event handlers.

    Args:
        ctx: The application context being bootstrapped.
    """
    config = ctx.config

    # -- Email service (Phase 15) ------------------------------------------
    if config.email.enabled:
        from backend.services.email_service import EmailService

        email_service = EmailService(config.email, ctx.event_bus)
        try:
            await email_service.initialize()
            ctx.email_service = email_service
            logger.info("Email service started ({})", config.email.username)
        except Exception as exc:
            logger.warning("Email service failed to start: {}", exc)
            await email_service.close()

    # -- Voice services (Phase 4) ------------------------------------------
    if config.stt.enabled:
        try:
            stt_service = STTService(config.stt)
            try:
                await asyncio.wait_for(stt_service.start(), timeout=120)
            except asyncio.TimeoutError:
                logger.warning(
                    "STT model pre-load timed out — will lazy-load on first use",
                )
            ctx.stt_service = stt_service
            logger.info("STT service started (engine={})", config.stt.engine)
        except Exception as exc:
            logger.warning("STT service failed to start: {}", exc)

    if ctx.stt_service is not None:
        try:
            await ctx.orchestrator.attach_started(
                STTManagedService(ctx.stt_service),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach STT: {}", exc)

    if config.tts.enabled:
        try:
            tts_service = TTSService(config.tts)
            await tts_service.start()
            ctx.tts_service = tts_service
            logger.info("TTS service started (engine={})", config.tts.engine)
        except Exception as exc:
            logger.warning("TTS service failed to start: {}", exc)

    if ctx.tts_service is not None:
        try:
            await ctx.orchestrator.attach_started(
                TTSManagedService(ctx.tts_service),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach TTS: {}", exc)

    if config.vram.monitoring_enabled:
        try:
            vram_monitor = VRAMMonitor(
                ctx.event_bus,
                poll_interval=config.vram.poll_interval_s,
                warning_mb=config.vram.warning_threshold_mb,
                critical_mb=config.vram.critical_threshold_mb,
            )
            await vram_monitor.start()
            ctx.vram_monitor = vram_monitor
            logger.info("VRAM monitor started")
        except Exception as exc:
            logger.warning("VRAM monitor failed to start: {}", exc)

    if ctx.vram_monitor is not None:
        try:
            await ctx.orchestrator.attach_started(
                VRAMManagedService(ctx.vram_monitor),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach VRAM monitor: {}", exc)

    # -- TRELLIS external process (health-only, user-managed) --------------
    if getattr(config, "trellis", None) and config.trellis.enabled:
        try:
            launcher, cwd = resolve_trellis_launcher("trellis")
            await ctx.orchestrator.attach_started(
                TrellisManagedService(
                    name="trellis",
                    service_url=config.trellis.service_url,
                    launcher=launcher,
                    cwd=cwd,
                    model=config.trellis.trellis_model,
                    trellis_dir=config.trellis.trellis_dir,
                ),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach TRELLIS: {}", exc)
    if getattr(config, "trellis2", None) and config.trellis2.enabled:
        try:
            launcher, cwd = resolve_trellis_launcher("trellis2")
            await ctx.orchestrator.attach_started(
                TrellisManagedService(
                    name="trellis2",
                    service_url=config.trellis2.service_url,
                    launcher=launcher,
                    cwd=cwd,
                    model=config.trellis2.trellis2_model,
                    trellis_dir=config.trellis2.trellis2_dir,
                ),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach TRELLIS.2: {}", exc)
    if (
        getattr(config, "trellis2multiview", None)
        and config.trellis2multiview.enabled
    ):
        try:
            launcher, cwd = resolve_trellis_launcher("trellis2multiview")
            await ctx.orchestrator.attach_started(
                TrellisManagedService(
                    name="trellis2multiview",
                    service_url=config.trellis2multiview.service_url,
                    launcher=launcher,
                    cwd=cwd,
                    model=config.trellis2multiview.trellis2multiview_model,
                    trellis_dir=config.trellis2multiview.trellis2multiview_dir,
                ),
            )
        except Exception as exc:
            logger.warning(
                "Orchestrator: failed to attach TRELLIS.2 multi-view: {}", exc,
            )

    # -- VRAM event handlers ------------------------------------------------
    # These handlers ONLY log VRAM pressure.  Mutating ``stt_cfg`` /
    # ``tts_cfg`` here would not actually downgrade the running services
    # (they cache their own config snapshot at start()), so we deliberately
    # avoid touching live config to prevent misleading "we mitigated"
    # signals.  Real mitigation (restart STT/TTS with new settings) lives
    # in the settings/config REST handlers and must be triggered explicitly
    # by the user or a future orchestrator.
    if ctx.vram_monitor:
        async def _handle_vram_warning(**kwargs):
            usage = kwargs.get("usage")
            if usage:
                logger.warning(
                    "VRAM warning: {}MB used / {}MB total",
                    usage.used_mb, usage.total_mb,
                )

        async def _handle_vram_critical(**kwargs):
            usage = kwargs.get("usage")
            if usage:
                logger.error(
                    "VRAM critical: {}MB used / {}MB total",
                    usage.used_mb, usage.total_mb,
                )

        ctx.event_bus.subscribe(AliceEvent.VRAM_WARNING, _handle_vram_warning)
        ctx.event_bus.subscribe(AliceEvent.VRAM_CRITICAL, _handle_vram_critical)
