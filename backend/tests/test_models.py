"""Tests for backend.db.models — Conversation & Message + DB round-trip."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import select

from backend.db.database import create_engine_and_session, init_db
from backend.db.models import Conversation, Message

# ---------------------------------------------------------------------------
# Unit tests — model creation with defaults
# ---------------------------------------------------------------------------


def test_conversation_has_uuid_by_default() -> None:
    conv = Conversation()
    assert isinstance(conv.id, uuid.UUID)


def test_conversation_has_timestamps() -> None:
    conv = Conversation()
    assert isinstance(conv.created_at, datetime)
    assert isinstance(conv.updated_at, datetime)
    assert conv.created_at.tzinfo is not None  # timezone-aware


def test_conversation_title_defaults_to_none() -> None:
    conv = Conversation()
    assert conv.title is None


def test_message_creation_with_required_fields() -> None:
    conv_id = uuid.uuid4()
    msg = Message(conversation_id=conv_id, role="user", content="hello")
    assert isinstance(msg.id, uuid.UUID)
    assert msg.conversation_id == conv_id
    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.tool_calls is None
    assert isinstance(msg.created_at, datetime)


# ---------------------------------------------------------------------------
# Database round-trip tests (in-memory SQLite)
# ---------------------------------------------------------------------------


async def test_db_roundtrip_conversation() -> None:
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
    await init_db(engine)

    conv = Conversation(title="Test conversation")

    async with session_factory() as session:
        session.add(conv)
        await session.commit()

    async with session_factory() as session:
        result = await session.exec(select(Conversation))
        rows = result.all()
        assert len(rows) == 1
        assert rows[0].title == "Test conversation"
        assert rows[0].id == conv.id

    await engine.dispose()


async def test_db_roundtrip_message() -> None:
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
    await init_db(engine)

    conv = Conversation(title="Chat")
    async with session_factory() as session:
        session.add(conv)
        await session.commit()

    msg = Message(conversation_id=conv.id, role="user", content="Hi!")
    async with session_factory() as session:
        session.add(msg)
        await session.commit()

    async with session_factory() as session:
        result = await session.exec(
            select(Message).where(Message.conversation_id == conv.id)
        )
        rows = result.all()
        assert len(rows) == 1
        assert rows[0].role == "user"
        assert rows[0].content == "Hi!"

    await engine.dispose()


async def test_db_conversation_with_multiple_messages() -> None:
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
    await init_db(engine)

    conv = Conversation()
    async with session_factory() as session:
        session.add(conv)
        await session.commit()

    async with session_factory() as session:
        session.add(Message(conversation_id=conv.id, role="user", content="Q"))
        session.add(Message(conversation_id=conv.id, role="assistant", content="A"))
        await session.commit()

    async with session_factory() as session:
        result = await session.exec(
            select(Message).where(Message.conversation_id == conv.id)
        )
        rows = result.all()
        assert len(rows) == 2
        roles = {m.role for m in rows}
        assert roles == {"user", "assistant"}

    await engine.dispose()
