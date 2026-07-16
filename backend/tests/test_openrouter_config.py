"""AL\\CE — Config route behaviour for the OpenRouter provider."""

from __future__ import annotations

import pytest

from backend.api.routes.config import _REDACT_KEYS, _redact
from backend.services.preferences_service import PERSISTABLE_LLM_KEYS


def test_redact_masks_openrouter_api_key() -> None:
    assert "openrouter_api_key" in _REDACT_KEYS
    node = {"llm": {"openrouter_api_key": "sk-or-secret", "model": "auto"}}
    redacted = _redact(node)
    assert redacted["llm"]["openrouter_api_key"] == "***"
    assert redacted["llm"]["model"] == "auto"


def test_openrouter_keys_are_persistable_preferences() -> None:
    for key in (
        "provider",
        "openrouter_api_key",
        "openrouter_model",
        "openrouter_favorites",
    ):
        assert key in PERSISTABLE_LLM_KEYS


# ---------------------------------------------------------------------------
# Endpoint-level tests (full app lifespan via the ``client``/``app`` fixtures
# from tests/conftest.py — in-memory DB, real LLMService construction).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProviderSwitch:
    """PUT /api/config — provider switch rebuilds ``ctx.llm_service``."""

    async def test_switching_provider_rebuilds_llm_service(self, client, app) -> None:
        ctx = app.state.context
        old_service = ctx.llm_service

        resp = await client.put(
            "/api/config", json={"llm": {"provider": "openrouter"}},
        )

        assert resp.status_code == 200
        assert resp.json()["llm"]["provider"] == "openrouter"
        assert ctx.config.llm.provider == "openrouter"
        assert ctx.llm_service is not old_service

    async def test_provider_is_normalized_in_memory_and_in_prefs(
        self, client, app,
    ) -> None:
        ctx = app.state.context

        resp = await client.put(
            "/api/config", json={"llm": {"provider": "OpenRouter"}},
        )

        assert resp.status_code == 200
        assert ctx.config.llm.provider == "openrouter"
        prefs = await ctx.preferences_service.load_all()
        assert prefs["llm"]["provider"] == "openrouter"

    async def test_invalid_provider_returns_400(self, client) -> None:
        resp = await client.put(
            "/api/config", json={"llm": {"provider": "bogus"}},
        )
        assert resp.status_code == 400

    async def test_masked_api_key_is_not_persisted_over_real_key(
        self, client, app,
    ) -> None:
        ctx = app.state.context

        seed = await client.put(
            "/api/config",
            json={
                "llm": {
                    "provider": "openrouter",
                    "openrouter_api_key": "sk-or-real-secret",
                },
            },
        )
        assert seed.status_code == 200
        assert ctx.config.llm.openrouter_api_key.get_secret_value() == "sk-or-real-secret"

        masked = await client.put(
            "/api/config", json={"llm": {"openrouter_api_key": "***"}},
        )
        assert masked.status_code == 200
        assert ctx.config.llm.openrouter_api_key.get_secret_value() == "sk-or-real-secret"

    async def test_masked_api_key_does_not_clobber_persisted_preference(
        self, client, app,
    ) -> None:
        ctx = app.state.context

        seed = await client.put(
            "/api/config",
            json={"llm": {"openrouter_api_key": "sk-or-real-secret"}},
        )
        assert seed.status_code == 200

        masked = await client.put(
            "/api/config", json={"llm": {"openrouter_api_key": "***"}},
        )
        assert masked.status_code == 200

        prefs = await ctx.preferences_service.load_all()
        assert prefs["llm"]["openrouter_api_key"] == "sk-or-real-secret"

    async def test_empty_api_key_is_a_noop_in_memory_and_in_prefs(
        self, client, app,
    ) -> None:
        ctx = app.state.context

        seed = await client.put(
            "/api/config",
            json={"llm": {"openrouter_api_key": "sk-or-real-secret"}},
        )
        assert seed.status_code == 200

        cleared = await client.put(
            "/api/config", json={"llm": {"openrouter_api_key": ""}},
        )
        assert cleared.status_code == 200
        assert ctx.config.llm.openrouter_api_key.get_secret_value() == "sk-or-real-secret"

        prefs = await ctx.preferences_service.load_all()
        assert prefs["llm"]["openrouter_api_key"] == "sk-or-real-secret"
