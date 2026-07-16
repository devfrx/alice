"""Tests for backend.api.routes.email — REST endpoints (service unavailable)."""

from __future__ import annotations

from httpx import AsyncClient

# ---------------------------------------------------------------------------
# All endpoints return 503 when email service is disabled (default in tests)
# ---------------------------------------------------------------------------


async def test_inbox_503(client: AsyncClient):
    response = await client.get("/api/email/inbox")
    assert response.status_code == 503


async def test_get_email_503(client: AsyncClient):
    response = await client.get("/api/email/some-uid")
    assert response.status_code == 503


async def test_search_503(client: AsyncClient):
    response = await client.post(
        "/api/email/search",
        json={"query": "FROM test"},
    )
    assert response.status_code == 503


async def test_folders_503(client: AsyncClient):
    response = await client.get("/api/email/folders")
    assert response.status_code == 503


async def test_mark_read_503(client: AsyncClient):
    response = await client.put("/api/email/some-uid/read")
    assert response.status_code == 503


async def test_archive_503(client: AsyncClient):
    response = await client.put("/api/email/some-uid/archive")
    assert response.status_code == 503
