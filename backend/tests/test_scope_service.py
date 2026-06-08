"""AL\\CE — Tests for the per-conversation workspace-scope service."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.config import WorkspaceScopeConfig
from backend.db.models import Conversation, ConversationScope
from backend.services.scope_service import ScopeService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory():
    """In-memory SQLite + session factory with FK enforcement enabled.

    SQLite does not enforce foreign keys (and therefore ``ON DELETE
    CASCADE``) unless ``PRAGMA foreign_keys=ON`` is set per connection, so
    we attach a ``connect`` listener to exercise the cascade in tests.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=SQLModelAsyncSession, expire_on_commit=False,
    )
    yield factory
    await engine.dispose()


@pytest.fixture
async def conversation_id(session_factory) -> uuid.UUID:
    """Insert a parent Conversation row and return its id."""
    async with session_factory() as session:
        conv = Conversation(title="t")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv.id


@pytest.fixture
def captured_events() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def service(session_factory, captured_events) -> ScopeService:
    async def _cb(event_payload: dict[str, Any]) -> None:
        captured_events.append(event_payload)

    svc = ScopeService(
        session_factory=session_factory,
        config=WorkspaceScopeConfig(),
    )
    svc.set_event_callback(_cb)
    return svc


@pytest.fixture
def ws_folder(tmp_path: Path) -> Path:
    """A real, existing directory usable as a workspace scope root."""
    folder = tmp_path / "workspace"
    folder.mkdir()
    return folder


# ---------------------------------------------------------------------------
# set_scope / get_scope / scope_roots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_then_get_and_scope_roots(service, conversation_id, ws_folder):
    await service.set_scope(conversation_id, [str(ws_folder)])

    # REST view: absolute strings.
    assert await service.get_scope(conversation_id) == [str(ws_folder.resolve())]
    # Permission-provider view: resolved Paths.
    assert service.scope_roots(str(conversation_id)) == [ws_folder.resolve()]


@pytest.mark.asyncio
async def test_set_scope_is_upsert_single_row(
    service, conversation_id, session_factory, tmp_path,
):
    first = tmp_path / "a"
    first.mkdir()
    second = tmp_path / "b"
    second.mkdir()

    await service.set_scope(conversation_id, [str(first)])
    await service.set_scope(conversation_id, [str(second)])

    # Latest folders win.
    assert service.scope_roots(str(conversation_id)) == [second.resolve()]

    # Exactly one row for the conversation (idempotent UPSERT).
    async with session_factory() as session:
        rows = (await session.exec(select(ConversationScope))).all()
    assert len(rows) == 1
    assert rows[0].conversation_id == conversation_id


@pytest.mark.asyncio
async def test_scope_roots_none_when_unset(service):
    # No scope set ⇒ None (the behaviour-preserving default: no confinement).
    assert service.scope_roots(str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_get_scope_empty_when_unset(service):
    assert await service.get_scope(uuid.uuid4()) == []


# ---------------------------------------------------------------------------
# clear_scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_scope_empties(
    service, conversation_id, session_factory, ws_folder,
):
    await service.set_scope(conversation_id, [str(ws_folder)])
    assert service.scope_roots(str(conversation_id)) is not None

    await service.clear_scope(conversation_id)

    assert service.scope_roots(str(conversation_id)) is None
    assert await service.get_scope(conversation_id) == []

    # The DB row is gone too.
    async with session_factory() as session:
        rows = (await session.exec(select(ConversationScope))).all()
    assert rows == []


# ---------------------------------------------------------------------------
# load_all (rebuild the in-memory mirror from the DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_all_repopulates_in_memory_dict(
    session_factory, conversation_id, ws_folder,
):
    # One instance persists a scope (writes the DB + its own memory).
    writer = ScopeService(
        session_factory=session_factory, config=WorkspaceScopeConfig(),
    )
    await writer.set_scope(conversation_id, [str(ws_folder)])

    # A fresh instance over the same engine starts empty, then load_all
    # rebuilds the in-memory dict so scope_roots is correct without async.
    reader = ScopeService(
        session_factory=session_factory, config=WorkspaceScopeConfig(),
    )
    assert reader.scope_roots(str(conversation_id)) is None

    await reader.load_all()
    assert reader.scope_roots(str(conversation_id)) == [ws_folder.resolve()]


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_scope_emits_event(
    service, captured_events, conversation_id, ws_folder,
):
    await service.set_scope(conversation_id, [str(ws_folder)])
    assert captured_events == [
        {
            "type": "scope.updated",
            "conversation_id": str(conversation_id),
            "folders": [str(ws_folder.resolve())],
        }
    ]


@pytest.mark.asyncio
async def test_clear_scope_emits_empty_event(
    service, captured_events, conversation_id, ws_folder,
):
    await service.set_scope(conversation_id, [str(ws_folder)])
    captured_events.clear()

    await service.clear_scope(conversation_id)
    assert captured_events == [
        {
            "type": "scope.updated",
            "conversation_id": str(conversation_id),
            "folders": [],
        }
    ]


# ---------------------------------------------------------------------------
# validate_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_folder_accepts_real_dir(service, ws_folder):
    assert service.validate_folder(str(ws_folder)) == ws_folder.resolve()


@pytest.mark.asyncio
async def test_validate_folder_rejects_nonexistent(service, tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ValueError):
        service.validate_folder(str(missing))


@pytest.mark.asyncio
async def test_validate_folder_rejects_file(service, tmp_path):
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    with pytest.raises(ValueError):
        service.validate_folder(str(a_file))


@pytest.mark.asyncio
async def test_validate_folder_rejects_unc_path(service):
    # UNC network share — refused before any filesystem access.
    with pytest.raises(ValueError):
        service.validate_folder(r"\\server\share")


@pytest.mark.asyncio
async def test_validate_folder_rejects_empty(service):
    with pytest.raises(ValueError):
        service.validate_folder("   ")


@pytest.mark.asyncio
async def test_set_scope_rejects_bad_folder_without_persisting(
    service, conversation_id, session_factory, ws_folder, tmp_path,
):
    missing = tmp_path / "nope"
    # A single bad entry must raise and persist nothing (validation is
    # performed up-front, before any DB write).
    with pytest.raises(ValueError):
        await service.set_scope(conversation_id, [str(ws_folder), str(missing)])

    assert service.scope_roots(str(conversation_id)) is None
    async with session_factory() as session:
        rows = (await session.exec(select(ConversationScope))).all()
    assert rows == []
