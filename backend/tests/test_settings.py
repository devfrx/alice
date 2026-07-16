"""Tests for the /settings/ REST endpoints."""

from __future__ import annotations

import pytest

_URL = "/api/settings/tool-confirmations"


@pytest.mark.asyncio
class TestToolConfirmations:
    """Tests for PUT / GET /api/settings/tool-confirmations."""

    async def test_get_default_returns_true(self, client):
        resp = await client.get(_URL)
        assert resp.status_code == 200
        assert resp.json()["confirmations_enabled"] is True

    async def test_put_disable(self, client):
        resp = await client.put(_URL, json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["confirmations_enabled"] is False

    async def test_get_after_disable(self, client):
        await client.put(_URL, json={"enabled": False})
        resp = await client.get(_URL)
        assert resp.status_code == 200
        assert resp.json()["confirmations_enabled"] is False

    async def test_put_reenable(self, client):
        await client.put(_URL, json={"enabled": False})
        resp = await client.put(_URL, json={"enabled": True})
        assert resp.status_code == 200
        assert resp.json()["confirmations_enabled"] is True

    async def test_put_invalid_body_returns_422(self, client):
        resp = await client.put(_URL, json={"enabled": "nope"})
        assert resp.status_code == 422

    async def test_put_missing_field_returns_422(self, client):
        resp = await client.put(_URL, json={})
        assert resp.status_code == 422


_PREFS_URL = "/api/settings/preferences"


@pytest.mark.asyncio
class TestResetPreferences:
    """DELETE /api/settings/preferences — reset vivo, senza riavvio (audit M1)."""

    async def test_reset_drops_the_layer_live(self, client, app):
        ctx = app.state.context
        new_theme = "light" if ctx.config.ui.theme != "light" else "dark"
        seed = await client.put("/api/config", json={"ui": {"theme": new_theme}})
        assert seed.status_code == 200
        assert ctx.config.ui.theme == new_theme

        resp = await client.delete(_PREFS_URL)
        assert resp.status_code == 200
        assert resp.json()["deleted"] >= 1

        from backend.services.config_service import ConfigLayer

        assert ctx.config_service.get_layer(ConfigLayer.PREFERENCES) == {}
        assert ctx.config.ui.theme != new_theme

    async def test_reset_applies_reactions(self, client, app):
        ctx = app.state.context
        seed = await client.put("/api/config", json={"llm": {"provider": "openrouter"}})
        assert seed.status_code == 200
        old_service = ctx.llm_service

        resp = await client.delete(_PREFS_URL)
        assert resp.status_code == 200
        assert ctx.config.llm.provider == "lmstudio"
        # Il reset del provider passa dalle reazioni: servizio LLM ricostruito.
        assert ctx.llm_service is not old_service


_CATALOG_URL = "/api/settings/tool-catalog"
_ACTIVE_URL = "/api/settings/active-tools"


@pytest.mark.asyncio
class TestToolCatalog:
    """Tests for GET /api/settings/tool-catalog and PUT /active-tools."""

    async def test_catalog_shape(self, client):
        resp = await client.get(_CATALOG_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) >= {
            "tools_enabled",
            "tool_rag_enabled",
            "disabled_tools",
            "plugins",
        }
        assert isinstance(body["plugins"], list)
        assert body["disabled_tools"] == []

    async def test_set_active_tools_round_trips(self, client):
        resp = await client.put(
            _ACTIVE_URL, json={"disabled_tools": ["plugin_b", "plugin_a"]},
        )
        assert resp.status_code == 200
        # Stored sorted + deduplicated.
        assert resp.json()["disabled_tools"] == ["plugin_a", "plugin_b"]

        get_resp = await client.get(_CATALOG_URL)
        assert get_resp.json()["disabled_tools"] == ["plugin_a", "plugin_b"]

    async def test_set_active_tools_dedupes_and_drops_empty(self, client):
        resp = await client.put(
            _ACTIVE_URL, json={"disabled_tools": ["x", "x", "", "y"]},
        )
        assert resp.status_code == 200
        assert resp.json()["disabled_tools"] == ["x", "y"]

    async def test_clear_active_tools(self, client):
        await client.put(_ACTIVE_URL, json={"disabled_tools": ["x"]})
        resp = await client.put(_ACTIVE_URL, json={"disabled_tools": []})
        assert resp.status_code == 200
        assert resp.json()["disabled_tools"] == []

    async def test_disabled_tool_marked_in_catalog(self, client):
        """A tool present in the catalog is reported enabled=False once disabled."""
        catalog = (await client.get(_CATALOG_URL)).json()
        names = [
            t["name"]
            for plugin in catalog["plugins"]
            for t in plugin["tools"]
        ]
        if not names:
            pytest.skip("No plugins/tools loaded in the test app")
        target = names[0]
        await client.put(_ACTIVE_URL, json={"disabled_tools": [target]})
        updated = (await client.get(_CATALOG_URL)).json()
        flat = {
            t["name"]: t["enabled"]
            for plugin in updated["plugins"]
            for t in plugin["tools"]
        }
        assert flat[target] is False

    async def test_set_active_tools_invalid_body_returns_422(self, client):
        resp = await client.put(_ACTIVE_URL, json={"disabled_tools": "nope"})
        assert resp.status_code == 422
