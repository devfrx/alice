"""Tests for QdrantService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import QdrantConfig
from backend.services.qdrant_service import (
    COLLECTION_MEMORY,
    COLLECTION_TOOLS,
    PROJECT_NS,
    QdrantService,
)


@pytest.fixture
def qdrant_config(tmp_path):
    """QdrantConfig pointing to a temp directory."""
    return QdrantConfig(mode="embedded", path=str(tmp_path / "qdrant"))


@pytest.fixture
def mock_qdrant_client():
    """Mock AsyncQdrantClient."""
    client = AsyncMock()
    client.collection_exists = AsyncMock(return_value=False)
    client.create_collection = AsyncMock()
    client.delete_collection = AsyncMock()
    client.upsert = AsyncMock()
    client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    client.delete = AsyncMock()
    client.scroll = AsyncMock(return_value=([], None))
    client.count = AsyncMock(return_value=MagicMock(count=0))
    client.get_collection = AsyncMock(
        return_value=MagicMock(
            config=MagicMock(
                params=MagicMock(
                    vectors=MagicMock(size=384)
                )
            )
        )
    )
    client.close = AsyncMock()
    return client


class TestQdrantServiceInit:
    def test_creates_with_embedded_mode(self, qdrant_config):
        service = QdrantService(qdrant_config)
        assert service._config.mode == "embedded"

    def test_creates_with_server_mode(self):
        config = QdrantConfig(mode="server", host="localhost", port=6333)
        service = QdrantService(config)
        assert service._config.mode == "server"


class TestQdrantServiceLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_embedded(self, qdrant_config):
        service = QdrantService(qdrant_config)
        with patch(
            "backend.services.qdrant_service.AsyncQdrantClient"
        ) as mock_cls:
            mock_cls.return_value = AsyncMock()
            await service.initialize()
            mock_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self, qdrant_config, mock_qdrant_client):
        service = QdrantService(qdrant_config)
        service._client = mock_qdrant_client
        await service.close()
        mock_qdrant_client.close.assert_awaited_once()


class TestEnsureCollection:
    @pytest.mark.asyncio
    async def test_creates_new_collection(
        self, qdrant_config, mock_qdrant_client,
    ):
        service = QdrantService(qdrant_config)
        service._client = mock_qdrant_client
        mock_qdrant_client.collection_exists.return_value = False

        await service.ensure_collection("test_coll", 384)

        mock_qdrant_client.create_collection.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_if_exists_same_dim(
        self, qdrant_config, mock_qdrant_client,
    ):
        service = QdrantService(qdrant_config)
        service._client = mock_qdrant_client
        mock_qdrant_client.collection_exists.return_value = True

        await service.ensure_collection("test_coll", 384)

        mock_qdrant_client.create_collection.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recreates_on_dim_mismatch(
        self, qdrant_config, mock_qdrant_client,
    ):
        service = QdrantService(qdrant_config)
        service._client = mock_qdrant_client
        mock_qdrant_client.collection_exists.return_value = True

        await service.ensure_collection("test_coll", 768)

        mock_qdrant_client.delete_collection.assert_awaited_once()
        mock_qdrant_client.create_collection.assert_awaited_once()


class TestCRUD:
    @pytest.mark.asyncio
    async def test_upsert(self, qdrant_config, mock_qdrant_client):
        service = QdrantService(qdrant_config)
        service._client = mock_qdrant_client
        from qdrant_client import models

        point = models.PointStruct(
            id="test-id", vector=[0.1, 0.2], payload={"key": "val"},
        )
        await service.upsert("coll", [point])
        mock_qdrant_client.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search(self, qdrant_config, mock_qdrant_client):
        service = QdrantService(qdrant_config)
        service._client = mock_qdrant_client

        results = await service.search("coll", [0.1, 0.2], k=5)
        assert results == []
        mock_qdrant_client.query_points.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_by_ids(self, qdrant_config, mock_qdrant_client):
        service = QdrantService(qdrant_config)
        service._client = mock_qdrant_client

        await service.delete("coll", ids=["id1", "id2"])
        mock_qdrant_client.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scroll(self, qdrant_config, mock_qdrant_client):
        service = QdrantService(qdrant_config)
        service._client = mock_qdrant_client

        records, offset = await service.scroll("coll", limit=10)
        assert records == []
        assert offset is None

    @pytest.mark.asyncio
    async def test_count(self, qdrant_config, mock_qdrant_client):
        service = QdrantService(qdrant_config)
        service._client = mock_qdrant_client

        n = await service.count("coll")
        assert n == 0


class TestConstants:
    def test_collection_names(self):
        assert COLLECTION_MEMORY == "alice_memory"
        assert COLLECTION_TOOLS == "alice_tools"

    def test_project_ns(self):
        assert isinstance(PROJECT_NS, uuid.UUID)


@pytest.mark.asyncio
async def test_try_clear_stale_lock_removes_orphan_lockfile(tmp_path):
    cfg = QdrantConfig(mode="embedded", path=str(tmp_path / "qd"))
    svc = QdrantService(cfg)
    # Simulate an orphan RocksDB lock with no holder.
    lock_dir = tmp_path / "qd"
    lock_dir.mkdir(parents=True)
    (lock_dir / ".lock").write_text("")
    removed = svc.try_clear_stale_lock()
    assert removed is True
    assert not (lock_dir / ".lock").exists()
