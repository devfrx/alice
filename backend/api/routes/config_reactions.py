"""AL\\CE — Declarative reactions to config changes.

Maps sets of dotted config paths to side-effect handlers (service
restarts, cache invalidation). Invoked once per PUT/PATCH request with
the set of paths whose RESOLVED value actually changed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable

from loguru import logger
from pydantic import SecretStr

from backend.core.config import AliceConfig
from backend.core.context import AppContext
from backend.services.config_policy import PREFERENCE_EXACT_PATHS
from backend.services.stt_service import STTService
from backend.services.tts_service import TTSService

# --- handlers spostati (corpo INVARIATO) da config.py ---------------------


async def _apply_stt_changes(ctx: AppContext, stt_updates: dict) -> None:
    """Restart or stop the STT service when its config changes."""
    cfg = ctx.config

    # Disable → stop service
    if "enabled" in stt_updates and not cfg.stt.enabled:
        if ctx.stt_service is not None:
            try:
                await ctx.stt_service.stop()
                logger.info("STT service stopped (disabled via config)")
            except Exception as exc:
                logger.warning("Failed to stop STT service: {}", exc)
            ctx.stt_service = None
        return

    # Enable or model/device changed → restart service
    needs_restart = any(
        k in stt_updates for k in ("enabled", "model", "device")
    )
    if not needs_restart:
        return

    if not cfg.stt.enabled:
        return

    # Stop existing
    if ctx.stt_service is not None:
        try:
            await ctx.stt_service.stop()
        except Exception as exc:
            logger.warning("Failed to stop STT service for restart: {}", exc)
        ctx.stt_service = None

    # Auto-correct compute_type for CPU (float16 not supported)
    if cfg.stt.device == "cpu" and cfg.stt.compute_type == "float16":
        object.__setattr__(cfg.stt, "compute_type", "int8")
        logger.info("Auto-corrected STT compute_type to int8 for CPU device")

    # Start new
    try:
        stt = STTService(cfg.stt)
        await stt.start()
        ctx.stt_service = stt
        logger.info(
            "STT service restarted (model={}, device={}, compute_type={})",
            cfg.stt.model, cfg.stt.device, cfg.stt.compute_type,
        )
    except Exception as exc:
        logger.warning("STT service failed to restart: {}", exc)


async def _apply_tts_changes(ctx: AppContext, tts_updates: dict) -> None:
    """Restart or stop the TTS service when its config changes."""
    cfg = ctx.config

    # Disable → stop service
    if "enabled" in tts_updates and not cfg.tts.enabled:
        if ctx.tts_service is not None:
            try:
                await ctx.tts_service.stop()
                logger.info("TTS service stopped (disabled via config)")
            except Exception as exc:
                logger.warning("Failed to stop TTS service: {}", exc)
            ctx.tts_service = None
        return

    # Engine, voice, or speed changed → restart service
    needs_restart = any(
        k in tts_updates for k in (
            "enabled", "engine", "voice", "speed",
            "kokoro_model", "kokoro_voices", "kokoro_voice", "kokoro_language",
        )
    )
    if not needs_restart:
        return

    if not cfg.tts.enabled:
        return

    # Stop existing
    if ctx.tts_service is not None:
        try:
            await ctx.tts_service.stop()
        except Exception as exc:
            logger.warning("Failed to stop TTS service for restart: {}", exc)
        ctx.tts_service = None

    # Start new
    try:
        tts = TTSService(cfg.tts)
        await tts.start()
        ctx.tts_service = tts
        logger.info(
            "TTS service restarted (engine={}, voice={})",
            cfg.tts.engine, cfg.tts.voice,
        )
    except Exception as exc:
        logger.warning("TTS service failed to restart: {}", exc)


async def _apply_llm_provider_change(ctx: AppContext) -> None:
    """Rebuild the LLM service after a provider or API-key change.

    Auth headers on the shared httpx client and the provider-derived
    flags in LLMClient/ModelResolver are fixed at construction time, so
    an in-place config mutation is not enough — recreate the service,
    mirroring the STT/TTS restart pattern.
    """
    from backend.services.llm_service import LLMService

    old = ctx.llm_service
    new_service = LLMService(ctx.config.llm, model_registry=ctx.model_registry)
    ctx.llm_service = new_service
    # add_models_changed_listener has no removal API: the old service's
    # listener stays registered (harmless no-op on a closed service,
    # bounded by user-initiated switches).
    if ctx.lmstudio_manager is not None:
        ctx.lmstudio_manager.add_models_changed_listener(
            new_service.invalidate_context_window_cache
        )
    if old is not None:
        try:
            await old.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to close previous LLM service: {}", exc)
    logger.info("LLM service rebuilt (provider={})", ctx.config.llm.provider)


async def _apply_email_changes(ctx: AppContext) -> None:
    """Restart or stop the email service after runtime config changes."""
    if ctx.email_service is not None:
        try:
            await ctx.email_service.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to stop EmailService for restart: {}", exc)
        ctx.email_service = None

    if not ctx.config.email.enabled:
        logger.info("Email service stopped (disabled via config)")
        return

    from backend.services.email_service import EmailService

    email_service = EmailService(ctx.config.email, ctx.event_bus)
    try:
        await email_service.initialize()
        ctx.email_service = email_service
        logger.info("Email service restarted ({})", ctx.config.email.username)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Email service failed to restart: {}", exc)
        await email_service.close()


_STT_RESTART_PATHS = frozenset({"stt.enabled", "stt.model", "stt.device"})
_TTS_RESTART_PATHS = frozenset({
    "tts.enabled", "tts.engine", "tts.voice", "tts.speed",
    "tts.kokoro_model", "tts.kokoro_voices", "tts.kokoro_voice",
    "tts.kokoro_language",
})
_LLM_REBUILD_PATHS = frozenset({
    "llm.provider", "llm.openrouter_api_key", "llm.api_token",
})
_EMAIL_REACTIVE_PATHS = frozenset(
    p for p in PREFERENCE_EXACT_PATHS if p.startswith("email.")
)


async def _react_stt(ctx: AppContext, changed: set[str]) -> None:
    updates = {p.removeprefix("stt."): True for p in changed if p in _STT_RESTART_PATHS}
    if updates:
        await _apply_stt_changes(ctx, updates)
        from backend.api.routes.voice import push_voice_ready
        await push_voice_ready(ctx)


async def _react_tts(ctx: AppContext, changed: set[str]) -> None:
    updates = {p.removeprefix("tts."): True for p in changed if p in _TTS_RESTART_PATHS}
    if updates:
        await _apply_tts_changes(ctx, updates)
        from backend.api.routes.voice import push_voice_ready
        await push_voice_ready(ctx)


async def _react_email(ctx: AppContext, changed: set[str]) -> None:
    if any(p.startswith("email.") for p in changed):
        await _apply_email_changes(ctx)


async def _react_llm_rebuild(ctx: AppContext, changed: set[str]) -> None:
    if changed & _LLM_REBUILD_PATHS:
        await _apply_llm_provider_change(ctx)


async def _react_model_cache(ctx: AppContext, changed: set[str]) -> None:
    if "llm.model" in changed and ctx.llm_service is not None:
        ctx.llm_service.invalidate_model_cache()


async def _react_openrouter_model(ctx: AppContext, changed: set[str]) -> None:
    if "llm.openrouter_model" in changed and ctx.llm_service is not None:
        ctx.llm_service.invalidate_model_cache()
        ctx.llm_service.invalidate_context_window_cache()


async def _react_system_prompt(ctx: AppContext, changed: set[str]) -> None:
    if "llm.user_preferred_name" in changed and ctx.llm_service is not None:
        ctx.llm_service.invalidate_system_prompt_cache()


Reaction = Callable[[AppContext, set[str]], Awaitable[None]]

# Ordine deliberato: il rebuild LLM per ULTIMO tra le reazioni llm.* così
# le invalidazioni di cache toccano il servizio NUOVO quando coincidono.
REACTIONS: tuple[tuple[frozenset[str] | str, Reaction], ...] = (
    ("stt.", _react_stt),
    ("tts.", _react_tts),
    ("email.", _react_email),
    (frozenset({"llm.model"}), _react_model_cache),
    (frozenset({"llm.openrouter_model"}), _react_openrouter_model),
    (frozenset({"llm.user_preferred_name"}), _react_system_prompt),
    (_LLM_REBUILD_PATHS, _react_llm_rebuild),
)

# Every dotted path any reaction actually listens for — used by callers to
# scope the pre/post-write diff to paths that matter for side effects.
ALL_REACTIVE_PATHS: frozenset[str] = (
    frozenset(
        p for trigger, _ in REACTIONS if isinstance(trigger, frozenset) for p in trigger
    )
    | _STT_RESTART_PATHS
    | _TTS_RESTART_PATHS
    | _EMAIL_REACTIVE_PATHS
)


def _matches(trigger: frozenset[str] | str, changed: set[str]) -> bool:
    if isinstance(trigger, str):
        return any(p.startswith(trigger) for p in changed)
    return bool(trigger & changed)


async def apply_reactions(ctx: AppContext, changed: set[str]) -> None:
    """Run every matching reaction; failures are logged, not raised."""
    for trigger, handler in REACTIONS:
        if not _matches(trigger, changed):
            continue
        try:
            await handler(ctx, changed)
        except Exception as exc:  # noqa: BLE001 — una reazione non blocca le altre
            logger.warning("Config reaction {} failed: {}", handler.__name__, exc)


def diff_paths(old: AliceConfig, new: AliceConfig, candidates: Iterable[str]) -> set[str]:
    """Return the candidate dotted paths whose resolved value changed."""
    from backend.services.config_service import _get_dotted

    changed: set[str] = set()
    for path in candidates:
        try:
            old_v = _get_dotted(old, path)
        except KeyError:
            old_v = None
        try:
            new_v = _get_dotted(new, path)
        except KeyError:
            new_v = None
        if isinstance(old_v, SecretStr):
            old_v = old_v.get_secret_value()
        if isinstance(new_v, SecretStr):
            new_v = new_v.get_secret_value()
        if old_v != new_v:
            changed.add(path)
    return changed
