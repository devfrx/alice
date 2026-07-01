"""Tests for backend.services.knowledge.service — KnowledgeService (Fase 4)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.services.knowledge import (
    CompositeKnowledgeBackend,
    ContinuumClient,
    KnowledgeDocCreate,
    KnowledgeDocPatch,
    QdrantBackend,
)
from backend.services.knowledge.service import (
    KnowledgeService,
    build_knowledge_service,
)


@pytest.fixture
def backend() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def memory() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(backend: AsyncMock, memory: AsyncMock) -> KnowledgeService:
    return KnowledgeService(backend=backend, memory_service=memory)


def _client() -> ContinuumClient:
    return ContinuumClient(
        base_url="http://localhost:9",
        api_token=None,
        timeout_s=1.0,
        folder_cache_ttl_s=1.0,
    )


class TestDelegation:
    """Every protocol operation delegates 1:1 to the wrapped backend."""

    @pytest.mark.asyncio
    async def test_search_delegates(self, service, backend):
        backend.search = AsyncMock(return_value=[])
        out = await service.search(
            "q", kind="memory", k=3, filters={"category": "fact"},
        )
        assert out == []
        backend.search.assert_awaited_once_with(
            "q", kind="memory", k=3, filters={"category": "fact"},
        )

    @pytest.mark.asyncio
    async def test_get_delegates(self, service, backend):
        backend.get = AsyncMock(return_value=None)
        assert await service.get("id1", kind="note") is None
        backend.get.assert_awaited_once_with("id1", kind="note")

    @pytest.mark.asyncio
    async def test_create_delegates(self, service, backend):
        doc = KnowledgeDocCreate(kind="memory", content="x")
        backend.create = AsyncMock(return_value="created")
        assert await service.create(doc) == "created"
        backend.create.assert_awaited_once_with(doc)

    @pytest.mark.asyncio
    async def test_update_delegates(self, service, backend):
        patch = KnowledgeDocPatch(title="t")
        backend.update = AsyncMock(return_value=None)
        assert await service.update("id1", patch, kind="note") is None
        backend.update.assert_awaited_once_with("id1", patch, kind="note")

    @pytest.mark.asyncio
    async def test_delete_delegates(self, service, backend):
        backend.delete = AsyncMock(return_value=True)
        assert await service.delete("id1", kind="memory") is True
        backend.delete.assert_awaited_once_with("id1", kind="memory")

    @pytest.mark.asyncio
    async def test_list_delegates(self, service, backend):
        backend.list = AsyncMock(return_value=([], 0))
        assert await service.list(kind="memory", limit=5, offset=2) == ([], 0)
        backend.list.assert_awaited_once_with(
            kind="memory", filters=None, limit=5, offset=2,
        )

    @pytest.mark.asyncio
    async def test_delete_by_filter_delegates(self, service, backend):
        backend.delete_by_filter = AsyncMock(return_value=4)
        out = await service.delete_by_filter(
            kind="memory", filters={"scope": "session"},
        )
        assert out == 4
        backend.delete_by_filter.assert_awaited_once_with(
            kind="memory", filters={"scope": "session"},
        )

    @pytest.mark.asyncio
    async def test_health_delegates(self, service, backend):
        backend.health = AsyncMock(return_value="ok")
        assert await service.health() == "ok"


class TestMemoryAdmin:
    """Admin operations outside the backend protocol."""

    def test_memory_available(self, backend, memory):
        assert KnowledgeService(
            backend=backend, memory_service=memory,
        ).memory_available is True
        assert KnowledgeService(
            backend=backend, memory_service=None,
        ).memory_available is False

    @pytest.mark.asyncio
    async def test_memory_stats_delegates(self, service, memory):
        memory.stats = AsyncMock(return_value={"total": 1})
        assert await service.memory_stats() == {"total": 1}

    @pytest.mark.asyncio
    async def test_memory_stats_raises_without_memory(self, backend):
        svc = KnowledgeService(backend=backend, memory_service=None)
        with pytest.raises(RuntimeError):
            await svc.memory_stats()

    @pytest.mark.asyncio
    async def test_delete_all_memories_delegates(self, service, memory):
        memory.delete_all = AsyncMock(return_value=7)
        assert await service.delete_all_memories() == 7

    @pytest.mark.asyncio
    async def test_delete_all_memories_raises_without_memory(self, backend):
        svc = KnowledgeService(backend=backend, memory_service=None)
        with pytest.raises(RuntimeError):
            await svc.delete_all_memories()


class TestFactory:
    """build_knowledge_service is the single wiring implementation."""

    def test_qdrant_only_when_continuum_disabled(self, memory):
        svc = build_knowledge_service(
            continuum_enabled=False,
            memory_service=memory,
            continuum_client=None,
        )
        assert isinstance(svc.backend, QdrantBackend)

    def test_composite_when_continuum_enabled(self, memory):
        svc = build_knowledge_service(
            continuum_enabled=True,
            memory_service=memory,
            continuum_client=_client(),
        )
        assert isinstance(svc.backend, CompositeKnowledgeBackend)

    def test_qdrant_only_when_client_missing(self, memory):
        svc = build_knowledge_service(
            continuum_enabled=True,
            memory_service=memory,
            continuum_client=None,
        )
        assert isinstance(svc.backend, QdrantBackend)

    def test_memory_available_flows_through(self):
        svc = build_knowledge_service(
            continuum_enabled=False,
            memory_service=None,
            continuum_client=None,
        )
        assert svc.memory_available is False
