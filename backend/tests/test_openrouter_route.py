"""AL\\CE — Tests for the OpenRouter REST route serialisers."""

from __future__ import annotations

from backend.api.routes.openrouter import (
    OpenRouterCreditsResponse,
    _serialise_model,
)


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
