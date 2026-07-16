"""AL\\CE — Qdrant vector store service.

Pure vector-store wrapper: stores, retrieves, and deletes vector points.
Does NOT handle embedding — callers provide pre-computed vectors.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from loguru import logger
from qdrant_client import models
from qdrant_client.async_qdrant_client import AsyncQdrantClient

from backend.core.config import QdrantConfig

# Re-export: kept for pre-Fase 5 import sites (`from ...qdrant_service import ...`).
from backend.core.vector_collections import COLLECTION_TOOLS, PROJECT_NS  # noqa: F401

# ---------------------------------------------------------------------------
# Collection constants
# ---------------------------------------------------------------------------

COLLECTION_MEMORY = "alice_memory"
"""Memory entries (Phase 9)."""

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
        self._fallback_reason: str | None = None

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

    @property
    def fallback_reason(self) -> str | None:
        """Human-readable cause of the in-memory fallback, or ``None``.

        Set alongside :attr:`in_memory` so status endpoints and the RAG
        readiness verdict can tell the user *why* the store is volatile
        instead of a generic "in-memory fallback".
        """
        return self._fallback_reason

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the AsyncQdrantClient based on configured mode."""
        self._fallback_reason = None
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
            max_retries = 5
            retry_delay = 0.6  # seconds between attempts
            last_exc: Exception | None = None
            for attempt in range(1, max_retries + 1):
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
                        attempt, max_retries, retry_delay,
                    )
                    await asyncio.sleep(retry_delay)

            # All retries exhausted — fall back gracefully.
            _log.warning(
                "Qdrant data dir still locked after {} retries — "
                "falling back to in-memory mode. "
                "Data will not persist until the lock is released. "
                "Cause: {}",
                max_retries, last_exc,
            )
            self._client = AsyncQdrantClient(":memory:")
            self._in_memory = True
            self._fallback_reason = (
                "Vector store data directory is locked by another process — "
                "another AL\\CE backend instance is likely running. Writes are "
                "not persisted until it is closed."
            )

    async def close(self) -> None:
        """Close the Qdrant client connection."""
        if self._client:
            await self._client.close()
            self._client = None
            _log.info("Qdrant client closed")

    def try_clear_stale_lock(self) -> bool:
        """Best-effort remove an orphan embedded-mode lock file.

        Returns True if at least one lock file was removed. Only touches the
        configured embedded path and never raises. A lock held by a live process
        cannot be removed on Windows (the unlink fails) — in that case this
        returns False and the caller keeps the in-memory fallback.

        Returns:
            True if at least one ``.lock`` file was removed.
        """
        if self._config.mode != "embedded":
            return False
        removed = False
        root = Path(self._config.path)
        for lock in root.rglob(".lock"):
            try:
                lock.unlink()
                removed = True
            except OSError:
                pass
        return removed

    async def reinitialize(self) -> None:
        """Close and re-run :meth:`initialize` (used after a stale-lock clear)."""
        await self.close()
        self._in_memory = False
        await self.initialize()

    def clear_embedded_data(self) -> bool:
        """Delete the embedded vector-store directory (destructive).

        Backs the user-triggered "repair" action: when the on-disk data was
        written by an incompatible ``qdrant-client`` version (so the client
        can no longer open it), removing the directory lets a fresh store be
        created on the next :meth:`initialize`.  Only touches the configured
        embedded path and never raises.

        Returns:
            True if the directory is gone afterwards (removed or already
            absent); False in server mode or if removal failed.
        """
        if self._config.mode != "embedded":
            return False
        root = Path(self._config.path)
        try:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
            return not root.exists()
        except OSError:
            return False

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

    async def get_collection_dim(self, name: str) -> int | None:
        """Return the vector dimensionality of *name*, or None if it is missing."""
        assert self._client is not None, "QdrantService not initialized"
        if not await self._client.collection_exists(name):
            return None
        info = await self._client.get_collection(name)
        return int(info.config.params.vectors.size)  # type: ignore[union-attr]

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
            Number of matching points (0 if the collection is missing).
        """
        assert self._client is not None, "QdrantService not initialized"
        if not await self._client.collection_exists(collection):
            return 0
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
