"""Tests for Memory REST API (Phase 9)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.routes.memory import router
from backend.services.memory_service import MemoryEntry

_PREFIX = "/api/memory"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    content: str = "User prefers dark mode",
    scope: str = "long_term",
    category: str | None = "preference",
) -> MemoryEntry:
    return MemoryEntry(
        id=uuid.uuid4(),
        content=content,
        scope=scope,
        category=category,
        source="llm",
        created_at=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        expires_at=None,
        conversation_id=None,
        embedding_model="test-model",
    )


def _build_app(memory_service=None) -> FastAPI:
    """Lightweight FastAPI app with only the memory router mounted."""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.context = SimpleNamespace(memory_service=memory_service)
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_memory_service() -> AsyncMock:
    """Fully-configured mock memory service."""
    list_entry = _make_entry()
    search_entry = _make_entry(content="User likes Python")

    svc = AsyncMock()
    svc.list = AsyncMock(return_value=([list_entry], 1))
    svc.search = AsyncMock(return_value=[
        {"entry": search_entry, "score": 0.92},
    ])
    svc.delete = AsyncMock(return_value=True)
    svc.delete_by_scope = AsyncMock(return_value=5)
    svc.stats = AsyncMock(return_value={
        "total": 10,
        "by_scope": {"long_term": 8, "session": 2},
        "by_category": {"preference": 3, "fact": 7},
        "db_size_bytes": 1024,
    })
    return svc


@pytest.fixture
async def disabled_client():
    """Client for an app where memory_service is None (disabled)."""
    app = _build_app(memory_service=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def memory_client(mock_memory_service):
    """Client for an app with a mocked memory service."""
    app = _build_app(memory_service=mock_memory_service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, mock_memory_service


# ---------------------------------------------------------------------------
# 503 — memory service not available (default config)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMemoryDisabled:
    """Endpoints return 503 when memory_service is None."""

    async def test_list_memories_503_when_disabled(self, disabled_client):
        resp = await disabled_client.get(_PREFIX)
        assert resp.status_code == 503

    async def test_search_memories_503_when_disabled(self, disabled_client):
        resp = await disabled_client.post(f"{_PREFIX}/search", json={"query": "hello"})
        assert resp.status_code == 503

    async def test_delete_memory_503_when_disabled(self, disabled_client):
        mid = str(uuid.uuid4())
        resp = await disabled_client.delete(f"{_PREFIX}/{mid}")
        assert resp.status_code == 503

    async def test_delete_session_503_when_disabled(self, disabled_client):
        resp = await disabled_client.delete(f"{_PREFIX}/session")
        assert resp.status_code == 503

    async def test_stats_503_when_disabled(self, disabled_client):
        resp = await disabled_client.get(f"{_PREFIX}/stats")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Success paths — mocked memory service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMemoryEndpoints:
    """Endpoints return correct data when memory service is available."""

    async def test_list_memories_success(self, memory_client):
        client, _ = memory_client
        resp = await client.get(_PREFIX)
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["entries"]) == 1

    async def test_list_memories_with_filters(self, memory_client):
        client, _ = memory_client
        resp = await client.get(
            _PREFIX, params={"scope": "long_term", "limit": 10, "offset": 0}
        )
        assert resp.status_code == 200

    async def test_search_memories(self, memory_client):
        client, _ = memory_client
        resp = await client.post(
            f"{_PREFIX}/search", json={"query": "Python preferences"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["entry"]["content"] == "User likes Python"
        assert data["results"][0]["score"] == 0.92

    async def test_search_empty_query_returns_422(self, memory_client):
        client, _ = memory_client
        resp = await client.post(f"{_PREFIX}/search", json={"query": ""})
        assert resp.status_code == 422

    async def test_delete_memory(self, memory_client):
        client, _ = memory_client
        mid = str(uuid.uuid4())
        resp = await client.delete(f"{_PREFIX}/{mid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True

    async def test_delete_memory_not_found(self, memory_client):
        client, mock_svc = memory_client
        mock_svc.delete = AsyncMock(return_value=False)
        mid = str(uuid.uuid4())
        resp = await client.delete(f"{_PREFIX}/{mid}")
        assert resp.status_code == 404

    async def test_delete_memory_invalid_id_returns_400(self, memory_client):
        client, _ = memory_client
        resp = await client.delete(f"{_PREFIX}/not-a-uuid")
        assert resp.status_code == 400

    async def test_delete_session_memory(self, memory_client):
        client, _ = memory_client
        resp = await client.delete(f"{_PREFIX}/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted_count"] == 5

    async def test_stats(self, memory_client):
        client, _ = memory_client
        resp = await client.get(f"{_PREFIX}/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 10
        assert "by_scope" in data
        assert "by_category" in data
        assert data["db_size_bytes"] == 1024
