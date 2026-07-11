"""AL\\CE — Bootstrap stage: database engine + session factory (Fase 5)."""

from __future__ import annotations

from pathlib import Path

from backend.core.context import AppContext
from backend.db.database import create_engine_and_session, init_db


async def stage_database(ctx: AppContext, *, testing: bool) -> None:
    """Create the async engine + session factory and store them on ``ctx``.

    Args:
        ctx: The application context being bootstrapped.
        testing: When ``True``, use an in-memory SQLite database.
    """
    config = ctx.config

    if testing:
        db_url = "sqlite+aiosqlite://"  # in-memory
    else:
        db_url = config.database.url
        # Ensure the directory for the SQLite file exists.
        if "sqlite" in db_url and ":///" in db_url:
            db_path = db_url.split(":///", 1)[-1]
            if db_path:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine, session_factory = create_engine_and_session(db_url)
    await init_db(engine)

    ctx.db = session_factory
    ctx.engine = engine
