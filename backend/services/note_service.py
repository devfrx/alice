"""O.M.N.I.A. — Obsidian-like note vault service.

CRUD + FTS5 full-text search + optional vector search via ``sqlite-vec``
on a dedicated SQLite DB (``data/notes.db``).  All I/O is async via
``aiosqlite``.
"""

from __future__ import annotations

import importlib.resources
import re
import struct
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
from loguru import logger

from backend.core.config import PROJECT_ROOT, NotesConfig
from backend.services.embedding_client import EmbeddingClient

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


# ----------------------------------------------------------------------- #
# Helpers
# ----------------------------------------------------------------------- #

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_f32(vec: list[float]) -> bytes:
    """Pack a float list into a little-endian f32 blob for sqlite-vec."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _resolve_vec_extension_path() -> str:
    """Resolve the sqlite-vec loadable extension DLL/so path."""
    pkg = importlib.resources.files("sqlite_vec")
    for item in pkg.iterdir():
        name = item.name
        if name.startswith("vec0") and (
            name.endswith(".dll")
            or name.endswith(".so")
            or name.endswith(".dylib")
        ):
            return str(item)
    logger.warning("sqlite-vec extension not found in package, falling back to bare 'vec0'")
    return "vec0"


def _extract_wikilinks(content: str) -> list[str]:
    """Return deduplicated ``[[wikilink]]`` targets from *content*."""
    return list(dict.fromkeys(_WIKILINK_RE.findall(content)))


# Unit separator character — used as delimiter for CSV-stored lists
# that may contain commas (e.g. wikilinks like [[Hello, World]]).
_LIST_SEP = "\x1f"


def _sanitize_tags(tags: list[str]) -> list[str]:
    """Strip commas and separator chars, deduplicate, preserve order."""
    seen: dict[str, None] = {}
    for t in tags:
        cleaned = t.replace(",", "").replace(_LIST_SEP, "").strip()
        if cleaned and cleaned not in seen:
            seen[cleaned] = None
    return list(seen)


# ----------------------------------------------------------------------- #
# NoteEntry
# ----------------------------------------------------------------------- #

class NoteEntry:
    """In-memory representation of a row in ``note_entries``."""

    __slots__ = (
        "id", "title", "content", "folder_path", "tags",
        "wikilinks", "pinned", "created_at", "updated_at",
    )

    def __init__(
        self,
        *,
        id: str,
        title: str,
        content: str,
        folder_path: str,
        tags: list[str],
        wikilinks: list[str],
        pinned: bool,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.id = id
        self.title = title
        self.content = content
        self.folder_path = folder_path
        self.tags = tags
        self.wikilinks = wikilinks
        self.pinned = pinned
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "folder_path": self.folder_path,
            "tags": self.tags,
            "wikilinks": self.wikilinks,
            "pinned": self.pinned,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_entry(row: aiosqlite.Row) -> NoteEntry:
    """Convert a DB row to a ``NoteEntry``."""
    raw_tags = row["tags"] or ""
    raw_wikilinks = row["wikilinks"] or ""
    # Wikilinks use \x1f separator; legacy rows may still use commas.
    if _LIST_SEP in raw_wikilinks:
        wikilinks = [w for w in raw_wikilinks.split(_LIST_SEP) if w]
    else:
        wikilinks = [w for w in raw_wikilinks.split(",") if w]
    return NoteEntry(
        id=row["id"],
        title=row["title"],
        content=row["content"],
        folder_path=row["folder_path"] or "",
        tags=[t for t in raw_tags.split(",") if t],
        wikilinks=wikilinks,
        pinned=bool(row["pinned"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ----------------------------------------------------------------------- #
# SQL constants
# ----------------------------------------------------------------------- #

_CREATE_ENTRIES_SQL = """
CREATE TABLE IF NOT EXISTS note_entries (
    id          TEXT PRIMARY KEY,
    title       TEXT    NOT NULL,
    content     TEXT    NOT NULL DEFAULT '',
    folder_path TEXT    NOT NULL DEFAULT '',
    tags        TEXT    NOT NULL DEFAULT '',
    wikilinks   TEXT    NOT NULL DEFAULT '',
    pinned      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
"""

_CREATE_VECTORS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS note_vectors
USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[{dim}] distance_metric=cosine);
"""

_CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS note_fts
USING fts5(title, content, tags, content=note_entries, content_rowid=rowid);
"""

_FTS_TRIGGERS_SQL = """
CREATE TRIGGER IF NOT EXISTS note_fts_ai AFTER INSERT ON note_entries BEGIN
    INSERT INTO note_fts(rowid, title, content, tags)
    VALUES (new.rowid, new.title, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS note_fts_ad AFTER DELETE ON note_entries BEGIN
    INSERT INTO note_fts(note_fts, rowid, title, content, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS note_fts_au AFTER UPDATE ON note_entries BEGIN
    INSERT INTO note_fts(note_fts, rowid, title, content, tags)
    VALUES ('delete', old.rowid, old.title, old.content, old.tags);
    INSERT INTO note_fts(rowid, title, content, tags)
    VALUES (new.rowid, new.title, new.content, new.tags);
END;
"""


# ----------------------------------------------------------------------- #
# NoteService
# ----------------------------------------------------------------------- #

class NoteService:
    """Obsidian-like note vault with FTS5 + optional vector search.

    Args:
        config: ``NotesConfig`` sub-section from OMNIA config.
        llm_base_url: Base URL of the LLM / embedding API server.
    """

    def __init__(self, config: NotesConfig, llm_base_url: str) -> None:
        self._config = config
        self._llm_base_url = llm_base_url
        self._db: aiosqlite.Connection | None = None
        self._embed: EmbeddingClient | None = None
        self._closed = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def initialize(self) -> None:
        """Open DB, create tables, optionally load sqlite-vec."""
        if self._db is not None:
            logger.debug("NoteService already initialised, skipping")
            return

        self._closed = False

        db_path = Path(self._config.db_path)
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Opening notes DB at {}", db_path)
        self._db = await aiosqlite.connect(str(db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL;")

        # Vector extension (optional)
        if self._config.embedding_enabled:
            vec_path = _resolve_vec_extension_path()
            await self._db.enable_load_extension(True)
            await self._db.load_extension(vec_path)
            await self._db.enable_load_extension(False)
            logger.info("Loaded sqlite-vec for notes from {}", vec_path)

        # Schema
        await self._db.execute(_CREATE_ENTRIES_SQL)
        if self._config.embedding_enabled:
            await self._db.execute(
                _CREATE_VECTORS_SQL.format(
                    dim=self._config.embedding_dim,
                )
            )
        await self._db.execute(_CREATE_FTS_SQL)
        await self._db.executescript(_FTS_TRIGGERS_SQL)
        await self._db.commit()

        # Embedding client
        if self._config.embedding_enabled:
            self._embed = EmbeddingClient(
                base_url=self._llm_base_url,
                model=self._config.embedding_model,
                dimensions=self._config.embedding_dim,
                fallback_enabled=self._config.embedding_fallback,
            )

        # Check for embedding dimension migration
        if self._config.embedding_enabled:
            migrated = await self._maybe_migrate_vectors()
            if migrated:
                await self._db.execute(
                    _CREATE_VECTORS_SQL.format(
                        dim=self._config.embedding_dim,
                    )
                )
                await self._db.commit()
                if self._embed:
                    await self._reembed_all()

        logger.info(
            "NoteService ready (embedding={}, dim={})",
            self._config.embedding_enabled,
            self._config.embedding_dim,
        )

    async def close(self) -> None:
        """Shut down embedding client and DB connection."""
        if self._closed:
            return
        self._closed = True

        if self._embed:
            await self._embed.close()
            self._embed = None

        if self._db:
            await self._db.close()
            self._db = None

        logger.info("NoteService closed")

    # ------------------------------------------------------------------ #
    # Vector migration
    # ------------------------------------------------------------------ #

    async def _maybe_migrate_vectors(self) -> bool:
        """Drop note_vectors if its DDL doesn't match the current config.

        Reads the actual ``CREATE VIRTUAL TABLE`` statement from
        ``sqlite_master`` and checks for the correct embedding dimension
        and ``distance_metric=cosine``.  Dropping is safe: ``initialize()``
        will recreate the table and ``_reembed_all()`` will repopulate it.

        Returns:
            ``True`` if the table was dropped and must be recreated.
        """
        assert self._db is not None

        cursor = await self._db.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'note_vectors'"
        )
        row = await cursor.fetchone()
        if row is None:
            return False

        current_ddl: str = (row["sql"] or "").lower()
        want_dim = f"float[{self._config.embedding_dim}]"

        dim_ok = want_dim in current_ddl
        cosine_ok = "distance_metric=cosine" in current_ddl

        if dim_ok and cosine_ok:
            return False

        reasons: list[str] = []
        if not dim_ok:
            reasons.append(
                f"dim mismatch (want {self._config.embedding_dim})"
            )
        if not cosine_ok:
            reasons.append("cosine metric missing")
        logger.info(
            "Rebuilding note_vectors: {}", ", ".join(reasons),
        )

        await self._db.execute("DROP TABLE IF EXISTS note_vectors")
        await self._db.commit()
        return True

    async def _reembed_all(self) -> None:
        """Re-embed every note entry into the vectors table.

        Called after a migration that dropped the old vectors.
        """
        assert self._db is not None and self._embed is not None

        cursor = await self._db.execute(
            "SELECT id, title, content FROM note_entries"
        )
        entries = await cursor.fetchall()
        if not entries:
            return

        logger.info(
            "Re-embedding {} note entries after migration",
            len(entries),
        )
        for entry in entries:
            try:
                text = f"{entry['title']}\n{entry['content']}"
                vector = await self._embed.encode(text)
                if len(vector) != self._config.embedding_dim:
                    logger.warning(
                        "Skipping note {} — embedding dim {} != expected {}",
                        entry["id"], len(vector), self._config.embedding_dim,
                    )
                    continue
                await self._db.execute(
                    "INSERT INTO note_vectors (id, embedding) "
                    "VALUES (?, ?)",
                    (entry["id"], _serialize_f32(vector)),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to re-embed note {}: {}",
                    entry["id"], exc,
                )
        await self._db.commit()
        logger.info("Re-embedding complete")

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    async def create(
        self,
        title: str,
        content: str,
        folder_path: str = "",
        tags: list[str] | None = None,
    ) -> NoteEntry:
        """Create a new note.

        Args:
            title: Note title.
            content: Markdown body.
            folder_path: Virtual folder path (e.g. ``recipes/italian``).
            tags: Optional list of tag strings.

        Returns:
            The created ``NoteEntry``.
        """
        if not self._db:
            raise RuntimeError("NoteService not initialised")

        note_id = str(uuid.uuid4())
        now = _utcnow().isoformat()
        tag_list = _sanitize_tags(tags or [])
        wikilinks = _extract_wikilinks(content)
        tags_csv = ",".join(tag_list)
        wikilinks_csv = _LIST_SEP.join(wikilinks) + _LIST_SEP if wikilinks else ""

        await self._db.execute(
            """
            INSERT INTO note_entries
                (id, title, content, folder_path, tags,
                 wikilinks, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                note_id, title, content, folder_path,
                tags_csv, wikilinks_csv, now, now,
            ),
        )

        # Vector embedding
        if self._embed:
            try:
                text = f"{title}\n{content}"
                vector = await self._embed.encode(text)
                if len(vector) != self._config.embedding_dim:
                    logger.warning(
                        "Embedding dim mismatch: got {} expected {}",
                        len(vector), self._config.embedding_dim,
                    )
                else:
                    await self._db.execute(
                        "INSERT INTO note_vectors (id, embedding) "
                        "VALUES (?, ?)",
                        (note_id, _serialize_f32(vector)),
                    )
            except Exception as exc:
                logger.warning("Failed to embed note {}: {}", note_id, exc)

        await self._db.commit()
        logger.debug("Note created id={} title={!r}", note_id, title)

        return NoteEntry(
            id=note_id,
            title=title,
            content=content,
            folder_path=folder_path,
            tags=tag_list,
            wikilinks=wikilinks,
            pinned=False,
            created_at=now,
            updated_at=now,
        )

    async def get(self, note_id: str) -> NoteEntry | None:
        """Retrieve a single note by ID.

        Returns:
            The ``NoteEntry`` or ``None`` if not found.
        """
        if not self._db:
            raise RuntimeError("NoteService not initialised")

        cur = await self._db.execute(
            "SELECT * FROM note_entries WHERE id = ?", (note_id,),
        )
        row = await cur.fetchone()
        return _row_to_entry(row) if row else None

    async def update(
        self,
        note_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        folder_path: str | None = None,
        tags: list[str] | None = None,
        pinned: bool | None = None,
    ) -> NoteEntry | None:
        """Update fields of an existing note.

        Only non-``None`` parameters are changed.

        Returns:
            The updated ``NoteEntry`` or ``None`` if not found.
        """
        if not self._db:
            raise RuntimeError("NoteService not initialised")

        existing = await self.get(note_id)
        if existing is None:
            return None

        new_title = title if title is not None else existing.title
        new_content = (
            content if content is not None else existing.content
        )
        new_folder = (
            folder_path if folder_path is not None
            else existing.folder_path
        )
        new_tags = (
            _sanitize_tags(tags) if tags is not None
            else existing.tags
        )
        new_pinned = pinned if pinned is not None else existing.pinned
        new_wikilinks = _extract_wikilinks(new_content)
        now = _utcnow().isoformat()

        await self._db.execute(
            """
            UPDATE note_entries SET
                title = ?, content = ?, folder_path = ?,
                tags = ?, wikilinks = ?, pinned = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_title, new_content, new_folder,
                ",".join(new_tags),
                _LIST_SEP.join(new_wikilinks) + _LIST_SEP if new_wikilinks else "",
                int(new_pinned), now, note_id,
            ),
        )

        # Re-embed
        if self._embed and (title is not None or content is not None):
            try:
                text = f"{new_title}\n{new_content}"
                vector = await self._embed.encode(text)
                if len(vector) != self._config.embedding_dim:
                    logger.warning(
                        "Embedding dim mismatch: got {} expected {}",
                        len(vector), self._config.embedding_dim,
                    )
                else:
                    await self._db.execute(
                        "DELETE FROM note_vectors WHERE id = ?",
                        (note_id,),
                    )
                    await self._db.execute(
                        "INSERT INTO note_vectors (id, embedding) "
                        "VALUES (?, ?)",
                        (note_id, _serialize_f32(vector)),
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to re-embed note {}: {}", note_id, exc,
                )

        await self._db.commit()
        logger.debug("Note updated id={}", note_id)

        return NoteEntry(
            id=note_id,
            title=new_title,
            content=new_content,
            folder_path=new_folder,
            tags=new_tags,
            wikilinks=new_wikilinks,
            pinned=new_pinned,
            created_at=existing.created_at,
            updated_at=now,
        )

    async def delete(self, note_id: str) -> bool:
        """Delete a note by ID.

        Returns:
            ``True`` if a row was deleted, ``False`` if not found.
        """
        if not self._db:
            raise RuntimeError("NoteService not initialised")

        cur = await self._db.execute(
            "DELETE FROM note_entries WHERE id = ?", (note_id,),
        )
        if self._config.embedding_enabled:
            await self._db.execute(
                "DELETE FROM note_vectors WHERE id = ?", (note_id,),
            )
        await self._db.commit()
        deleted = cur.rowcount > 0
        if deleted:
            logger.debug("Note deleted id={}", note_id)
        return deleted

    # ------------------------------------------------------------------ #
    # Search (FTS5 + optional semantic)
    # ------------------------------------------------------------------ #

    async def search(
        self,
        query: str,
        folder: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search notes via FTS5 first, then semantic dedup merge.

        Args:
            query: Natural-language search text.
            folder: Optional folder filter.
            tags: Optional tag filter (AND logic).
            limit: Maximum results.

        Returns:
            List of dicts with ``entry`` and ``score`` keys.
        """
        if not self._db:
            raise RuntimeError("NoteService not initialised")

        if not query or not query.strip():
            return []

        limit = min(limit, self._config.max_search_results)
        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        # 1. FTS5 full-text search
        fts_query = query.replace('"', '""')
        try:
            fts_cur = await self._db.execute(
                """
                SELECT e.*, rank
                FROM note_fts f
                JOIN note_entries e ON e.rowid = f.rowid
                WHERE note_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (f'"{fts_query}"', limit * 2),
            )
            fts_rows = await fts_cur.fetchall()
            # Normalise FTS5 rank (negative, lower=better) to 0–1 score.
            if fts_rows:
                ranks = [abs(r["rank"]) for r in fts_rows]
                max_rank = max(ranks) or 1.0
                for row, abs_rank in zip(fts_rows, ranks):
                    entry = _row_to_entry(row)
                    if not self._matches_filters(entry, folder, tags):
                        continue
                    if entry.id not in seen:
                        seen.add(entry.id)
                        score = round(1.0 - abs_rank / (max_rank + 1.0), 4)
                        results.append({"entry": entry, "score": score})
        except Exception as exc:
            logger.debug("FTS5 search failed (non-fatal): {}", exc)

        # 2. Semantic search (if embedding enabled)
        if self._embed and len(results) < limit:
            try:
                query_vec = await self._embed.encode(query)
                sem_cur = await self._db.execute(
                    """
                    SELECT v.id, v.distance
                    FROM note_vectors v
                    WHERE v.embedding MATCH ?
                    ORDER BY v.distance
                    LIMIT ?
                    """,
                    (_serialize_f32(query_vec), limit * 2),
                )
                for row in await sem_cur.fetchall():
                    similarity = 1.0 - row["distance"]
                    if similarity < self._config.semantic_threshold:
                        continue
                    nid = row["id"]
                    if nid in seen:
                        continue
                    entry_cur = await self._db.execute(
                        "SELECT * FROM note_entries WHERE id = ?",
                        (nid,),
                    )
                    entry_row = await entry_cur.fetchone()
                    if entry_row is None:
                        continue
                    entry = _row_to_entry(entry_row)
                    if not self._matches_filters(entry, folder, tags):
                        continue
                    seen.add(nid)
                    results.append({
                        "entry": entry,
                        "score": round(similarity, 4),
                    })
                    if len(results) >= limit:
                        break
            except Exception as exc:
                logger.debug(
                    "Semantic note search failed (non-fatal): {}", exc,
                )

        return results[:limit]

    # ------------------------------------------------------------------ #
    # List / folders
    # ------------------------------------------------------------------ #

    async def list(
        self,
        folder: str | None = None,
        tags: list[str] | None = None,
        pinned_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[NoteEntry], int]:
        """List notes with optional filters.

        Returns:
            Tuple of (entries, total_count).
        """
        if not self._db:
            raise RuntimeError("NoteService not initialised")

        clauses: list[str] = []
        params: list[Any] = []

        if folder is not None:
            clauses.append("folder_path = ?")
            params.append(folder)
        if pinned_only:
            clauses.append("pinned = 1")
        if tags:
            for tag in tags:
                # Escape LIKE wildcards properly instead of stripping.
                escaped = (
                    tag.replace(",", "")
                    .replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                if escaped:
                    clauses.append(
                        "(',' || tags || ',') LIKE ? ESCAPE '\\'"
                    )
                    params.append(f"%,{escaped},%")

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        count_cur = await self._db.execute(
            f"SELECT COUNT(*) AS cnt FROM note_entries{where}",
            params[:],
        )
        total = (await count_cur.fetchone())["cnt"]

        params.extend([limit, offset])
        cursor = await self._db.execute(
            f"SELECT * FROM note_entries{where} "
            f"ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cursor.fetchall()
        return [_row_to_entry(r) for r in rows], total

    async def get_folders(self) -> list[dict[str, Any]]:
        """Return all folder paths with note counts.

        Returns:
            List of ``{"path": str, "count": int}`` dicts.
        """
        if not self._db:
            raise RuntimeError("NoteService not initialised")

        cursor = await self._db.execute(
            "SELECT folder_path, COUNT(*) AS cnt "
            "FROM note_entries GROUP BY folder_path "
            "ORDER BY folder_path"
        )
        rows = await cursor.fetchall()
        return [
            {"path": row["folder_path"] or "", "count": row["cnt"]}
            for row in rows
        ]

    async def delete_folder(
        self, folder_path: str, *, mode: str = "move",
    ) -> int:
        """Delete a folder and handle its notes.

        Args:
            folder_path: Folder to remove.
            mode: ``"move"`` moves notes to root, ``"delete"`` removes them.

        Returns:
            Number of affected notes.
        """
        if not self._db:
            raise RuntimeError("NoteService not initialised")
        if mode not in ("move", "delete"):
            raise ValueError(f"Invalid mode: {mode!r}")

        if mode == "move":
            cur = await self._db.execute(
                "UPDATE note_entries SET folder_path = '', updated_at = ? "
                "WHERE folder_path = ?",
                (_utcnow().isoformat(), folder_path),
            )
            await self._db.commit()
            affected = cur.rowcount
            logger.info(
                "Folder {!r} dissolved — {} notes moved to root",
                folder_path, affected,
            )
        else:
            if self._config.embedding_enabled:
                await self._db.execute(
                    "DELETE FROM note_vectors WHERE id IN "
                    "(SELECT id FROM note_entries WHERE folder_path = ?)",
                    (folder_path,),
                )
            cur = await self._db.execute(
                "DELETE FROM note_entries WHERE folder_path = ?",
                (folder_path,),
            )
            await self._db.commit()
            affected = cur.rowcount
            logger.info(
                "Folder {!r} deleted — {} notes removed",
                folder_path, affected,
            )
        return affected

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _matches_filters(
        entry: NoteEntry,
        folder: str | None,
        tags: list[str] | None,
    ) -> bool:
        """Check if an entry passes folder and tag filters."""
        if folder is not None and entry.folder_path != folder:
            return False
        if tags:
            entry_tags_lower = [t.lower() for t in entry.tags]
            for tag in tags:
                if tag.lower() not in entry_tags_lower:
                    return False
        return True
