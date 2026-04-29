"""AL\\CE — Qdrant vector store service.

Pure vector-store wrapper: stores, retrieves, and deletes vector points.
Does NOT handle embedding — callers provide pre-computed vectors.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger
from qdrant_client import models
from qdrant_client.async_qdrant_client import AsyncQdrantClient

from backend.core.config import QdrantConfig

# ---------------------------------------------------------------------------
# Collection constants
# ---------------------------------------------------------------------------

COLLECTION_MEMORY = "alice_memory"
"""Memory entries (Phase 9)."""

COLLECTION_NOTES = "alice_notes"
"""Note embeddings (Phase 13)."""

COLLECTION_TOOLS = "alice_tools"
"""Tool definition embeddings (Tool RAG)."""

PROJECT_NS = uuid.UUID("a1c3e5f7-0000-4000-8000-000000000000")
"""Namespace UUID for deterministic tool IDs via uuid5."""

_log = logger.bind(component="QdrantService")


class QdrantService:
    """Async-first Qdrant vector store wrapper.

    Supports embedded mode (in-process, no Docker) and server mode
    (connects to a running Qdrant instance).

    Args:
        config: Qdrant configuration section.
    """

    def __init__(self, config: QdrantConfig) -> None:
        self._config = config
        self._client: AsyncQdrantClient | None = None
        self._in_memory: bool = False

    @property
    def in_memory(self) -> bool:
        """Return True if running in the volatile in-memory fallback mode.

        Set when :meth:`initialize` cannot acquire the embedded data
        directory after the configured retries and falls back to
        ``AsyncQdrantClient(":memory:")``.  Callers (status endpoints,
        UI badges) should surface this so the user knows persisted
        writes are not durable.
        """
        return self._in_memory

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the AsyncQdrantClient based on configured mode."""
        if self._config.mode == "server":
            self._client = AsyncQdrantClient(
                host=self._config.host,
                port=self._config.port,
            )
            _log.info(
                "Qdrant client connected (server mode: {}:{})",
                self._config.host, self._config.port,
            )
        else:
            # Retry loop — during hot-reload the previous process may still
            # hold the RocksDB lock for a moment after its file descriptors
            # are closed by the OS.  Five quick retries usually suffice.
            _RETRIES = 5
            _DELAY = 0.6  # seconds between attempts
            last_exc: Exception | None = None
            for attempt in range(1, _RETRIES + 1):
                try:
                    self._client = AsyncQdrantClient(path=self._config.path)
                    _log.info(
                        "Qdrant client started (embedded mode: {})",
                        self._config.path,
                    )
                    return
                except Exception as exc:
                    if "already accessed" not in str(exc):
                        raise
                    last_exc = exc
                    _log.debug(
                        "Qdrant lock held — retry {}/{} in {:.1f}s …",
                        attempt, _RETRIES, _DELAY,
                    )
                    await asyncio.sleep(_DELAY)

            # All retries exhausted — fall back gracefully.
            _log.warning(
                "Qdrant data dir still locked after {} retries — "
                "falling back to in-memory mode. "
                "Data will not persist until the lock is released. "
                "Cause: {}",
                _RETRIES, last_exc,
            )
            self._client = AsyncQdrantClient(":memory:")
            self._in_memory = True

    async def close(self) -> None:
        """Close the Qdrant client connection."""
        if self._client:
            await self._client.close()
            self._client = None
            _log.info("Qdrant client closed")

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    async def ensure_collection(
        self,
        name: str,
        vector_size: int,
        distance: models.Distance = models.Distance.COSINE,
    ) -> None:
        """Create a collection if it doesn't exist, or recreate on dim mismatch.

        Args:
            name: Collection name.
            vector_size: Expected vector dimensionality.
            distance: Distance metric (default COSINE).
        """
        assert self._client is not None, "QdrantService not initialized"

        exists = await self._client.collection_exists(name)
        if exists:
            info = await self._client.get_collection(name)
            current_size = info.config.params.vectors.size  # type: ignore[union-attr]
            if current_size != vector_size:
                _log.warning(
                    "Collection '{}' dim mismatch: {} vs {} — recreating",
                    name, current_size, vector_size,
                )
                await self._client.delete_collection(name)
                exists = False

        if not exists:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=distance,
                ),
            )
            _log.info(
                "Collection '{}' created (dim={}, distance={})",
                name, vector_size, distance.value,
            )

    async def get_collection_dim(self, name: str) -> int:
        """Return the vector size of an existing collection, or 0 if absent."""
        assert self._client is not None, "QdrantService not initialized"
        try:
            exists = await self._client.collection_exists(name)
            if not exists:
                return 0
            info = await self._client.get_collection(name)
            return info.config.params.vectors.size  # type: ignore[union-attr]
        except Exception:
            return 0

    async def upsert(
        self,
        collection: str,
        points: list[models.PointStruct],
    ) -> None:
        """Insert or update points in a collection.

        Args:
            collection: Target collection name.
            points: List of PointStruct with id, vector, and payload.
        """
        assert self._client is not None, "QdrantService not initialized"
        await self._client.upsert(
            collection_name=collection,
            points=points,
        )

    async def set_payload(
        self,
        collection: str,
        *,
        payload: dict,
        ids: list[str] | None = None,
        query_filter: models.Filter | None = None,
    ) -> None:
        """Patch the payload of points (selected by IDs or filter).

        Only the keys present in *payload* are overwritten — other
        payload fields are preserved.  Exactly one of *ids* or
        *query_filter* must be provided; if both are ``None`` the call
        is a no-op so callers are free to pass an empty ID list without
        accidentally rewriting the whole collection.

        Args:
            collection: Target collection name.
            payload: Partial payload to merge into matching points.
            ids: List of point IDs to update.
            query_filter: Alternative filter-based selector.
        """
        assert self._client is not None, "QdrantService not initialized"
        if ids is None and query_filter is None:
            return
        if ids is not None and not ids:
            return
        kwargs: dict = {"collection_name": collection, "payload": payload}
        if ids is not None:
            kwargs["points"] = ids
        else:
            kwargs["points_selector"] = models.FilterSelector(
                filter=query_filter,
            )
        await self._client.set_payload(**kwargs)

    async def search(
        self,
        collection: str,
        vector: list[float],
        k: int = 5,
        query_filter: models.Filter | None = None,
    ) -> list[models.ScoredPoint]:
        """Search for nearest vectors in a collection.

        Args:
            collection: Target collection name.
            vector: Query vector.
            k: Number of results to return.
            query_filter: Optional Qdrant filter.

        Returns:
            List of scored points ordered by similarity.
        """
        assert self._client is not None, "QdrantService not initialized"
        results = await self._client.query_points(
            collection_name=collection,
            query=vector,
            limit=k,
            query_filter=query_filter,
            with_payload=True,
        )
        return results.points

    async def delete(
        self,
        collection: str,
        *,
        ids: list[str] | None = None,
        query_filter: models.Filter | None = None,
    ) -> None:
        """Delete points by IDs or filter.

        Args:
            collection: Target collection name.
            ids: List of point IDs to delete.
            query_filter: Alternative filter-based deletion.
        """
        assert self._client is not None, "QdrantService not initialized"
        if ids is not None:
            await self._client.delete(
                collection_name=collection,
                points_selector=models.PointIdsList(points=ids),
            )
        elif query_filter is not None:
            await self._client.delete(
                collection_name=collection,
                points_selector=models.FilterSelector(
                    filter=query_filter,
                ),
            )

    async def scroll(
        self,
        collection: str,
        query_filter: models.Filter | None = None,
        limit: int = 50,
        offset: str | int | None = None,
    ) -> tuple[list[models.Record], str | int | None]:
        """Scroll through points in a collection.

        Args:
            collection: Target collection name.
            query_filter: Optional filter.
            limit: Max points per page.
            offset: Pagination offset from previous scroll.

        Returns:
            Tuple of (records, next_offset). next_offset is None when done.
        """
        assert self._client is not None, "QdrantService not initialized"
        records, next_offset = await self._client.scroll(
            collection_name=collection,
            scroll_filter=query_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
        )
        return records, next_offset

    async def count(
        self,
        collection: str,
        query_filter: models.Filter | None = None,
    ) -> int:
        """Count points in a collection, optionally filtered.

        Args:
            collection: Target collection name.
            query_filter: Optional filter.

        Returns:
            Number of matching points.
        """
        assert self._client is not None, "QdrantService not initialized"
        if query_filter:
            result = await self._client.count(
                collection_name=collection,
                count_filter=query_filter,
                exact=True,
            )
        else:
            result = await self._client.count(
                collection_name=collection,
                exact=True,
            )
        return result.count
