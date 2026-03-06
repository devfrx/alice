"""O.M.N.I.A. — Configuration endpoints (read/update runtime config)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from backend.api.routes.models import serialise_model
from backend.core.config import KNOWN_MODELS
from backend.core.context import AppContext

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
        },
        "stt": {
            "engine": cfg.stt.engine,
            "model": cfg.stt.model,
            "language": cfg.stt.language,
            "device": cfg.stt.device,
        },
        "tts": {
            "engine": cfg.tts.engine,
            "voice": cfg.tts.voice,
            "sample_rate": cfg.tts.sample_rate,
        },
        "ui": {
            "theme": cfg.ui.theme,
            "language": cfg.ui.language,
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
            temp = float(llm_updates["temperature"])
            if not (0.0 <= temp <= 2.0):
                raise HTTPException(400, "temperature must be between 0.0 and 2.0")
            object.__setattr__(cfg.llm, "temperature", temp)
        if "max_tokens" in llm_updates:
            mt = int(llm_updates["max_tokens"])
            if mt <= 0:
                raise HTTPException(400, "max_tokens must be a positive integer")
            object.__setattr__(cfg.llm, "max_tokens", mt)

    if "ui" in body:
        ui_updates = body["ui"]
        if "theme" in ui_updates:
            object.__setattr__(cfg.ui, "theme", ui_updates["theme"])
        if "language" in ui_updates:
            object.__setattr__(cfg.ui, "language", ui_updates["language"])

    # Return the full config after applying changes.
    return await get_config(request)


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
