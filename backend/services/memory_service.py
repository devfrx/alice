"""AL\\CE — Persistent semantic memory service (Qdrant backend).

Stores, retrieves, and manages semantic memories using Qdrant vector search
with automatic expiry cleanup for session-scoped entries.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from qdrant_client import models

from backend.core.config import MemoryConfig
from backend.core.protocols import EmbeddingClientProtocol, QdrantServiceProtocol
from backend.services.qdrant_service import COLLECTION_MEMORY


# ---------------------------------------------------------------------------
# Memory entry dataclass (lightweight, no SQLModel table mapping needed
# because memory lives in its own DB)
# ---------------------------------------------------------------------------

class MemoryEntry:
    """In-memory representation of a row in ``memory_entries``."""

    __slots__ = (
        "id", "content", "scope", "category", "source",
        "created_at", "expires_at", "conversation_id", "embedding_model",
    )

    def __init__(
        self,
        *,
        id: uuid.UUID,
        content: str,
        scope: str,
        category: str | None,
        source: str,
        created_at: datetime,
        expires_at: datetime | None,
        conversation_id: uuid.UUID | None,
        embedding_model: str,
    ) -> None:
        self.id = id
        self.content = content
        self.scope = scope
        self.category = category
        self.source = source
        self.created_at = created_at
        self.expires_at = expires_at
        self.conversation_id = conversation_id
        self.embedding_model = embedding_model

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "content": self.content,
            "scope": self.scope,
            "category": self.category,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "conversation_id": str(self.conversation_id) if self.conversation_id else None,
            "embedding_model": self.embedding_model,
        }


# ---------------------------------------------------------------------------
# MemoryService
# ---------------------------------------------------------------------------

class MemoryService:
    """Semantic memory service backed by Qdrant.

    Args:
        config: Memory configuration section.
        qdrant_service: Shared Qdrant vector store.
        embedding_client: Shared embedding client.
    """

    def __init__(
        self,
        config: MemoryConfig,
        qdrant_service: QdrantServiceProtocol,
        embedding_client: EmbeddingClientProtocol,
        *,
        embedding_model: str = "",
    ) -> None:
        self._config = config
        self._qdrant = qdrant_service
        self._embedder = embedding_client
        self._embedding_model = embedding_model
        self._cleanup_task: asyncio.Task[None] | None = None
        self._log = logger.bind(component="MemoryService")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Ensure collection exists and start cleanup loop."""
        await self._qdrant.ensure_collection(
            COLLECTION_MEMORY,
            self._embedder.dimensions,
        )
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._log.info(
            "Memory service initialized (collection={}, dim={})",
            COLLECTION_MEMORY, self._embedder.dimensions,
        )

    async def close(self) -> None:
        """Cancel cleanup task. Does NOT close qdrant or embedding client."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self._cleanup_task = None
        self._log.info("Memory service closed")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def add(
        self,
        content: str,
        *,
        scope: str = "long_term",
        category: str | None = None,
        source: str = "llm",
        conversation_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryEntry:
        """Embed content and persist it.

        Args:
            content: The text to memorise.
            scope: ``long_term`` | ``session`` | ``user_fact``.
            category: Optional category tag.
            source: Origin — ``llm``, ``user``, ``plugin``, etc.
            conversation_id: Link to a conversation, if applicable.
            expires_at: Optional expiry (auto-cleaned later).

        Returns:
            The created ``MemoryEntry``.
        """
        entry_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        vector = await self._embedder.encode(content)

        point = models.PointStruct(
            id=str(entry_id),
            vector=vector,
            payload={
                "content": content,
                "scope": scope,
                "category": category or "",
                "source": source,
                "conversation_id": conversation_id or "",
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at else "",
                "embedding_model": self._embedding_model,
            },
        )
        await self._qdrant.upsert(COLLECTION_MEMORY, [point])

        self._log.debug(
            "Memory added: id={} scope={} category={}",
            entry_id, scope, category,
        )
        return MemoryEntry(
            id=entry_id,
            content=content,
            scope=scope,
            category=category,
            source=source,
            created_at=now,
            expires_at=expires_at,
            conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
            embedding_model=self._embedding_model,
        )

    async def search(
        self,
        query: str,
        *,
        k: int = 5,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search over stored memories.

        Args:
            query: Natural-language query text.
            k: Number of results (defaults to 5).
            filter: Optional dict with ``scope`` and/or ``category`` keys.

        Returns:
            List of dicts with ``entry`` (MemoryEntry) and ``score`` (float).
        """
        vector = await self._embedder.encode(query)

        # Build Qdrant filter conditions
        conditions: list[models.Condition] = []
        if filter:
            if "scope" in filter:
                conditions.append(
                    models.FieldCondition(
                        key="scope",
                        match=models.MatchValue(value=filter["scope"]),
                    )
                )
            if "category" in filter:
                conditions.append(
                    models.FieldCondition(
                        key="category",
                        match=models.MatchValue(value=filter["category"]),
                    )
                )

        query_filter = models.Filter(must=conditions) if conditions else None

        # Over-fetch to allow post-filtering of expired entries
        hits = await self._qdrant.search(
            COLLECTION_MEMORY, vector, k=k * 2, query_filter=query_filter,
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        results: list[dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            expires = payload.get("expires_at", "")
            if expires and expires < now_iso:
                continue
            if hit.score < self._config.similarity_threshold:
                continue
            entry = self._payload_to_entry(hit.id, payload)
            results.append({"entry": entry, "score": round(hit.score, 4)})
            if len(results) >= k:
                break

        return results

    async def delete(self, memory_id: str) -> bool:
        """Remove a memory by ID.

        Returns:
            ``True`` if deletion was attempted.
        """
        await self._qdrant.delete(COLLECTION_MEMORY, ids=[memory_id])
        self._log.debug("Memory deleted: {}", memory_id)
        return True

    async def delete_by_scope(self, scope: str) -> int:
        """Delete all memories with the given scope.

        Args:
            scope: Scope to purge (e.g. ``session``).

        Returns:
            Number of deleted entries.
        """
        count_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="scope",
                    match=models.MatchValue(value=scope),
                )
            ]
        )
        count = await self._qdrant.count(COLLECTION_MEMORY, count_filter)
        if count > 0:
            await self._qdrant.delete(
                COLLECTION_MEMORY, query_filter=count_filter,
            )
        self._log.info("Deleted {} memories with scope={}", count, scope)
        return count

    async def delete_all(self) -> int:
        """Delete every memory entry.

        Returns:
            Number of deleted entries.
        """
        count = await self._qdrant.count(COLLECTION_MEMORY)
        if count > 0:
            offset = None
            while True:
                records, next_offset = await self._qdrant.scroll(
                    COLLECTION_MEMORY, limit=100, offset=offset,
                )
                if not records:
                    break
                ids = [str(r.id) for r in records]
                await self._qdrant.delete(COLLECTION_MEMORY, ids=ids)
                if next_offset is None:
                    break
                offset = next_offset
        self._log.info("Deleted all {} memories", count)
        return count

    async def list(
        self,
        *,
        filter: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryEntry], int]:
        """List memory entries with optional filters.

        Args:
            filter: Optional dict with ``scope``, ``category`` keys.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            Tuple of (entries, total_count).
        """
        scope = (filter or {}).get("scope")
        category = (filter or {}).get("category")

        conditions: list[models.Condition] = []
        if scope:
            conditions.append(
                models.FieldCondition(
                    key="scope",
                    match=models.MatchValue(value=scope),
                )
            )
        if category:
            conditions.append(
                models.FieldCondition(
                    key="category",
                    match=models.MatchValue(value=category),
                )
            )

        query_filter = models.Filter(must=conditions) if conditions else None

        total = await self._qdrant.count(COLLECTION_MEMORY, query_filter)

        # Qdrant scroll uses cursor-based pagination (point IDs), not
        # positional offsets.  Skip the first `offset` records by
        # scrolling past them before fetching the requested page.
        cursor: str | int | None = None
        if offset > 0:
            skipped = 0
            while skipped < offset:
                batch = min(100, offset - skipped)
                skip_records, next_cursor = await self._qdrant.scroll(
                    COLLECTION_MEMORY,
                    query_filter=query_filter,
                    limit=batch,
                    offset=cursor,
                )
                skipped += len(skip_records)
                if not skip_records or next_cursor is None:
                    return [], total
                cursor = next_cursor

        records, _ = await self._qdrant.scroll(
            COLLECTION_MEMORY,
            query_filter=query_filter,
            limit=limit,
            offset=cursor,
        )

        entries = [
            self._payload_to_entry(r.id, r.payload or {})
            for r in records
        ]
        return entries, total

    async def stats(self) -> dict[str, Any]:
        """Return aggregate statistics about stored memories.

        Returns:
            Dict with ``total``, ``by_scope``, ``by_category``,
            and ``db_size_bytes``.
        """
        total = await self._qdrant.count(COLLECTION_MEMORY)

        by_scope: dict[str, int] = {}
        for scope_name in ("long_term", "session", "user_fact"):
            scope_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="scope",
                        match=models.MatchValue(value=scope_name),
                    )
                ]
            )
            by_scope[scope_name] = await self._qdrant.count(
                COLLECTION_MEMORY, scope_filter,
            )

        # Aggregate categories by scrolling all records
        by_category: dict[str, int] = {}
        offset = None
        while True:
            records, next_offset = await self._qdrant.scroll(
                COLLECTION_MEMORY, limit=100, offset=offset,
            )
            if not records:
                break
            for r in records:
                cat = (r.payload or {}).get("category", "") or ""
                if cat:
                    by_category[cat] = by_category.get(cat, 0) + 1
            if next_offset is None:
                break
            offset = next_offset

        return {
            "total": total,
            "by_scope": by_scope,
            "by_category": by_category,
            "db_size_bytes": 0,  # Not applicable for Qdrant
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _payload_to_entry(
        point_id: str | int, payload: dict[str, Any],
    ) -> MemoryEntry:
        """Convert a Qdrant payload to a MemoryEntry."""
        created = payload.get("created_at", "")
        expires = payload.get("expires_at", "")
        cid = payload.get("conversation_id", "")
        return MemoryEntry(
            id=uuid.UUID(str(point_id)),
            content=payload.get("content", ""),
            scope=payload.get("scope", "long_term"),
            category=payload.get("category", "") or None,
            source=payload.get("source", "user"),
            created_at=(
                datetime.fromisoformat(created) if created
                else datetime.now(timezone.utc)
            ),
            expires_at=datetime.fromisoformat(expires) if expires else None,
            conversation_id=uuid.UUID(cid) if cid else None,
            embedding_model=payload.get("embedding_model", ""),
        )

    # ------------------------------------------------------------------
    # Background cleanup
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """Remove expired and stale entries: once at start, then every 6 h."""
        interval = 6 * 3600
        try:
            await self._cleanup_expired()
        except Exception:
            self._log.opt(exception=True).warning(
                "Initial memory cleanup failed"
            )
        while True:
            try:
                await asyncio.sleep(interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                return
            except Exception:
                self._log.opt(exception=True).warning(
                    "Memory cleanup cycle failed"
                )

    async def _cleanup_expired(self) -> int:
        """Delete memories past their expiry time.

        Returns:
            Number of expired entries removed.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        removed = 0
        offset = None

        while True:
            records, next_offset = await self._qdrant.scroll(
                COLLECTION_MEMORY, limit=100, offset=offset,
            )
            if not records:
                break

            expired_ids: list[str] = []
            for r in records:
                expires = (r.payload or {}).get("expires_at", "")
                if expires and expires < now_iso:
                    expired_ids.append(str(r.id))

            if expired_ids:
                await self._qdrant.delete(COLLECTION_MEMORY, ids=expired_ids)
                removed += len(expired_ids)

            if next_offset is None:
                break
            offset = next_offset

        if removed:
            self._log.info("Cleaned up {} expired memories", removed)
        return removed