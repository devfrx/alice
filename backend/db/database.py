"""AL\\CE — Database engine and session helpers."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession
from loguru import logger


def create_engine_and_session(
    db_url: str,
) -> tuple[AsyncEngine, async_sessionmaker]:
    """Create an async engine and a session factory.

    Args:
        db_url: SQLAlchemy-style database URL
                (e.g. ``sqlite+aiosqlite:///data/alice.db``).

    Returns:
        A tuple of ``(AsyncEngine, async_sessionmaker)`` where sessions
        are SQLModel-aware (supporting ``.exec()``).
    """
    engine_kwargs: dict[str, Any] = {
        "echo": False,
    }

    is_sqlite = db_url.startswith("sqlite")
    is_memory_sqlite = db_url in (
        "sqlite+aiosqlite://",
        "sqlite+aiosqlite:///:memory:",
    )

    if is_sqlite and is_memory_sqlite:
        # In-memory SQLite MUST use StaticPool so all sessions share
        # the single underlying connection (data lives only in memory).
        engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    elif is_sqlite:
        # File-based SQLite with WAL mode supports concurrent readers
        # + one writer.  Use a regular pool (NullPool avoided — we want
        # connection reuse) so each session gets its own connection with
        # an independent transaction snapshot.  This prevents stale reads
        # when a long-lived WebSocket session holds an implicit read
        # transaction while plugin tools query the DB separately.
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 3
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Non-SQLite databases benefit from pool_pre_ping to recover
        # from dropped connections (e.g. PostgreSQL idle timeout).
        engine_kwargs["pool_pre_ping"] = True
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10

    engine = create_async_engine(
        db_url,
        **engine_kwargs,
    )

    # Enable WAL journal mode and busy timeout for file-based SQLite.
    # WAL allows concurrent reads during writes and busy_timeout prevents
    # immediate "database is locked" errors under concurrent access.
    if is_sqlite and not is_memory_sqlite:
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    session_factory = async_sessionmaker(
        engine,
        class_=SQLModelAsyncSession,
        expire_on_commit=False,
    )
    return engine, session_factory


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables defined by SQLModel metadata.

    Also applies lightweight schema migrations for columns added after
    initial table creation (SQLAlchemy ``create_all`` only creates
    *missing tables*, not missing columns).

    Args:
        engine: The async engine to use for DDL execution.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # -- Lightweight column migrations --------------------------------------
    _COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
        ("messages", "thinking_content", "TEXT"),
        ("messages", "tool_calls", "TEXT"),
        ("messages", "tool_call_id", "VARCHAR(64)"),
        ("messages", "version_group_id", "TEXT"),
        ("messages", "version_index", "INTEGER DEFAULT 0"),
        ("conversations", "active_versions", "TEXT"),
        ("messages", "token_count", "INTEGER"),
        ("messages", "is_context_summary", "INTEGER DEFAULT 0"),
        ("messages", "context_excluded", "INTEGER DEFAULT 0"),
        ("conversations", "context_snapshot", "TEXT"),
    ]

    # Batch all column-existence checks in a single run_sync call to
    # avoid N async→sync context switches (one per column).
    def _find_missing_columns(sync_conn) -> list[tuple[str, str, str]]:
        """Return (table, column, col_type) tuples for missing columns."""
        inspector = sa.inspect(sync_conn)
        missing: list[tuple[str, str, str]] = []
        # Cache column names per table to avoid repeated introspection.
        table_columns: dict[str, set[str]] = {}
        for table, column, col_type in _COLUMN_MIGRATIONS:
            if table not in table_columns:
                if not inspector.has_table(table):
                    continue
                table_columns[table] = {
                    c["name"] for c in inspector.get_columns(table)
                }
            if column not in table_columns.get(table, set()):
                missing.append((table, column, col_type))
        return missing

    async with engine.begin() as conn:
        missing = await conn.run_sync(_find_missing_columns)
        for table, column, col_type in missing:
            await conn.execute(
                sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            )
            logger.info("Added missing column {}.{}", table, column)

    # -- Lightweight index migrations ---------------------------------------
    # Ensures indexes added after initial table creation are present in
    # existing databases (create_all only creates *missing tables*).
    _INDEX_MIGRATIONS: list[tuple[str, str, list[str]]] = [
        ("ix_message_conv_created", "messages", ["conversation_id", "created_at"]),
        ("ix_message_version_group", "messages", ["version_group_id"]),
        ("ix_attachment_message_id", "attachments", ["message_id"]),
    ]

    async with engine.begin() as conn:
        existing_indexes: set[str] = await conn.run_sync(
            lambda sync_conn: {
                idx["name"]
                for tbl in ("messages", "attachments")
                if sa.inspect(sync_conn).has_table(tbl)
                for idx in sa.inspect(sync_conn).get_indexes(tbl)
                if idx["name"]
            }
        )
        for idx_name, table, columns in _INDEX_MIGRATIONS:
            if idx_name not in existing_indexes:
                cols = ", ".join(columns)
                await conn.execute(
                    sa.text(
                        f"CREATE INDEX IF NOT EXISTS {idx_name} "
                        f"ON {table} ({cols})"
                    )
                )
                logger.info("Created missing index {} on {}", idx_name, table)

    # -- Schema rebuilds ----------------------------------------------------
    # SQLite cannot ALTER COLUMN; structural changes require copying the
    # table.  Each rebuild is idempotent: it inspects the live schema and
    # only acts when the desired state has not been reached yet.
    async with engine.begin() as conn:
        await conn.run_sync(_rebuild_artifacts_if_needed)


def _rebuild_artifacts_if_needed(sync_conn: Any) -> None:
    """Make ``artifacts.conversation_id`` nullable + FK SET NULL.

    Older databases were created with ``conversation_id NOT NULL`` and
    ``ON DELETE CASCADE``.  Pinned artifacts must survive deletion of
    their source conversation, so the column has to allow ``NULL`` and
    the FK has to ``SET NULL`` instead of cascading.  This routine
    rebuilds the table only when needed (cheap inspection on startup).
    """
    inspector = sa.inspect(sync_conn)
    if not inspector.has_table("artifacts"):
        return

    cols = {c["name"]: c for c in inspector.get_columns("artifacts")}
    conv_col = cols.get("conversation_id")
    fks = inspector.get_foreign_keys("artifacts")
    conv_fk = next(
        (fk for fk in fks if fk["constrained_columns"] == ["conversation_id"]),
        None,
    )

    needs_rebuild = (
        conv_col is not None and not conv_col.get("nullable", True)
    ) or (
        conv_fk is not None
        and (conv_fk.get("options") or {}).get("ondelete", "").upper()
        != "SET NULL"
    )
    if not needs_rebuild:
        return

    logger.info(
        "Rebuilding 'artifacts' table to allow NULL conversation_id "
        "with ON DELETE SET NULL (preserves pinned artifacts when a "
        "conversation is deleted)."
    )
    sync_conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    sync_conn.exec_driver_sql("ALTER TABLE artifacts RENAME TO artifacts__old")
    sync_conn.exec_driver_sql(
        """
        CREATE TABLE artifacts (
            id CHAR(32) NOT NULL PRIMARY KEY,
            conversation_id CHAR(32),
            message_id CHAR(32),
            tool_call_id VARCHAR(64),
            kind VARCHAR(32) NOT NULL,
            title VARCHAR(256) NOT NULL,
            file_path VARCHAR NOT NULL,
            mime VARCHAR(128) NOT NULL,
            size_bytes INTEGER NOT NULL,
            artifact_metadata JSON NOT NULL,
            pinned BOOLEAN NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                ON DELETE SET NULL,
            FOREIGN KEY(message_id) REFERENCES messages(id)
                ON DELETE SET NULL
        )
        """
    )
    sync_conn.exec_driver_sql(
        """
        INSERT INTO artifacts (
            id, conversation_id, message_id, tool_call_id, kind,
            title, file_path, mime, size_bytes, artifact_metadata,
            pinned, created_at, updated_at
        )
        SELECT id, conversation_id, message_id, tool_call_id, kind,
               title, file_path, mime, size_bytes, artifact_metadata,
               pinned, created_at, updated_at
        FROM artifacts__old
        """
    )
    sync_conn.exec_driver_sql("DROP TABLE artifacts__old")
    sync_conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_artifact_conv_created "
        "ON artifacts (conversation_id, created_at)"
    )
    sync_conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_artifact_kind_created "
        "ON artifacts (kind, created_at)"
    )
    sync_conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_artifacts_tool_call_id "
        "ON artifacts (tool_call_id)"
    )
    sync_conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    logger.success("'artifacts' table rebuild complete.")


