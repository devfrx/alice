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


