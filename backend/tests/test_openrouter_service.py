"""AL\\CE — Tests for the OpenRouter catalog/credits service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.config import LLMConfig
from backend.services.model_capability_registry import ModelCapabilityRegistry
from backend.services.openrouter_service import OpenRouterService

pytestmark = pytest.mark.asyncio

_CATALOG = [
    {
        "id": "anthropic/claude-sonnet-5",
        "name": "Anthropic: Claude Sonnet 5",
        "description": "A very good model",
        "context_length": 200000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "architecture": {"input_modalities": ["text", "image"]},
        "supported_parameters": ["tools", "reasoning", "temperature"],
        "top_provider": {"context_length": 200000},
    },
    {
        "id": "qwen/qwen3.5-72b",
        "name": "Qwen 3.5 72B",
        "context_length": 32768,
        "pricing": {"prompt": "0.0000004", "completion": "0.0000012"},
        "architecture": {"input_modalities": ["text"]},
        "supported_parameters": ["tools", "temperature"],
    },
]


def _config() -> LLMConfig:
    return LLMConfig(provider="openrouter", openrouter_api_key="sk-or-x")


def _json_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    return resp


async def test_list_models_caches_and_seeds_registry() -> None:
    registry = ModelCapabilityRegistry()
    svc = OpenRouterService(_config(), model_registry=registry)
    svc._http.get = AsyncMock(return_value=_json_response({"data": _CATALOG}))

    models = await svc.list_models()
    assert len(models) == 2
    # Seconda chiamata: cache, nessun secondo GET.
    await svc.list_models()
    assert svc._http.get.await_count == 1

    profile = registry.get_profile("anthropic/claude-sonnet-5")
    assert profile.supports_tool_use is True
    assert profile.supports_vision is True
    assert profile.supports_thinking is True
    assert profile.context_length == 200000
    assert profile.source == "openrouter_api"

    text_only = registry.get_profile("qwen/qwen3.5-72b")
    assert text_only.supports_vision is False
    assert text_only.supports_thinking is False
    await svc.close()


async def test_list_models_force_refresh_bypasses_cache() -> None:
    svc = OpenRouterService(_config())
    svc._http.get = AsyncMock(return_value=_json_response({"data": _CATALOG}))
    await svc.list_models()
    await svc.list_models(force_refresh=True)
    assert svc._http.get.await_count == 2
    await svc.close()


async def test_get_credits_sends_auth_header() -> None:
    svc = OpenRouterService(_config())
    svc._http.get = AsyncMock(return_value=_json_response({
        "data": {"limit": 10.0, "limit_remaining": 7.5, "usage": 2.5},
    }))

    data = await svc.get_credits()
    assert data["limit_remaining"] == 7.5
    _, kwargs = svc._http.get.await_args
    assert kwargs["headers"]["Authorization"] == "Bearer sk-or-x"
    await svc.close()
