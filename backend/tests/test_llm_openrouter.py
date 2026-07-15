"""AL\\CE — Tests for the OpenRouter provider path in the LLM layer."""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.config import PROJECT_ROOT, LLMConfig
from backend.services.llm_service import LLMService

pytestmark = pytest.mark.asyncio


def _openrouter_config(**overrides: Any) -> LLMConfig:
    base: dict[str, Any] = dict(
        provider="openrouter",
        openrouter_api_key="sk-or-test-123",
        openrouter_model="anthropic/claude-sonnet-5",
        system_prompt_file=str(PROJECT_ROOT / "config" / "system_prompt.md"),
    )
    base.update(overrides)
    return LLMConfig(**base)


def _service(**overrides) -> LLMService:
    return LLMService(_openrouter_config(**overrides))


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


async def test_openrouter_sets_auth_headers() -> None:
    svc = _service()
    assert svc._client.headers["authorization"] == "Bearer sk-or-test-123"
    assert "x-title" in svc._client.headers
    await svc.close()


async def test_local_provider_has_no_auth_header() -> None:
    svc = LLMService(LLMConfig(
        provider="lmstudio",
        system_prompt_file=str(PROJECT_ROOT / "config" / "system_prompt.md"),
    ))
    assert "authorization" not in svc._client.headers
    await svc.close()


# ---------------------------------------------------------------------------
# Model resolution — no HTTP probe for OpenRouter
# ---------------------------------------------------------------------------


async def test_resolve_returns_openrouter_model_without_probe() -> None:
    svc = _service()

    async def _fail_get(*_a, **_k):
        raise AssertionError("resolve() must not probe /models for openrouter")

    svc._client.get = _fail_get  # type: ignore[method-assign]
    assert await svc._resolve_model() == "anthropic/claude-sonnet-5"
    await svc.close()


async def test_resolve_falls_back_to_openrouter_auto() -> None:
    svc = _service(openrouter_model="")
    assert await svc._resolve_model() == "openrouter/auto"
    await svc.close()


# ---------------------------------------------------------------------------
# Streaming — OAI-compat path, payload, cost in usage event
# ---------------------------------------------------------------------------


class _FakeResponse:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        pass

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCM:
    def __init__(self, resp: _FakeResponse) -> None:
        self._resp = resp

    async def __aenter__(self) -> _FakeResponse:
        return self._resp

    async def __aexit__(self, *exc) -> bool:
        return False


def _sse(lines: list[str], captured: dict):
    def _stream(method: str, url: str, json: dict | None = None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _FakeStreamCM(_FakeResponse(lines))

    return _stream


_STREAM_LINES = [
    'data: {"choices":[{"delta":{"content":"ciao"},"finish_reason":null}]}',
    'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
    '"usage":{"prompt_tokens":10,"completion_tokens":5,"cost":0.00042}}',
    "data: [DONE]",
]


async def test_openrouter_chat_uses_oai_path_with_usage_accounting() -> None:
    svc = _service()
    captured: dict = {}
    svc._client.stream = _sse(_STREAM_LINES, captured)  # type: ignore[method-assign]

    events = [
        e async for e in svc.chat(
            [{"role": "user", "content": "ciao"}],
            user_content="ciao",  # native path would be taken for lmstudio
        )
    ]

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    # Usage accounting è automatico su OpenRouter: nessun campo extra.
    assert "usage" not in captured["payload"]
    assert captured["payload"]["model"] == "anthropic/claude-sonnet-5"
    tokens = [e for e in events if e["type"] == "token"]
    assert tokens and tokens[0]["content"] == "ciao"
    usage = [e for e in events if e["type"] == "usage"]
    assert usage == [{
        "type": "usage", "input_tokens": 10, "output_tokens": 5,
        "cost": 0.00042,
    }]
    await svc.close()


# ---------------------------------------------------------------------------
# Context window from capability registry
# ---------------------------------------------------------------------------


async def test_context_window_from_registry_for_openrouter() -> None:
    from backend.services.model_capability_registry import (
        ModelCapabilityRegistry,
        ModelProfile,
    )

    registry = ModelCapabilityRegistry()
    registry._profiles["anthropic/claude-sonnet-5"] = ModelProfile(
        model_id="anthropic/claude-sonnet-5",
        context_length=200000,
        source="openrouter_api",
    )
    svc = LLMService(_openrouter_config(), model_registry=registry)
    assert svc.get_cached_context_window() == 200000
    await svc.close()
