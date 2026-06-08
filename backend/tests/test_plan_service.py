"""AL\\CE — Tests for the conversation-plan persistence service."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import Conversation, ConversationPlan
from backend.services.plan_service import PlanService

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
def service(session_factory, captured_events) -> PlanService:
    async def _cb(event_payload: dict[str, Any]) -> None:
        captured_events.append(event_payload)

    svc = PlanService(session_factory=session_factory)
    svc.set_event_callback(_cb)
    return svc


# ---------------------------------------------------------------------------
# set_plan / get_plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_then_get_returns_steps(service, conversation_id):
    steps = [
        {"step": "research", "status": "pending"},
        {"step": "write", "status": "pending"},
    ]
    await service.set_plan(conversation_id, steps)
    assert await service.get_plan(conversation_id) == steps


@pytest.mark.asyncio
async def test_set_twice_updates_and_keeps_single_row(
    service, conversation_id, session_factory,
):
    first = [{"step": "a", "status": "pending"}]
    second = [
        {"step": "a", "status": "done"},
        {"step": "b", "status": "in_progress"},
    ]
    await service.set_plan(conversation_id, first)
    await service.set_plan(conversation_id, second)

    # Latest steps win.
    assert await service.get_plan(conversation_id) == second

    # Exactly one row for the conversation (idempotent UPSERT).
    async with session_factory() as session:
        rows = (await session.exec(select(ConversationPlan))).all()
    assert len(rows) == 1
    assert rows[0].conversation_id == conversation_id


@pytest.mark.asyncio
async def test_get_unknown_conversation_returns_empty(service):
    assert await service.get_plan(uuid.uuid4()) == []


@pytest.mark.asyncio
async def test_clear_removes_plan(service, conversation_id):
    await service.set_plan(conversation_id, [{"step": "x", "status": "pending"}])
    assert await service.get_plan(conversation_id) != []

    await service.clear(conversation_id)
    assert await service.get_plan(conversation_id) == []


@pytest.mark.asyncio
async def test_clear_unknown_conversation_is_noop(service):
    # Must not raise when there is no row to delete.
    await service.clear(uuid.uuid4())


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_plan_emits_event_once(
    service, captured_events, conversation_id,
):
    steps = [{"step": "ping", "status": "pending"}]
    await service.set_plan(conversation_id, steps)
    assert captured_events == [
        {
            "type": "plan.updated",
            "conversation_id": str(conversation_id),
            "steps": steps,
        }
    ]


@pytest.mark.asyncio
async def test_set_plan_survives_failing_callback(
    session_factory, conversation_id,
):
    async def _boom(_event: dict[str, Any]) -> None:
        raise RuntimeError("callback exploded")

    svc = PlanService(session_factory=session_factory)
    svc.set_event_callback(_boom)

    steps = [{"step": "y", "status": "pending"}]
    # The raising callback must not break persistence.
    await svc.set_plan(conversation_id, steps)
    assert await svc.get_plan(conversation_id) == steps


# ---------------------------------------------------------------------------
# Cascade on parent delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_conversation_cascades_plan(
    service, conversation_id, session_factory,
):
    await service.set_plan(conversation_id, [{"step": "z", "status": "pending"}])

    # Deleting the parent conversation must remove its plan row via the
    # ``ON DELETE CASCADE`` FK (foreign-key enforcement enabled in fixture).
    async with session_factory() as session:
        conv = await session.get(Conversation, conversation_id)
        assert conv is not None
        await session.delete(conv)
        await session.commit()

    assert await service.get_plan(conversation_id) == []
    async with session_factory() as session:
        rows = (await session.exec(select(ConversationPlan))).all()
    assert rows == []
