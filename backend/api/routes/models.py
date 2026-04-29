"""AL\\CE — Model management endpoints using LM Studio v1 API."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field, field_validator

from backend.core.config import KNOWN_MODELS
from backend.core.context import AppContext
from backend.core.protocols import LMStudioManagerProtocol

router = APIRouter(tags=["models"])

# ---------------------------------------------------------------------------
# /models/status cache
# ---------------------------------------------------------------------------
# A handful of components in the renderer poll ``/models/status`` every few
# seconds (connection badge, ModelSelector, etc.).  Each call would otherwise
# hit ``GET /api/v1/models`` on LM Studio, which is expensive when the server
# is busy generating or loading a model and quickly degrades into a stream of
# 500 / ReadTimeout warnings in the backend log.  We coalesce concurrent
# callers behind a short TTL cache so LM Studio is queried at most once per
# ``_STATUS_CACHE_TTL`` window (longer when the previous probe failed).
_STATUS_CACHE_TTL: float = 4.0
_STATUS_CACHE_TTL_DOWN: float = 15.0
_status_cache: dict[str, Any] = {"value": None, "expires_at": 0.0}
_status_cache_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class LoadModelRequest(BaseModel):
    """Body for ``POST /models/load``."""

    model: str
    context_length: int | None = None
    flash_attention: bool | None = None
    eval_batch_size: int | None = None
    num_experts: int | None = None
    offload_kv_cache_to_gpu: bool | None = None

    @field_validator("model")
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model must not be empty")
        return v

    @field_validator("context_length")
    @classmethod
    def context_length_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("context_length must be a positive integer")
        return v

    @field_validator("eval_batch_size")
    @classmethod
    def eval_batch_size_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("eval_batch_size must be a positive integer")
        return v

    @field_validator("num_experts")
    @classmethod
    def num_experts_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("num_experts must be a positive integer")
        return v


class UnloadModelRequest(BaseModel):
    """Body for ``POST /models/unload``."""

    instance_id: str

    @field_validator("instance_id")
    @classmethod
    def instance_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("instance_id must not be empty")
        return v


class DownloadModelRequest(BaseModel):
    """Body for ``POST /models/download``."""

    model: str
    quantization: str | None = None

    @field_validator("model")
    @classmethod
    def model_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("model must not be empty")
        return v


class ModelStatusResponse(BaseModel):
    """Response for ``GET /models/status``."""

    connected: bool
    loaded_model_count: int = 0
    total_model_count: int = 0
    loaded_models: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


def _manager(request: Request) -> LMStudioManagerProtocol:
    """Return the ``LMStudioManager`` or raise 503."""
    ctx = _ctx(request)
    mgr = ctx.lmstudio_manager
    if mgr is None:
        raise HTTPException(503, "LM Studio manager not initialised")
    return mgr


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/models/operation")
async def get_current_operation(request: Request) -> dict:
    """Return the status of the current model operation."""
    mgr = _manager(request)
    op = mgr.current_operation
    if op is None:
        return {"status": "idle"}
    return op


@router.get("/models/capabilities")
async def model_capabilities(request: Request) -> dict[str, Any]:
    """Return the capability registry state for all known models."""
    ctx = _ctx(request)
    if ctx.model_registry is None:
        return {"profiles": {}, "last_refresh": 0}
    profiles = ctx.model_registry.all_profiles()
    return {
        "profiles": {
            k: v.to_dict() for k, v in profiles.items()
        },
        "last_refresh": ctx.model_registry.last_refresh,
    }


@router.get("/models")
async def list_models(request: Request) -> list[dict[str, Any]]:
    """List all models via LM Studio v1 API."""
    mgr = _manager(request)
    try:
        data = await mgr.list_models()
    except httpx.HTTPError:
        raise HTTPException(503, "LM Studio is unreachable")

    models = data.get("models", [])

    # Refresh the model capability registry with fresh API data.
    ctx = _ctx(request)
    if ctx.model_registry is not None:
        await ctx.model_registry.refresh_from_api(models)

    return [serialise_model(m, ctx.model_registry) for m in models]


@router.post("/models/load")
async def load_model(body: LoadModelRequest, request: Request) -> dict:
    """Load a model into LM Studio."""
    ctx = _ctx(request)
    mgr = _manager(request)
    if mgr.is_busy:
        raise HTTPException(
            409, "Another model operation is already in progress",
        )
    try:
        result = await mgr.load_model(
            body.model,
            context_length=body.context_length,
            flash_attention=body.flash_attention,
            eval_batch_size=body.eval_batch_size,
            num_experts=body.num_experts,
            offload_kv_cache_to_gpu=body.offload_kv_cache_to_gpu,
        )
        # Invalidate auto-model cache so the next chat uses the new model.
        if ctx.llm_service is not None:
            ctx.llm_service.invalidate_model_cache()
        # Drop the cached /models/status snapshot so the UI reflects the
        # newly loaded model on the next poll.
        _invalidate_status_cache()
        # Refresh registry so newly loaded model has up-to-date caps.
        if ctx.model_registry is not None:
            try:
                data = await mgr.list_models()
                await ctx.model_registry.refresh_from_api(
                    data.get("models", []),
                )
            except Exception:
                pass  # non-critical; next list_models will refresh
        return result
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except httpx.HTTPError as exc:
        logger.error("Load model failed: {}", exc)
        raise HTTPException(503, "LM Studio is unreachable")


@router.post("/models/unload")
async def unload_model(body: UnloadModelRequest, request: Request) -> dict:
    """Unload a model from LM Studio."""
    ctx = _ctx(request)
    mgr = _manager(request)
    if mgr.is_busy:
        raise HTTPException(
            409, "Another model operation is already in progress",
        )
    try:
        result = await mgr.unload_model(body.instance_id)
        # Invalidate auto-model cache after unload.
        if ctx.llm_service is not None:
            ctx.llm_service.invalidate_model_cache()
        _invalidate_status_cache()
        return result
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except httpx.HTTPError as exc:
        logger.error("Unload model failed: {}", exc)
        raise HTTPException(503, "LM Studio is unreachable")


@router.post("/models/download")
async def download_model(body: DownloadModelRequest, request: Request) -> dict:
    """Start a model download on LM Studio."""
    mgr = _manager(request)
    try:
        return await mgr.download_model(
            body.model, quantization=body.quantization,
        )
    except httpx.HTTPError as exc:
        logger.error("Download model failed: {}", exc)
        raise HTTPException(503, "LM Studio is unreachable")


@router.get("/models/download/{job_id}")
async def download_status(job_id: str, request: Request) -> dict:
    """Get the status of a download job."""
    mgr = _manager(request)
    try:
        return await mgr.get_download_status(job_id)
    except httpx.HTTPError as exc:
        logger.error("Download status failed: {}", exc)
        raise HTTPException(503, "LM Studio is unreachable")


@router.get("/models/status")
async def models_status(request: Request) -> ModelStatusResponse:
    """Quick health-check + summary of loaded models.

    Cached for a few seconds so concurrent renderer pollers do not
    hammer LM Studio with one ``GET /api/v1/models`` per call.  When
    the previous probe failed the cache TTL is extended so a slow or
    unreachable LM Studio is not retried on every request.
    """
    mgr = _manager(request)

    now = time.monotonic()
    cached = _status_cache["value"]
    if cached is not None and now < _status_cache["expires_at"]:
        return cached

    async with _status_cache_lock:
        # Re-check inside the lock: another coroutine may have refreshed
        # the cache while we were waiting.
        cached = _status_cache["value"]
        now = time.monotonic()
        if cached is not None and now < _status_cache["expires_at"]:
            return cached

        try:
            data = await mgr.list_models()
        except httpx.HTTPError:
            response = ModelStatusResponse(connected=False)
            _status_cache["value"] = response
            _status_cache["expires_at"] = time.monotonic() + _STATUS_CACHE_TTL_DOWN
            return response

        all_models = data.get("models", [])
        loaded = [
            m["key"]
            for m in all_models
            if m.get("loaded_instances")
        ]
        response = ModelStatusResponse(
            connected=True,
            loaded_model_count=len(loaded),
            total_model_count=len(all_models),
            loaded_models=loaded,
        )
        _status_cache["value"] = response
        _status_cache["expires_at"] = time.monotonic() + _STATUS_CACHE_TTL
        return response


def _invalidate_status_cache() -> None:
    """Force the next ``/models/status`` request to re-query LM Studio.

    Called by load/unload routes so the UI reflects the new state
    immediately instead of waiting for the cache TTL to expire.
    """
    _status_cache["value"] = None
    _status_cache["expires_at"] = 0.0


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def serialise_model(
    m: dict,
    registry: Any | None = None,
) -> dict[str, Any]:
    """Transform a v1 API model object into the AL\\CE response shape.

    Uses the ``ModelCapabilityRegistry`` when available for consistent
    capability resolution; falls back to ``KNOWN_MODELS`` otherwise.

    Shared by both ``/api/models`` and ``/api/config/models`` to ensure
    a single, consistent serialisation for the frontend ``LMStudioModel``
    type.
    """
    key = m.get("key", "")
    caps = m.get("capabilities", {})
    quant = m.get("quantization")

    # Resolve capabilities: registry → API response → KNOWN_MODELS
    if registry is not None:
        profile = registry.get_profile(key)
        resolved_caps = {
            "vision": profile.supports_vision,
            "thinking": profile.supports_thinking,
            "trained_for_tool_use": profile.supports_tool_use,
        }
    else:
        known = KNOWN_MODELS.get(key, {})
        resolved_caps = {
            "vision": caps.get("vision", False),
            "thinking": caps.get(
                "thinking", known.get("thinking", False),
            ),
            "trained_for_tool_use": caps.get("trained_for_tool_use", False),
        }

    return {
        "name": key,
        "display_name": m.get("display_name", key),
        "type": m.get("type", "llm"),
        "size": m.get("size_bytes", 0),
        "modified_at": "",
        "is_active": bool(m.get("loaded_instances")),
        "loaded": bool(m.get("loaded_instances")),
        "loaded_instances": m.get("loaded_instances", []),
        "architecture": m.get("architecture"),
        "quantization": {
            "name": quant.get("name") if quant else None,
            "bits_per_weight": quant.get("bits_per_weight") if quant else None,
        } if quant else None,
        "params_string": m.get("params_string"),
        "format": m.get("format"),
        "max_context_length": m.get("max_context_length", 0),
        "capabilities": resolved_caps,
    }
