"""AL\\CE — Tests for the conversation plan-document persistence service."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import Conversation, ConversationPlanDocument
from backend.services.plan_document_service import (
    PlanDocumentService,
    render_plan_document,
)

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
def service(session_factory, captured_events) -> PlanDocumentService:
    async def _cb(event_payload: dict[str, Any]) -> None:
        captured_events.append(event_payload)

    svc = PlanDocumentService(session_factory=session_factory)
    svc.set_event_callback(_cb)
    return svc


# ---------------------------------------------------------------------------
# set_document / get_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_then_get_round_trips_title_and_body(service, conversation_id):
    await service.set_document(conversation_id, "Plan A", "## Step 1\nDo it.")
    doc = await service.get_document(conversation_id)
    assert doc is not None
    assert doc["title"] == "Plan A"
    assert doc["body"] == "## Step 1\nDo it."
    assert doc["updated_at"] is not None


@pytest.mark.asyncio
async def test_set_twice_replaces_wholesale_and_keeps_single_row(
    service, conversation_id, session_factory,
):
    await service.set_document(conversation_id, "First", "first body")
    await service.set_document(conversation_id, "Second", "second body")

    # Latest content wins (wholesale replace).
    doc = await service.get_document(conversation_id)
    assert doc is not None
    assert doc["title"] == "Second"
    assert doc["body"] == "second body"

    # Exactly one row for the conversation (idempotent UPSERT).
    async with session_factory() as session:
        rows = (await session.exec(select(ConversationPlanDocument))).all()
    assert len(rows) == 1
    assert rows[0].conversation_id == conversation_id
    assert rows[0].title == "Second"
    assert rows[0].body == "second body"


@pytest.mark.asyncio
async def test_get_unknown_conversation_returns_none(service):
    assert await service.get_document(uuid.uuid4()) is None


# ---------------------------------------------------------------------------
# clear_document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_empties_document(service, conversation_id):
    await service.set_document(conversation_id, "Plan", "body")
    assert await service.get_document(conversation_id) is not None

    await service.clear_document(conversation_id)
    assert await service.get_document(conversation_id) is None


@pytest.mark.asyncio
async def test_clear_unknown_conversation_is_noop(service):
    # Must not raise when there is no row to delete.
    await service.clear_document(uuid.uuid4())


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_document_emits_event_with_body(
    service, captured_events, conversation_id,
):
    await service.set_document(conversation_id, "T", "the markdown body")
    assert len(captured_events) == 1
    payload = captured_events[0]
    assert payload["type"] == "plan_document.updated"
    assert payload["conversation_id"] == str(conversation_id)
    assert payload["title"] == "T"
    assert payload["body"] == "the markdown body"
    assert payload["updated_at"] is not None


@pytest.mark.asyncio
async def test_clear_document_emits_empty_body(
    service, captured_events, conversation_id,
):
    await service.set_document(conversation_id, "T", "body")
    captured_events.clear()

    await service.clear_document(conversation_id)
    assert captured_events == [
        {
            "type": "plan_document.updated",
            "conversation_id": str(conversation_id),
            "title": "",
            "body": "",
            "updated_at": None,
        }
    ]


@pytest.mark.asyncio
async def test_set_document_survives_failing_callback(
    session_factory, conversation_id,
):
    async def _boom(_event: dict[str, Any]) -> None:
        raise RuntimeError("callback exploded")

    svc = PlanDocumentService(session_factory=session_factory)
    svc.set_event_callback(_boom)

    # The raising callback must not break persistence.
    await svc.set_document(conversation_id, "T", "b")
    doc = await svc.get_document(conversation_id)
    assert doc is not None
    assert doc["body"] == "b"


# ---------------------------------------------------------------------------
# load_all (startup mirror hydration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_all_hydrates_mirror(
    session_factory, conversation_id,
):
    # Persist with one service instance...
    writer = PlanDocumentService(session_factory=session_factory)
    await writer.set_document(conversation_id, "Persisted", "persisted body")

    # ...then a fresh instance must see it only after load_all().
    reader = PlanDocumentService(session_factory=session_factory)
    assert await reader.get_document(conversation_id) is None
    await reader.load_all()

    doc = await reader.get_document(conversation_id)
    assert doc is not None
    assert doc["title"] == "Persisted"
    assert doc["body"] == "persisted body"


# ---------------------------------------------------------------------------
# Cascade on parent delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_conversation_cascades_document(
    service, conversation_id, session_factory,
):
    await service.set_document(conversation_id, "Z", "z body")

    # Deleting the parent conversation must remove its document row via the
    # ``ON DELETE CASCADE`` FK (foreign-key enforcement enabled in fixture).
    async with session_factory() as session:
        conv = await session.get(Conversation, conversation_id)
        assert conv is not None
        await session.delete(conv)
        await session.commit()

    async with session_factory() as session:
        rows = (await session.exec(select(ConversationPlanDocument))).all()
    assert rows == []


# ---------------------------------------------------------------------------
# render_plan_document (pure re-injection rendering)
# ---------------------------------------------------------------------------


def test_render_plan_document_empty_returns_empty_string():
    # No content ⇒ no context block (caller guards on this too).
    assert render_plan_document({}) == ""
    assert render_plan_document({"title": "", "body": ""}) == ""


def test_render_plan_document_includes_title_and_body():
    rendered = render_plan_document(
        {"title": "Release plan", "body": "1. cut branch\n2. tag"}
    )
    assert isinstance(rendered, str)
    assert rendered.startswith("# Current plan document\n\n")
    assert "Release plan" in rendered
    assert "1. cut branch" in rendered
    assert "2. tag" in rendered


def test_render_plan_document_reads_keys_defensively():
    # Missing keys must not raise; a body-only doc still renders.
    rendered = render_plan_document({"body": "just a body"})
    assert isinstance(rendered, str)
    assert rendered.startswith("# Current plan document\n\n")
    assert "just a body" in rendered
