"""O.M.N.I.A. — Database engine and session helpers."""

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
                (e.g. ``sqlite+aiosqlite:///data/omnia.db``).

    Returns:
        A tuple of ``(AsyncEngine, async_sessionmaker)`` where sessions
        are SQLModel-aware (supporting ``.exec()``).
    """
    engine_kwargs: dict[str, Any] = {
        "echo": False,
        "pool_pre_ping": True,
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
        # Connection pool tuning for non-SQLite databases (e.g. PostgreSQL).
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
    ]

    async with engine.begin() as conn:
        for table, column, col_type in _COLUMN_MIGRATIONS:
            exists = await conn.run_sync(
                lambda sync_conn, t=table, c=column: c
                in [
                    col["name"]
                    for col in sa.inspect(sync_conn).get_columns(t)
                ]
                if sa.inspect(sync_conn).has_table(t)
                else True
            )
            if not exists:
                await conn.execute(
                    sa.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                )
                logger.info("Added missing column {}.{}", table, column)


