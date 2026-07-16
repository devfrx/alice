"""Tests for MemoryService (Qdrant backend)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from backend.core.config import MemoryConfig
from backend.services.memory_service import MemoryEntry, MemoryService


@pytest.fixture
def memory_config():
    return MemoryConfig(
        enabled=True,
        top_k=5,
        similarity_threshold=0.5,
        session_ttl_hours=24,
    )


@pytest.fixture
def memory_service(memory_config, mock_qdrant_service, mock_embedding_client):
    return MemoryService(memory_config, mock_qdrant_service, mock_embedding_client)


class TestMemoryServiceInit:
    @pytest.mark.asyncio
    async def test_initialize(self, memory_service, mock_qdrant_service):
        await memory_service.initialize()
        mock_qdrant_service.ensure_collection.assert_awaited_once()
        assert memory_service._cleanup_task is not None
        await memory_service.close()

    @pytest.mark.asyncio
    async def test_close_cancels_cleanup(
        self, memory_service, mock_qdrant_service,
    ):
        await memory_service.initialize()
        assert memory_service._cleanup_task is not None
        await memory_service.close()
        assert memory_service._cleanup_task is None


class TestMemoryServiceCRUD:
    @pytest.mark.asyncio
    async def test_add(
        self, memory_service, mock_qdrant_service, mock_embedding_client,
    ):
        entry = await memory_service.add(
            "test content", scope="long_term", category="test",
        )
        assert isinstance(entry, MemoryEntry)
        assert entry.content == "test content"
        mock_embedding_client.encode.assert_awaited_once_with("test content")
        mock_qdrant_service.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_with_explicit_expires(
        self, memory_service, mock_qdrant_service,
    ):
        expires = datetime(2026, 12, 31, tzinfo=UTC)
        entry = await memory_service.add(
            "session data", scope="session", expires_at=expires,
        )
        assert isinstance(entry, MemoryEntry)
        call_args = mock_qdrant_service.upsert.call_args
        point = call_args[0][1][0]
        assert point.payload["expires_at"] != ""

    @pytest.mark.asyncio
    async def test_search(
        self, memory_service, mock_qdrant_service, mock_embedding_client,
    ):
        hit = MagicMock()
        hit.id = "a1c3e5f7-0000-4000-8000-000000000001"
        hit.score = 0.9
        hit.payload = {
            "content": "test",
            "scope": "long_term",
            "category": "",
            "source": "user",
            "conversation_id": "",
            "created_at": "2024-01-01T00:00:00+00:00",
            "expires_at": "",
            "embedding_model": "test-model",
        }
        mock_qdrant_service.search.return_value = [hit]

        results = await memory_service.search("test query")
        assert len(results) == 1
        assert results[0]["score"] == 0.9
        assert isinstance(results[0]["entry"], MemoryEntry)

    @pytest.mark.asyncio
    async def test_search_filters_low_score(
        self, memory_service, mock_qdrant_service,
    ):
        hit = MagicMock()
        hit.id = "a1c3e5f7-0000-4000-8000-000000000001"
        hit.score = 0.1  # Below threshold
        hit.payload = {
            "content": "low score",
            "scope": "long_term",
            "category": "",
            "source": "user",
            "conversation_id": "",
            "created_at": "2024-01-01T00:00:00+00:00",
            "expires_at": "",
            "embedding_model": "test-model",
        }
        mock_qdrant_service.search.return_value = [hit]

        results = await memory_service.search("query")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_delete(self, memory_service, mock_qdrant_service):
        result = await memory_service.delete("test-id")
        assert result is True
        mock_qdrant_service.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_by_scope(
        self, memory_service, mock_qdrant_service,
    ):
        mock_qdrant_service.count.return_value = 3
        count = await memory_service.delete_by_scope("session")
        assert count == 3

    @pytest.mark.asyncio
    async def test_list(self, memory_service, mock_qdrant_service):
        record = MagicMock()
        record.id = "a1c3e5f7-0000-4000-8000-000000000001"
        record.payload = {
            "content": "test",
            "scope": "long_term",
            "category": "general",
            "source": "user",
            "conversation_id": "",
            "created_at": "2024-01-01T00:00:00+00:00",
            "expires_at": "",
            "embedding_model": "test-model",
        }
        mock_qdrant_service.scroll.return_value = ([record], None)
        mock_qdrant_service.count.return_value = 1

        entries, total = await memory_service.list()
        assert total == 1
        assert len(entries) == 1
        assert entries[0].content == "test"

    @pytest.mark.asyncio
    async def test_stats(self, memory_service, mock_qdrant_service):
        mock_qdrant_service.count.return_value = 5
        result = await memory_service.stats()
        assert result["total"] == 5
        assert "by_scope" in result

    @pytest.mark.asyncio
    async def test_delete_all(self, memory_service, mock_qdrant_service):
        mock_qdrant_service.count.return_value = 0
        count = await memory_service.delete_all()
        assert count == 0


class TestMemoryEntry:
    def test_to_dict(self):
        entry = MemoryEntry(
            id=uuid.UUID("a1c3e5f7-0000-4000-8000-000000000001"),
            content="hello world",
            scope="long_term",
            category="general",
            source="user",
            conversation_id=None,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            expires_at=None,
            embedding_model="test-model",
        )
        d = entry.to_dict()
        assert d["id"] == "a1c3e5f7-0000-4000-8000-000000000001"
        assert d["content"] == "hello world"
