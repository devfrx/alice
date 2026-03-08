"""O.M.N.I.A. — Configuration endpoints (read/update runtime config)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from backend.api.routes.models import serialise_model
from backend.core.config import KNOWN_MODELS
from backend.core.context import AppContext
from backend.services.stt_service import STTService
from backend.services.tts_service import TTSService

router = APIRouter()


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


@router.get("/config/models")
async def list_models(request: Request) -> list[dict[str, Any]]:
    """Fetch locally available models and return enriched metadata.

    Uses the LM Studio v1 API as primary source, falling back to
    OpenAI-compatible ``/v1/models`` or Ollama ``/api/tags``.
    """
    ctx = _ctx(request)
    active_model = ctx.config.llm.model

    # -- Primary: LM Studio v1 API ------------------------------------------
    mgr = ctx.lmstudio_manager
    if mgr is not None:
        try:
            data = await mgr.list_models()
            return _models_from_v1(data, active_model)
        except Exception:
            logger.debug("v1 API unavailable, falling back to legacy")

    # -- Fallback: legacy OpenAI-compat / Ollama ----------------------------
    return await _models_legacy(ctx)


def _models_from_v1(
    data: dict, active_model: str,
) -> list[dict[str, Any]]:
    """Map LM Studio v1 response to the frontend-expected shape."""
    return [
        serialise_model(m, active_model)
        for m in data.get("models", [])
    ]


async def _models_legacy(ctx: AppContext) -> list[dict[str, Any]]:
    """Fetch models via OpenAI-compatible or Ollama endpoint."""
    active_model = ctx.config.llm.model
    base_url = ctx.config.llm.base_url
    is_ollama = ctx.config.llm.provider == "ollama"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if is_ollama:
                resp = await client.get(f"{base_url}/api/tags")
                resp.raise_for_status()
                raw_models = resp.json().get("models", [])
            else:
                resp = await client.get(f"{base_url}/v1/models")
                resp.raise_for_status()
                raw_models = resp.json().get("data", [])
    except Exception:
        logger.debug("Failed to fetch models from {}", base_url)
        return []

    models: list[dict[str, Any]] = []
    for m in raw_models:
        name = m.get("id", "") or m.get("name", "")
        known = KNOWN_MODELS.get(name, {})
        models.append({
            "name": name,
            "display_name": name,
            "size": m.get("size", 0),
            "modified_at": m.get("modified_at", m.get("created", "")),
            "is_active": name == active_model,
            "loaded": True,
            "loaded_instances": [],
            "architecture": None,
            "quantization": None,
            "params_string": None,
            "format": None,
            "max_context_length": 0,
            "capabilities": {
                "vision": known.get("vision", False),
                "thinking": known.get("thinking", False),
                "trained_for_tool_use": False,
            },
        })
    return models


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    """Return the current server configuration as JSON."""
    ctx = _ctx(request)
    cfg = ctx.config
    return {
        "llm": {
            "provider": cfg.llm.provider,
            "base_url": cfg.llm.base_url,
            "model": cfg.llm.model,
            "temperature": cfg.llm.temperature,
            "max_tokens": cfg.llm.max_tokens,
            "supports_thinking": cfg.llm.supports_thinking,
            "supports_vision": cfg.llm.supports_vision,
            "max_tool_iterations": cfg.llm.max_tool_iterations,
        },
        "stt": {
            "engine": cfg.stt.engine,
            "model": cfg.stt.model,
            "language": cfg.stt.language,
            "device": cfg.stt.device,
            "enabled": cfg.stt.enabled,
        },
        "tts": {
            "engine": cfg.tts.engine,
            "voice": cfg.tts.voice,
            "sample_rate": cfg.tts.sample_rate,
            "enabled": cfg.tts.enabled,
            "speed": cfg.tts.speed,
        },
        "ui": {
            "theme": cfg.ui.theme,
            "language": cfg.ui.language,
        },
        "voice": {
            "auto_tts_response": cfg.voice.auto_tts_response,
            "voice_confirmation_enabled": cfg.voice.voice_confirmation_enabled,
            "activation_mode": cfg.voice.activation_mode,
            "wake_word": cfg.voice.wake_word,
        },
        "pc_automation": {
            "enabled": cfg.pc_automation.enabled,
            "confirmations_enabled": cfg.pc_automation.confirmations_enabled,
            "screenshot_lockout_s": cfg.pc_automation.screenshot_lockout_s,
        },
    }


@router.put("/config")
async def update_config(request: Request) -> dict[str, Any]:
    """Update configuration values at runtime.

    Body: a partial config dict with only the keys to change.

    Note: Currently a stub — changes are accepted but NOT persisted to
    disk.  Full persistence is planned for a future phase.
    """
    ctx = _ctx(request)
    body = await request.json()

    cfg = ctx.config

    # Apply supported runtime overrides.
    if "llm" in body:
        llm_updates = body["llm"]
        if "model" in llm_updates:
            new_model = str(llm_updates["model"])

            # Load the model on LM Studio BEFORE mutating config so
            # the active-model state stays consistent on failure.
            mgr = ctx.lmstudio_manager
            if mgr is not None:
                if mgr.is_busy:
                    raise HTTPException(
                        409,
                        "Another model operation is already in progress",
                    )

                # Check if model is already loaded — skip redundant load
                models_data: dict | None = None
                try:
                    models_data = await mgr.list_models()
                    already_loaded = any(
                        m.get("key") == new_model
                        and m.get("loaded_instances")
                        for m in models_data.get("models", [])
                    )
                except Exception as exc:
                    logger.debug(
                        "Could not check loaded models: {}", exc,
                    )
                    already_loaded = False

                if not already_loaded:
                    try:
                        await mgr.load_model(new_model)
                        logger.info(
                            "Loaded model '{}' on LM Studio",
                            new_model,
                        )
                    except RuntimeError as exc:
                        raise HTTPException(409, str(exc))
                    except Exception as exc:
                        raise HTTPException(
                            503,
                            f"Failed to load model '{new_model}': {exc}",
                        )
                else:
                    logger.info(
                        "Model '{}' already loaded, skipping load",
                        new_model,
                    )

            object.__setattr__(cfg.llm, "model", new_model)
            caps = KNOWN_MODELS.get(
                new_model, {"vision": False, "thinking": False},
            )
            if mgr is not None:
                # Reuse models_data from loaded-check; re-query
                # only if the model was just loaded (data may be stale).
                if not already_loaded or models_data is None:
                    try:
                        models_data = await mgr.list_models()
                    except Exception as exc:
                        logger.debug(
                            "Could not query models for '{}': {}",
                            new_model, exc,
                        )
                        models_data = None
                if models_data is not None:
                    for m_info in models_data.get("models", []):
                        if m_info.get("key") == new_model:
                            live_caps = m_info.get(
                                "capabilities", {},
                            )
                            caps = {
                                "vision": live_caps.get(
                                    "vision",
                                    caps.get("vision", False),
                                ),
                                "thinking": live_caps.get(
                                    "thinking",
                                    caps.get("thinking", False),
                                ),
                            }
                            break
            object.__setattr__(
                cfg.llm, "supports_vision",
                caps.get("vision", False),
            )
            object.__setattr__(
                cfg.llm, "supports_thinking",
                caps.get("thinking", False),
            )
        if "temperature" in llm_updates:
            try:
                temp = float(llm_updates["temperature"])
            except (TypeError, ValueError):
                raise HTTPException(400, "temperature must be a number")
            if not (0.0 <= temp <= 2.0):
                raise HTTPException(400, "temperature must be between 0.0 and 2.0")
            object.__setattr__(cfg.llm, "temperature", temp)
        if "max_tokens" in llm_updates:
            try:
                mt = int(llm_updates["max_tokens"])
            except (TypeError, ValueError):
                raise HTTPException(400, "max_tokens must be a positive integer")
            if mt <= 0:
                raise HTTPException(400, "max_tokens must be a positive integer")
            object.__setattr__(cfg.llm, "max_tokens", mt)
        if "max_tool_iterations" in llm_updates:
            try:
                mti = int(llm_updates["max_tool_iterations"])
            except (TypeError, ValueError):
                raise HTTPException(400, "max_tool_iterations must be a positive integer")
            if not (1 <= mti <= 100):
                raise HTTPException(400, "max_tool_iterations must be between 1 and 100")
            object.__setattr__(cfg.llm, "max_tool_iterations", mti)

    if "ui" in body:
        ui_updates = body["ui"]
        if "theme" in ui_updates:
            theme = str(ui_updates["theme"]).strip()
            if theme not in ("dark", "light"):
                raise HTTPException(400, "theme must be 'dark' or 'light'")
            object.__setattr__(cfg.ui, "theme", theme)
        if "language" in ui_updates:
            lang = str(ui_updates["language"]).strip()
            if not lang or len(lang) > 10:
                raise HTTPException(
                    400, "ui language must be a non-empty string (max 10 chars)",
                )
            object.__setattr__(cfg.ui, "language", lang)

    if "stt" in body:
        stt_updates = body["stt"]
        if "enabled" in stt_updates:
            if not isinstance(stt_updates["enabled"], bool):
                raise HTTPException(400, "stt.enabled must be a boolean")
            object.__setattr__(cfg.stt, "enabled", stt_updates["enabled"])
        if "language" in stt_updates:
            lang = str(stt_updates["language"]).strip()
            if not lang or len(lang) > 10:
                raise HTTPException(
                    400, "language must be a non-empty string (max 10 chars)",
                )
            object.__setattr__(cfg.stt, "language", lang)
        if "model" in stt_updates:
            model = str(stt_updates["model"]).strip()
            if not model or len(model) > 64:
                raise HTTPException(
                    400, "STT model must be a non-empty string (max 64 chars)",
                )
            object.__setattr__(cfg.stt, "model", model)
        if "device" in stt_updates:
            device = str(stt_updates["device"]).strip()
            if device not in ("cpu", "cuda"):
                raise HTTPException(400, "device must be 'cpu' or 'cuda'")
            object.__setattr__(cfg.stt, "device", device)

    if "tts" in body:
        tts_updates = body["tts"]
        if "enabled" in tts_updates:
            if not isinstance(tts_updates["enabled"], bool):
                raise HTTPException(400, "tts.enabled must be a boolean")
            object.__setattr__(cfg.tts, "enabled", tts_updates["enabled"])
        if "engine" in tts_updates:
            engine = str(tts_updates["engine"]).strip()
            if engine not in ("piper", "xtts"):
                raise HTTPException(
                    400, "TTS engine must be 'piper' or 'xtts'",
                )
            object.__setattr__(cfg.tts, "engine", engine)
        if "voice" in tts_updates:
            voice = str(tts_updates["voice"]).strip()
            if not voice or len(voice) > 256:
                raise HTTPException(
                    400, "voice must be a non-empty string (max 256 chars)",
                )
            object.__setattr__(cfg.tts, "voice", voice)
        if "speed" in tts_updates:
            try:
                speed = float(tts_updates["speed"])
            except (TypeError, ValueError):
                raise HTTPException(400, "speed must be a number")
            if not (0.5 <= speed <= 2.0):
                raise HTTPException(
                    400, "speed must be between 0.5 and 2.0",
                )
            object.__setattr__(cfg.tts, "speed", speed)
        if "sample_rate" in tts_updates:
            try:
                sr = int(tts_updates["sample_rate"])
            except (TypeError, ValueError):
                raise HTTPException(400, "sample_rate must be an integer")
            if sr not in (16000, 22050, 44100, 48000):
                raise HTTPException(
                    400,
                    "sample_rate must be one of: 16000, 22050, 44100, 48000",
                )
            object.__setattr__(cfg.tts, "sample_rate", sr)

    if "voice" in body:
        voice_updates = body["voice"]
        if "auto_tts_response" in voice_updates:
            if not isinstance(voice_updates["auto_tts_response"], bool):
                raise HTTPException(400, "auto_tts_response must be a boolean")
            object.__setattr__(
                cfg.voice, "auto_tts_response",
                voice_updates["auto_tts_response"],
            )
        if "voice_confirmation_enabled" in voice_updates:
            if not isinstance(voice_updates["voice_confirmation_enabled"], bool):
                raise HTTPException(400, "voice_confirmation_enabled must be a boolean")
            object.__setattr__(
                cfg.voice, "voice_confirmation_enabled",
                voice_updates["voice_confirmation_enabled"],
            )
        if "activation_mode" in voice_updates:
            mode = str(voice_updates["activation_mode"]).strip()
            if mode not in ("push_to_talk", "wake_word", "always_on"):
                raise HTTPException(
                    400,
                    "activation_mode must be one of: push_to_talk, wake_word, always_on",
                )
            object.__setattr__(cfg.voice, "activation_mode", mode)
        if "wake_word" in voice_updates:
            ww = str(voice_updates["wake_word"]).strip()
            if not ww or len(ww) > 50:
                raise HTTPException(
                    400,
                    "wake_word must be a non-empty string (max 50 chars)",
                )
            object.__setattr__(cfg.voice, "wake_word", ww)

    if "pc_automation" in body:
        pc_updates = body["pc_automation"]
        if "enabled" in pc_updates:
            if not isinstance(pc_updates["enabled"], bool):
                raise HTTPException(400, "pc_automation.enabled must be a boolean")
            object.__setattr__(
                cfg.pc_automation, "enabled",
                pc_updates["enabled"],
            )
        if "confirmations_enabled" in pc_updates:
            if not isinstance(pc_updates["confirmations_enabled"], bool):
                raise HTTPException(400, "confirmations_enabled must be a boolean")
            object.__setattr__(
                cfg.pc_automation, "confirmations_enabled",
                pc_updates["confirmations_enabled"],
            )

    # -- Restart STT/TTS services if their config changed ------------------
    if "stt" in body:
        await _apply_stt_changes(ctx, body["stt"])
    if "tts" in body:
        await _apply_tts_changes(ctx, body["tts"])

    # Return the full config after applying changes.
    return await get_config(request)


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
        k in tts_updates for k in ("enabled", "engine", "voice", "speed")
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


@router.post("/config/sync-model")
async def sync_model(request: Request) -> dict[str, Any]:
    """Sync config with the model currently loaded in LM Studio.

    Queries LM Studio for loaded models.  If exactly one model is loaded
    and it differs from ``config.llm.model``, the config is updated
    automatically (model name, supports_thinking, supports_vision).

    Returns:
        ``{"synced": true, "model": "..."}`` on success, or
        ``{"synced": false, "reason": "..."}`` when no sync is needed.
    """
    ctx = _ctx(request)
    mgr = ctx.lmstudio_manager
    if mgr is None:
        return {"synced": False, "reason": "LM Studio manager not available"}

    try:
        data = await mgr.list_models()
    except Exception as exc:
        logger.warning("sync-model: cannot reach LM Studio — {}", exc)
        return {"synced": False, "reason": "LM Studio unreachable"}

    loaded = [
        m for m in data.get("models", [])
        if m.get("loaded_instances")
    ]

    if not loaded:
        return {"synced": False, "reason": "no model loaded"}

    cfg = ctx.config

    # When multiple models are loaded, check if the config model is among
    # them — that means the user intentionally loaded extras.
    if len(loaded) > 1:
        if any(m.get("key") == cfg.llm.model for m in loaded):
            return {"synced": False, "reason": "already in sync"}
        return {
            "synced": False,
            "reason": f"{len(loaded)} models loaded — ambiguous",
        }

    loaded_model = loaded[0]
    loaded_key = loaded_model.get("key", "")

    if not loaded_key:
        return {"synced": False, "reason": "loaded model has no key"}

    if loaded_key == cfg.llm.model:
        return {"synced": False, "reason": "already in sync"}

    # Resolve capabilities from live data, fallback to KNOWN_MODELS.
    live_caps = loaded_model.get("capabilities", {})
    known = KNOWN_MODELS.get(loaded_key, {})
    supports_thinking = live_caps.get(
        "thinking", known.get("thinking", False),
    )
    supports_vision = live_caps.get(
        "vision", known.get("vision", False),
    )

    object.__setattr__(cfg.llm, "model", loaded_key)
    object.__setattr__(cfg.llm, "supports_thinking", supports_thinking)
    object.__setattr__(cfg.llm, "supports_vision", supports_vision)

    logger.info(
        "sync-model: config updated to '{}' (thinking={}, vision={})",
        loaded_key, supports_thinking, supports_vision,
    )
    return {"synced": True, "model": loaded_key}
