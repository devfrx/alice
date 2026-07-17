"""Fixture condivise per la suite del motore greenfield.

``db_session``/``conv`` riproducono il pattern DB in-memory usato dai test di
piattaforma (es. ``backend/tests/test_agent_run_model.py``):
``create_engine_and_session("sqlite+aiosqlite://")`` + ``init_db(engine)`` con
``StaticPool`` (tutte le sessioni condividono l'unica connessione in-memory,
quindi un ``commit()`` in una sessione è visibile dalle altre — utile per
verificare che ``checkpoint()`` non perda righe dopo un ``rollback()``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.database import create_engine_and_session, init_db
from backend.db.models import Conversation


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Sessione async su SQLite in-memory con lo schema completo creato."""
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
    await init_db(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def conv(db_session: AsyncSession) -> Conversation:
    """Una ``Conversation`` persistita (flush, non commit) pronta per i test."""
    conversation = Conversation(title="test conversation")
    db_session.add(conversation)
    await db_session.flush()
    return conversation
