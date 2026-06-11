"""AL\\CE — Tests for backend.services.conversation_export."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import Attachment, Conversation, Message
from backend.services.conversation_export import (
    _UPLOADS_BASE,
    ConversationExport,
    build_conversation_export,
    export_conversations_to_dir,
)


@pytest.fixture
async def session_factory():
    """In-memory SQLite + session factory with all tables created."""
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=SQLModelAsyncSession, expire_on_commit=False,
    )
    yield factory
    await engine.dispose()


async def _seed_conversation(session_factory, *, title: str = "Test") -> uuid.UUID:
    """Insert a conversation with one user + one assistant message."""
    async with session_factory() as session:
        conv = Conversation(title=title)
        session.add(conv)
        await session.flush()
        session.add(Message(conversation_id=conv.id, role="user", content="hi"))
        session.add(
            Message(
                conversation_id=conv.id,
                role="assistant",
                content="hello",
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "f", "arguments": "{}"},
                    },
                ],
            ),
        )
        await session.commit()
        return conv.id


class TestBuildConversationExport:
    async def test_returns_full_dict(self, session_factory) -> None:
        conv_id = await _seed_conversation(session_factory)
        async with session_factory() as session:
            data = await build_conversation_export(session, conv_id)
        assert data["id"] == str(conv_id)
        assert data["title"] == "Test"
        assert len(data["messages"]) == 2
        assert data["messages"][1]["tool_calls"][0]["id"] == "call_1"
        # Il dict prodotto DEVE validare contro il modello del contratto.
        ConversationExport.model_validate(data)

    async def test_missing_conversation_returns_empty(self, session_factory) -> None:
        async with session_factory() as session:
            data = await build_conversation_export(session, uuid.uuid4())
        assert data == {}

    async def test_attachment_serialization(self, session_factory) -> None:
        """Attachments round-trip with file_id, url and file_path."""
        async with session_factory() as session:
            conv = Conversation(title="Att")
            session.add(conv)
            await session.flush()
            msg = Message(conversation_id=conv.id, role="user", content="img")
            session.add(msg)
            await session.flush()
            att = Attachment(
                message_id=msg.id,
                filename="photo.png",
                content_type="image/png",
                file_path=str(_UPLOADS_BASE / str(conv.id) / "photo.png"),
            )
            session.add(att)
            await session.commit()
            conv_id, att_id = conv.id, att.id

        async with session_factory() as session:
            data = await build_conversation_export(session, conv_id)

        atts = data["messages"][0]["attachments"]
        assert atts is not None and len(atts) == 1
        assert atts[0]["file_id"] == str(att_id)
        assert atts[0]["url"] == f"/uploads/{conv_id}/photo.png"
        assert atts[0]["file_path"].endswith("photo.png")
        ConversationExport.model_validate(data)

    async def test_attachment_outside_uploads_base_gets_empty_url(
        self, session_factory, tmp_path: Path,
    ) -> None:
        """A file_path escaping the uploads base yields an empty url."""
        async with session_factory() as session:
            conv = Conversation(title="Evil")
            session.add(conv)
            await session.flush()
            msg = Message(conversation_id=conv.id, role="user", content="x")
            session.add(msg)
            await session.flush()
            session.add(
                Attachment(
                    message_id=msg.id,
                    filename="evil.png",
                    content_type="image/png",
                    file_path=str(tmp_path / "evil.png"),
                ),
            )
            await session.commit()
            conv_id = conv.id

        async with session_factory() as session:
            data = await build_conversation_export(session, conv_id)

        atts = data["messages"][0]["attachments"]
        assert atts is not None
        assert atts[0]["url"] == ""
        ConversationExport.model_validate(data)


class TestExportConversationsToDir:
    async def test_exports_all_to_directory(
        self, session_factory, tmp_path: Path,
    ) -> None:
        id_a = await _seed_conversation(session_factory, title="A")
        id_b = await _seed_conversation(session_factory, title="B")
        dest = tmp_path / "backup"

        exported = await export_conversations_to_dir(session_factory, dest)

        assert exported == 2
        for cid in (id_a, id_b):
            payload = json.loads(
                (dest / f"{cid}.json").read_text(encoding="utf-8"),
            )
            assert payload["id"] == str(cid)
        # Nessun file temporaneo residuo.
        assert list(dest.glob("*.tmp.*")) == []

    async def test_exports_subset_by_id(
        self, session_factory, tmp_path: Path,
    ) -> None:
        id_a = await _seed_conversation(session_factory, title="A")
        await _seed_conversation(session_factory, title="B")
        dest = tmp_path / "backup"

        exported = await export_conversations_to_dir(
            session_factory, dest, conversation_ids=[id_a],
        )

        assert exported == 1
        assert (dest / f"{id_a}.json").exists()
        assert len(list(dest.glob("*.json"))) == 1

    async def test_unknown_id_is_skipped(
        self, session_factory, tmp_path: Path,
    ) -> None:
        dest = tmp_path / "backup"
        exported = await export_conversations_to_dir(
            session_factory, dest, conversation_ids=[uuid.uuid4()],
        )
        assert exported == 0
