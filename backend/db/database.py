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

    # In-memory SQLite requires StaticPool so all sessions share the same DB.
    if db_url in ("sqlite+aiosqlite://", "sqlite+aiosqlite:///:memory:"):
        engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    elif not is_sqlite:
        # Connection pool tuning for non-SQLite databases (e.g. PostgreSQL).
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10

    engine = create_async_engine(
        db_url,
        **engine_kwargs,
    )
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
