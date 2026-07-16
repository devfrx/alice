"""AL\\CE — Tests for the OpenRouter REST route serialisers and endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.openrouter import (
    OpenRouterCreditsResponse,
    _serialise_model,
    router,
)
from backend.core.config import LLMConfig


def test_serialise_model_maps_capabilities_and_pricing() -> None:
    out = _serialise_model({
        "id": "anthropic/claude-sonnet-5",
        "name": "Anthropic: Claude Sonnet 5",
        "description": "x" * 900,
        "context_length": 200000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "architecture": {"input_modalities": ["text", "image"]},
        "supported_parameters": ["tools", "reasoning"],
    })
    assert out.id == "anthropic/claude-sonnet-5"
    assert out.context_length == 200000
    assert out.pricing.prompt == 0.000003
    assert out.pricing.completion == 0.000015
    assert out.supports_tools and out.supports_vision and out.supports_reasoning
    assert len(out.description) == 500  # troncata


def test_serialise_model_tolerates_missing_fields() -> None:
    out = _serialise_model({"id": "x/y"})
    assert out.name == "x/y"
    assert out.pricing.prompt is None
    assert out.supports_tools is False


def test_credits_response_from_key_payload() -> None:
    resp = OpenRouterCreditsResponse.from_key_data({
        "limit": 10.0, "limit_remaining": 7.5, "usage": 2.5,
        "is_free_tier": False,
    })
    assert resp.limit_remaining == 7.5
    assert resp.usage == 2.5


# ---------------------------------------------------------------------------
# Endpoint-level tests (TestClient + mocked AppContext)
# ---------------------------------------------------------------------------


_MODEL_SAMPLE = {
    "id": "anthropic/claude-sonnet-5",
    "name": "Anthropic: Claude Sonnet 5",
    "description": "A capable model.",
    "context_length": 200000,
    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
    "architecture": {"input_modalities": ["text", "image"]},
    "supported_parameters": ["tools", "reasoning"],
}


def _make_app(openrouter_service: object | None, api_key: str = "sk-or-x") -> FastAPI:
    """Create a minimal FastAPI app with the openrouter router and mocked context."""
    app = FastAPI()
    app.include_router(router, prefix="/api")

    ctx = MagicMock()
    ctx.openrouter_service = openrouter_service
    ctx.config.llm = LLMConfig(provider="openrouter", openrouter_api_key=api_key)

    app.state.context = ctx
    return app


class TestListModels:
    """GET /api/openrouter/models."""

    def test_happy_path(self) -> None:
        svc = MagicMock()
        svc.list_models = AsyncMock(return_value=[_MODEL_SAMPLE])
        app = _make_app(svc)

        with TestClient(app) as client:
            resp = client.get("/api/openrouter/models")

        assert resp.status_code == 200
        body = resp.json()
        assert body["models"][0]["id"] == "anthropic/claude-sonnet-5"

    def test_service_unavailable_503(self) -> None:
        app = _make_app(None)

        with TestClient(app) as client:
            resp = client.get("/api/openrouter/models")

        assert resp.status_code == 503

    def test_http_status_error_502(self) -> None:
        svc = MagicMock()
        svc.list_models = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "err",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(500),
            ),
        )
        app = _make_app(svc)

        with TestClient(app) as client:
            resp = client.get("/api/openrouter/models")

        assert resp.status_code == 502

    def test_malformed_json_value_error_502(self) -> None:
        svc = MagicMock()
        svc.list_models = AsyncMock(side_effect=ValueError("Expecting value"))
        app = _make_app(svc)

        with TestClient(app) as client:
            resp = client.get("/api/openrouter/models")

        assert resp.status_code == 502


class TestGetCredits:
    """GET /api/openrouter/credits."""

    def test_missing_api_key_400(self) -> None:
        svc = MagicMock()
        svc.get_credits = AsyncMock()
        app = _make_app(svc, api_key="")

        with TestClient(app) as client:
            resp = client.get("/api/openrouter/credits")

        assert resp.status_code == 400

    def test_invalid_api_key_401(self) -> None:
        svc = MagicMock()
        svc.get_credits = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "err",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(401),
            ),
        )
        app = _make_app(svc)

        with TestClient(app) as client:
            resp = client.get("/api/openrouter/credits")

        assert resp.status_code == 401

    def test_happy_path(self) -> None:
        svc = MagicMock()
        svc.get_credits = AsyncMock(
            return_value={
                "limit": 10.0,
                "limit_remaining": 7.5,
                "usage": 2.5,
                "is_free_tier": False,
            },
        )
        app = _make_app(svc)

        with TestClient(app) as client:
            resp = client.get("/api/openrouter/credits")

        assert resp.status_code == 200
        body = resp.json()
        assert body["limit_remaining"] == 7.5
