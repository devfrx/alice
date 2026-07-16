"""AL\\CE — Config route behaviour for the OpenRouter provider."""

from __future__ import annotations

import pytest

from backend.api.routes.config import _REDACT_KEYS, _redact
from backend.services.config_policy import is_preference_writable, is_secret_path


def test_redact_masks_openrouter_api_key() -> None:
    assert "openrouter_api_key" in _REDACT_KEYS
    node = {"llm": {"openrouter_api_key": "sk-or-secret", "model": "auto"}}
    redacted = _redact(node)
    assert redacted["llm"]["openrouter_api_key"] == "***"
    assert redacted["llm"]["model"] == "auto"


def test_openrouter_keys_are_persistable_preferences() -> None:
    # ``openrouter_api_key`` is a secret (SecretStore-only, never a config
    # layer); the rest are policy-writable preferences.
    assert is_secret_path("llm.openrouter_api_key")
    for key in ("provider", "openrouter_model", "openrouter_favorites"):
        assert is_preference_writable(f"llm.{key}")


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

    async def test_provider_is_normalized_in_memory_but_raw_in_prefs(
        self, client, app,
    ) -> None:
        """Resolution normalizes case; the persisted preferences row does
        not — the preferences layer holds the user's literal input, exactly
        like the user/system YAML layers (canonical form is re-derived on
        every resolve, never written back to the layer)."""
        ctx = app.state.context

        resp = await client.put(
            "/api/config", json={"llm": {"provider": "OpenRouter"}},
        )

        assert resp.status_code == 200
        assert ctx.config.llm.provider == "openrouter"
        prefs = await ctx.preferences_store.load()
        assert prefs["llm"]["provider"] == "OpenRouter"

    async def test_invalid_provider_returns_422(self, client) -> None:
        # Task 11: validation now happens in the pydantic model via
        # set_many, so a bad value is a 422 (was a hand-rolled 400).
        resp = await client.put(
            "/api/config", json={"llm": {"provider": "bogus"}},
        )
        assert resp.status_code == 422

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

        # Secrets never land in the preferences DB — the real value only
        # ever lives in the SecretStore (Task 5).
        assert ctx.secret_store.cached()["llm.openrouter_api_key"] == "sk-or-real-secret"
        prefs = await ctx.preferences_store.load()
        assert "openrouter_api_key" not in prefs.get("llm", {})

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

        assert ctx.secret_store.cached()["llm.openrouter_api_key"] == "sk-or-real-secret"
        prefs = await ctx.preferences_store.load()
        assert "openrouter_api_key" not in prefs.get("llm", {})

    async def test_api_key_lands_in_secret_store_not_in_db(self, client, app) -> None:
        ctx = app.state.context
        resp = await client.put(
            "/api/config",
            json={"llm": {"openrouter_api_key": "sk-or-secret-store"}},
        )
        assert resp.status_code == 200
        assert ctx.secret_store.cached()["llm.openrouter_api_key"] == "sk-or-secret-store"
        assert ctx.config.llm.openrouter_api_key.get_secret_value() == "sk-or-secret-store"
        prefs = await ctx.preferences_store.load()
        assert "openrouter_api_key" not in prefs.get("llm", {})

    async def test_null_api_key_deletes_secret(self, client, app) -> None:
        ctx = app.state.context
        await client.put(
            "/api/config", json={"llm": {"openrouter_api_key": "sk-or-todelete"}},
        )
        resp = await client.put(
            "/api/config", json={"llm": {"openrouter_api_key": None}},
        )
        assert resp.status_code == 200
        assert "llm.openrouter_api_key" not in ctx.secret_store.cached()
        assert ctx.config.llm.openrouter_api_key.get_secret_value() == ""
        assert resp.json()["llm"]["openrouter_api_key_configured"] is False
