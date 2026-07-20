"""AL\\CE — REST tests for GET /api/tools/catalog."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

_ENTRY_KEYS = {
    "name",
    "plugin",
    "label",
    "description",
    "capabilities",
    "risk_level",
    "requires_confirmation",
    "mcp_server",
}


@pytest.mark.asyncio
async def test_catalog_returns_200_with_flat_entries(client: AsyncClient) -> None:
    """GET /api/tools/catalog → 200 with a (possibly empty) sorted tool list."""
    resp = await client.get("/api/tools/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"tools"}
    assert isinstance(body["tools"], list)

    if body["tools"]:
        first = body["tools"][0]
        assert set(first.keys()) == _ENTRY_KEYS
        assert isinstance(first["capabilities"], list)
        assert isinstance(first["requires_confirmation"], bool)
        names = [entry["name"] for entry in body["tools"]]
        assert names == sorted(names)
