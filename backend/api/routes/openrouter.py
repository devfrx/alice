"""AL\\CE — OpenRouter endpoints (model catalog, credits)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.core.context import AppContext

router = APIRouter(tags=["openrouter"])


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


def _safe_float(value: Any) -> float | None:
    """Coerce an untrusted upstream value to float (None when absent/invalid)."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Response models (contract-first: the ratchet requires a response_model)
# ---------------------------------------------------------------------------


class OpenRouterPricing(BaseModel):
    """Per-token price (USD), ``None`` when not reported."""

    prompt: float | None = None
    completion: float | None = None


class OpenRouterModelOut(BaseModel):
    """An OpenRouter catalog model, reduced to the fields used by the UI."""

    id: str
    name: str
    description: str = ""
    context_length: int = 0
    pricing: OpenRouterPricing
    supports_tools: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False


class OpenRouterModelsResponse(BaseModel):
    """OpenRouter model catalog."""

    models: list[OpenRouterModelOut]


class OpenRouterCreditsResponse(BaseModel):
    """Credits/limits state for the API key (from ``GET /v1/key``)."""

    limit: float | None = None
    limit_remaining: float | None = None
    usage: float = 0.0
    is_free_tier: bool | None = None
    """``None`` means unknown/not reported by OpenRouter, not "false"."""

    @classmethod
    def from_key_data(cls, data: dict[str, Any]) -> OpenRouterCreditsResponse:
        """Build from the raw ``data`` object of the /v1/key response."""
        return cls(
            limit=_safe_float(data.get("limit")),
            limit_remaining=_safe_float(data.get("limit_remaining")),
            usage=_safe_float(data.get("usage")) or 0.0,
            is_free_tier=data.get("is_free_tier"),
        )


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------


def _serialise_model(m: dict[str, Any]) -> OpenRouterModelOut:
    """Map a raw OpenRouter catalog entry to the UI shape."""
    params = m.get("supported_parameters") or []
    arch = m.get("architecture") or {}
    pricing = m.get("pricing") or {}

    model_id = m.get("id", "")
    return OpenRouterModelOut(
        id=model_id,
        name=m.get("name") or model_id,
        description=(m.get("description") or "")[:500],
        context_length=int(
            m.get("context_length")
            or (m.get("top_provider") or {}).get("context_length")
            or 0
        ),
        pricing=OpenRouterPricing(
            prompt=_safe_float(pricing.get("prompt")),
            completion=_safe_float(pricing.get("completion")),
        ),
        supports_tools="tools" in params,
        supports_vision="image" in (arch.get("input_modalities") or []),
        supports_reasoning="reasoning" in params,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/openrouter/models", response_model=OpenRouterModelsResponse)
async def list_openrouter_models(
    request: Request, force_refresh: bool = False,
) -> OpenRouterModelsResponse:
    """Return the OpenRouter model catalog (cached server-side, TTL 1h)."""
    ctx = _ctx(request)
    svc = ctx.openrouter_service
    if svc is None:
        raise HTTPException(503, "OpenRouter service unavailable")
    try:
        models = await svc.list_models(force_refresh=force_refresh)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            502, f"OpenRouter returned {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "OpenRouter unreachable") from exc
    except ValueError as exc:
        raise HTTPException(502, "OpenRouter returned malformed data") from exc
    return OpenRouterModelsResponse(
        models=[_serialise_model(m) for m in models],
    )


@router.get("/openrouter/credits", response_model=OpenRouterCreditsResponse)
async def get_openrouter_credits(request: Request) -> OpenRouterCreditsResponse:
    """Return credits/limits for the configured OpenRouter API key."""
    ctx = _ctx(request)
    svc = ctx.openrouter_service
    if svc is None:
        raise HTTPException(503, "OpenRouter service unavailable")
    if not ctx.config.llm.openrouter_api_key:
        raise HTTPException(400, "OpenRouter API key not configured")
    try:
        data = await svc.get_credits()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            raise HTTPException(401, "OpenRouter API key invalid") from exc
        raise HTTPException(
            502, f"OpenRouter returned {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "OpenRouter unreachable") from exc
    except ValueError as exc:
        raise HTTPException(502, "OpenRouter returned malformed data") from exc
    return OpenRouterCreditsResponse.from_key_data(data)
