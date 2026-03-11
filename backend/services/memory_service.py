"""O.M.N.I.A. — Persistent semantic memory service.

CRUD + vector search via ``sqlite-vec`` on a dedicated SQLite DB
(``data/memory.db``).  All I/O is async via ``aiosqlite``.
"""

from __future__ import annotations

import asyncio
import importlib.resources
import struct
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from backend.core.config import PROJECT_ROOT, MemoryConfig
from backend.services.embedding_client import EmbeddingClient


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MemoryDimensionMismatchError(Exception):
    """Raised when embedding dimension doesn't match the stored vectors."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_f32(vec: list[float]) -> bytes:
    """Pack a float list into a little-endian f32 blob for sqlite-vec."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _resolve_vec_extension_path() -> str:
    """Resolve the sqlite-vec loadable extension DLL/so path.

    Uses ``importlib.resources`` to find the shared library bundled
    with the ``sqlite_vec`` Python package.
    """
    pkg = importlib.resources.files("sqlite_vec")
    # The package ships a single shared lib (vec0.dll / vec0.so / vec0.dylib)
    for item in pkg.iterdir():
        name = item.name
        if name.startswith("vec0") and (
            name.endswith(".dll")
            or name.endswith(".so")
            or name.endswith(".dylib")
        ):
            return str(item)
    # Fallback: let sqlite try the bare module name
    return "vec0"


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
# SQL constants
# ---------------------------------------------------------------------------

_CREATE_ENTRIES_SQL = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id              TEXT PRIMARY KEY,
    content         TEXT    NOT NULL,
    scope           TEXT    NOT NULL DEFAULT 'long_term',
    category        TEXT,
    source          TEXT    NOT NULL DEFAULT 'llm',
    created_at      TEXT    NOT NULL,
    expires_at      TEXT,
    conversation_id TEXT,
    embedding_model TEXT    NOT NULL
);
"""

_CREATE_VECTORS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors
USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[{dim}] distance_metric=cosine);
"""




# ---------------------------------------------------------------------------
# MemoryService
# ---------------------------------------------------------------------------

