"""O.M.N.I.A. — Configuration endpoints (read/update runtime config)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request

from backend.core.config import KNOWN_MODELS
from backend.core.context import AppContext

router = APIRouter()


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


@router.get("/config/models")
async def list_models(request: Request) -> list[dict[str, Any]]:
    """Fetch locally available models from Ollama and return enriched metadata."""
    ctx = _ctx(request)
    active_model = ctx.config.llm.model
    ollama_base = ctx.config.llm.base_url  # e.g. http://localhost:11434

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ollama_base}/api/tags")
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, Exception):
        return []

    models: list[dict[str, Any]] = []
    for m in data.get("models", []):
        name = m.get("name", "")
        caps = KNOWN_MODELS.get(name, {"vision": False, "thinking": False})
        models.append({
            "name": name,
            "size": m.get("size", 0),
            "modified_at": m.get("modified_at", ""),
            "is_active": name == active_model,
            "capabilities": {
                "vision": caps.get("vision", False),
                "thinking": caps.get("thinking", False),
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
            object.__setattr__(cfg.llm, "model", new_model)
            caps = KNOWN_MODELS.get(new_model, {"vision": False, "thinking": False})
            object.__setattr__(cfg.llm, "supports_vision", caps.get("vision", False))
            object.__setattr__(cfg.llm, "supports_thinking", caps.get("thinking", False))
        if "temperature" in llm_updates:
            object.__setattr__(cfg.llm, "temperature", float(llm_updates["temperature"]))
        if "max_tokens" in llm_updates:
            object.__setattr__(cfg.llm, "max_tokens", int(llm_updates["max_tokens"]))

    if "ui" in body:
        ui_updates = body["ui"]
        if "theme" in ui_updates:
            object.__setattr__(cfg.ui, "theme", ui_updates["theme"])
        if "language" in ui_updates:
            object.__setattr__(cfg.ui, "language", ui_updates["language"])

    # Return the full config after applying changes.
    return await get_config(request)