class MemoryService:
    """Persistent semantic memory: embed, store, and search via sqlite-vec.

    Args:
        config: ``MemoryConfig`` sub-section from OMNIA config.
        llm_base_url: Base URL of the LLM / embedding API server.
    """

    def __init__(self, config: MemoryConfig, llm_base_url: str) -> None:
        self._config = config
        self._llm_base_url = llm_base_url
        self._db: aiosqlite.Connection | None = None
        self._embed: EmbeddingClient | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open DB, load sqlite-vec, create tables, start cleanup loop.

        Idempotent — safe to call on hot-reload.
        """
        if self._db is not None:
            logger.debug("MemoryService already initialised, skipping")
            return

        self._closed = False

        db_path = Path(self._config.db_path)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Opening memory DB at {}", db_path)
        self._db = await aiosqlite.connect(str(db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")

        # Load sqlite-vec extension
        vec_path = _resolve_vec_extension_path()
        await self._db.enable_load_extension(True)
        await self._db.load_extension(vec_path)
        await self._db.enable_load_extension(False)
        logger.info("Loaded sqlite-vec extension from {}", vec_path)

        # Create entries table (idempotent).
        await self._db.execute(_CREATE_ENTRIES_SQL)
        await self._db.commit()

        # Migrate vectors table if definition is stale (wrong dim or no cosine).
        needs_reembed = await self._maybe_migrate_vectors()

        await self._db.execute(
            _CREATE_VECTORS_SQL.format(dim=self._config.embedding_dim)
        )
        await self._db.commit()

        # Embedding client
        self._embed = EmbeddingClient(
            base_url=self._llm_base_url,
            model=self._config.embedding_model,
            dimensions=self._config.embedding_dim,
            fallback_enabled=self._config.embedding_fallback,
        )

        # Re-embed entries that lost their vectors during migration.
        if needs_reembed:
            await self._reembed_all()

        logger.info(
            "MemoryService ready (model={}, dim={})",
            self._config.embedding_model,
            self._config.embedding_dim,
        )

        # Background cleanup
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def close(self) -> None:
        """Shut down cleanup task, embedding client, and DB connection."""
        if self._closed:
            return
        self._closed = True

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._embed:
            await self._embed.close()
            self._embed = None

        if self._db:
            await self._db.close()
            self._db = None

        logger.info("MemoryService closed")

    # ------------------------------------------------------------------
    # Schema migration
    # ------------------------------------------------------------------

    async def _maybe_migrate_vectors(self) -> bool:
        """Drop memory_vectors if its DDL doesn't match the current config.

        Reads the actual ``CREATE VIRTUAL TABLE`` statement from
        ``sqlite_master`` and checks for the correct embedding dimension
        and ``distance_metric=cosine``.  Dropping the table here is safe:
        ``initialize()`` will immediately recreate it and ``_reembed_all()``
        will repopulate it from ``memory_entries``.

        Returns:
            ``True`` if the table was dropped and must be recreated/re-embedded.
        """
        assert self._db is not None

        cursor = await self._db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'memory_vectors'"
        )
        row = await cursor.fetchone()
        if row is None:
            # Table doesn't exist yet — will be created fresh, no migration needed.
            return False

        current_ddl: str = (row["sql"] or "").lower()
        want_dim = f"float[{self._config.embedding_dim}]"

        dim_ok = want_dim in current_ddl
        cosine_ok = "distance_metric=cosine" in current_ddl

        if dim_ok and cosine_ok:
            return False

        reasons: list[str] = []
        if not dim_ok:
            reasons.append(f"dim mismatch (want {self._config.embedding_dim})")
        if not cosine_ok:
            reasons.append("cosine metric missing")
        logger.info("Rebuilding memory_vectors: {}", ", ".join(reasons))

        await self._db.execute("DROP TABLE IF EXISTS memory_vectors")
        await self._db.commit()
        return True

    async def _reembed_all(self) -> None:
        """Re-embed every entry in ``memory_entries`` into the vectors table.

        Called after a migration that dropped the old vectors.
        """
        assert self._db is not None and self._embed is not None

        cursor = await self._db.execute(
            "SELECT id, content FROM memory_entries"
        )
        entries = await cursor.fetchall()
        if not entries:
            return

        logger.info("Re-embedding {} memory entries after migration", len(entries))
        for entry in entries:
            try:
                vector = await self._embed.encode(entry["content"])
                await self._db.execute(
                    "INSERT INTO memory_vectors (id, embedding) VALUES (?, ?)",
                    (entry["id"], _serialize_f32(vector)),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to re-embed memory {}: {}", entry["id"], exc
                )
        await self._db.commit()
        logger.info("Re-embedding complete")

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
        if not self._db or not self._embed:
            raise RuntimeError("MemoryService not initialised")

        entry_id = uuid.uuid4()
        now = _utcnow()
        vector = await self._embed.encode(content)

        if len(vector) != self._config.embedding_dim:
            raise MemoryDimensionMismatchError(
                f"Expected {self._config.embedding_dim} dims, "
                f"got {len(vector)}"
            )

        await self._db.execute(
            """
            INSERT INTO memory_entries
                (id, content, scope, category, source,
                 created_at, expires_at, conversation_id, embedding_model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(entry_id),
                content,
                scope,
                category,
                source,
                now.isoformat(),
                expires_at.isoformat() if expires_at else None,
                conversation_id or None,
                self._config.embedding_model,
            ),
        )
        await self._db.execute(
            "INSERT INTO memory_vectors (id, embedding) VALUES (?, ?)",
            (str(entry_id), _serialize_f32(vector)),
        )
        await self._db.commit()

        logger.debug("Memory added id={} scope={}", entry_id, scope)
        return MemoryEntry(
            id=entry_id,
            content=content,
            scope=scope,
            category=category,
            source=source,
            created_at=now,
            expires_at=expires_at,
            conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
            embedding_model=self._config.embedding_model,
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
        if not self._db or not self._embed:
            raise RuntimeError("MemoryService not initialised")

        scope = (filter or {}).get("scope")
        category = (filter or {}).get("category")

        query_vec = await self._embed.encode(query)

        if len(query_vec) != self._config.embedding_dim:
            raise MemoryDimensionMismatchError(
                f"Expected {self._config.embedding_dim} dims, "
                f"got {len(query_vec)}"
            )

        # sqlite-vec cosine: distance ∈ [0, 2]; similarity = 1 - distance
        cursor = await self._db.execute(
            """
            SELECT v.id, v.distance
            FROM memory_vectors v
            WHERE v.embedding MATCH ?
            ORDER BY v.distance
            LIMIT ?
            """,
            (_serialize_f32(query_vec), k * 3),
        )
        rows = await cursor.fetchall()

        now_iso = _utcnow().isoformat()
        results: list[dict[str, Any]] = []
        for row in rows:
            similarity = 1.0 - row["distance"]
            if similarity < self._config.similarity_threshold:
                continue

            entry_cur = await self._db.execute(
                "SELECT * FROM memory_entries WHERE id = ?",
                (row["id"],),
            )
            entry_row = await entry_cur.fetchone()
            if entry_row is None:
                continue

            # Expired?
            exp = entry_row["expires_at"]
            if exp and exp < now_iso:
                continue

            # Scope / category filter
            if scope and entry_row["scope"] != scope:
                continue
            if category and entry_row["category"] != category:
                continue

            results.append({
                "entry": _row_to_entry(entry_row),
                "score": round(similarity, 4),
            })
            if len(results) >= k:
                break

        return results

    async def delete(self, memory_id: str) -> bool:
        """Remove a memory by ID.

        Returns:
            ``True`` if a row was deleted, ``False`` if not found.
        """
        if not self._db:
            raise RuntimeError("MemoryService not initialised")
        mid = str(memory_id)

        cur = await self._db.execute(
            "DELETE FROM memory_entries WHERE id = ?", (mid,)
        )
        await self._db.execute(
            "DELETE FROM memory_vectors WHERE id = ?", (mid,)
        )
        await self._db.commit()
        deleted = cur.rowcount > 0
        if deleted:
            logger.debug("Memory deleted id={}", memory_id)
        return deleted

    async def delete_by_scope(self, scope: str) -> int:
        """Delete all memories with the given scope.

        Args:
            scope: Scope to purge (e.g. ``session``).

        Returns:
            Number of deleted entries.
        """
        if not self._db:
            raise RuntimeError("MemoryService not initialised")

        cur = await self._db.execute(
            "DELETE FROM memory_entries WHERE scope = ?", (scope,)
        )
        await self._db.execute(
            "DELETE FROM memory_vectors WHERE id NOT IN "
            "(SELECT id FROM memory_entries)"
        )
        await self._db.commit()
        count = cur.rowcount
        if count:
            logger.info("Deleted {} memories with scope={}", count, scope)
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
            filter: Optional dict with ``scope``, ``category``,
                ``created_after`` keys.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            Tuple of (entries, total_count).
        """
        if not self._db:
            raise RuntimeError("MemoryService not initialised")

        scope = (filter or {}).get("scope")
        category = (filter or {}).get("category")
        created_after = (filter or {}).get("created_after")

        clauses: list[str] = []
        params: list[Any] = []

        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if category:
            if category == "uncategorised":
                clauses.append("category IS NULL")
            else:
                clauses.append("category = ?")
                params.append(category)
        if created_after:
            clauses.append("created_at > ?")
            params.append(created_after.isoformat())

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        # Total count for pagination
        count_cur = await self._db.execute(
            f"SELECT COUNT(*) AS cnt FROM memory_entries{where}",
            params[:],
        )
        total = (await count_cur.fetchone())["cnt"]

        params.extend([limit, offset])
        cursor = await self._db.execute(
            f"SELECT * FROM memory_entries{where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cursor.fetchall()
        return [_row_to_entry(r) for r in rows], total

    async def stats(self) -> dict[str, Any]:
        """Return aggregate statistics about stored memories.

        Returns:
            Dict with ``total``, ``by_scope``, ``by_category``, and
            ``db_size_bytes``.
        """
        if not self._db:
            raise RuntimeError("MemoryService not initialised")

        cur = await self._db.execute(
            "SELECT COUNT(*) AS cnt FROM memory_entries"
        )
        total = (await cur.fetchone())["cnt"]

        cur = await self._db.execute(
            "SELECT scope, COUNT(*) AS cnt "
            "FROM memory_entries GROUP BY scope"
        )
        by_scope = {r["scope"]: r["cnt"] for r in await cur.fetchall()}

        cur = await self._db.execute(
            "SELECT category, COUNT(*) AS cnt "
            "FROM memory_entries GROUP BY category"
        )
        by_category = {
            (r["category"] or "uncategorised"): r["cnt"]
            for r in await cur.fetchall()
        }

        db_path = Path(self._config.db_path)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        db_size = db_path.stat().st_size if db_path.exists() else 0

        return {
            "total": total,
            "by_scope": by_scope,
            "by_category": by_category,
            "db_size_bytes": db_size,
        }

    # ------------------------------------------------------------------
    # Background cleanup
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """Periodically remove expired and stale entries (every 6 h)."""
        interval = 6 * 3600  # seconds
        while True:
            try:
                await asyncio.sleep(interval)
                await self._run_cleanup()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.opt(exception=True).warning(
                    "Memory cleanup cycle failed"
                )

    async def _run_cleanup(self) -> None:
        """Delete expired entries and optionally old unused entries."""
        if not self._db:
            return
        now_iso = _utcnow().isoformat()

        # Expired entries
        cur = await self._db.execute(
            "DELETE FROM memory_entries "
            "WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now_iso,),
        )
        expired_count = cur.rowcount

        # Orphan vectors for deleted entries
        await self._db.execute(
            "DELETE FROM memory_vectors WHERE id NOT IN "
            "(SELECT id FROM memory_entries)"
        )

        # Auto-cleanup old entries
        stale_count = 0
        if self._config.auto_cleanup_days > 0:
            cutoff = (
                _utcnow() - timedelta(days=self._config.auto_cleanup_days)
            ).isoformat()
            cur = await self._db.execute(
                "DELETE FROM memory_entries WHERE created_at < ?",
                (cutoff,),
            )
            stale_count = cur.rowcount
            # Clean orphan vectors again
            await self._db.execute(
                "DELETE FROM memory_vectors WHERE id NOT IN "
                "(SELECT id FROM memory_entries)"
            )

        await self._db.commit()
        if expired_count or stale_count:
            logger.info(
                "Memory cleanup: expired={}, stale={}",
                expired_count,
                stale_count,
            )


# ---------------------------------------------------------------------------
# Row → MemoryEntry helper
# ---------------------------------------------------------------------------

def _row_to_entry(row: aiosqlite.Row) -> MemoryEntry:
    """Convert an aiosqlite Row from memory_entries to a MemoryEntry."""
    exp = row["expires_at"]
    cid = row["conversation_id"]
    return MemoryEntry(
        id=uuid.UUID(row["id"]),
        content=row["content"],
        scope=row["scope"],
        category=row["category"],
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
        expires_at=datetime.fromisoformat(exp) if exp else None,
        conversation_id=uuid.UUID(cid) if cid else None,
        embedding_model=row["embedding_model"],
    )
