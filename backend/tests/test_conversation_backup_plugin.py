"""AL\\CE — Tests for the conversation_backup plugin tool."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.plugin_models import ExecutionContext
from backend.db.models import Conversation, Message
from backend.plugins.conversation_backup.plugin import ConversationBackupPlugin


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


@pytest.fixture
async def plugin(session_factory):
    p = ConversationBackupPlugin()
    # Duck-typed ctx: il plugin usa solo ctx.db (session factory).
    await p.initialize(SimpleNamespace(db=session_factory))  # type: ignore[arg-type]
    return p


def _exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="s", conversation_id="c", execution_id="e",
    )


async def test_tool_definition_registered(plugin) -> None:
    tools = plugin.get_tools()
    assert [t.name for t in tools] == ["backup_conversations"]
    assert tools[0].risk_level == "safe"


async def test_backup_all_writes_files(
    plugin, session_factory, tmp_path, monkeypatch,
) -> None:
    import backend.plugins.conversation_backup.plugin as plugin_mod

    monkeypatch.setattr(plugin_mod, "PROJECT_ROOT", tmp_path)

    async with session_factory() as session:
        conv = Conversation(title="T")
        session.add(conv)
        await session.flush()
        session.add(Message(conversation_id=conv.id, role="user", content="hi"))
        await session.commit()
        conv_id = conv.id

    result = await plugin.execute_tool("backup_conversations", {}, _exec_ctx())

    assert result.success
    assert isinstance(result.content, dict)
    assert result.content["exported"] == 1
    out_dir = tmp_path / "data" / "backups"
    matches = list(out_dir.rglob(f"{conv_id}.json"))
    assert len(matches) == 1


async def test_backup_invalid_conversation_id(plugin) -> None:
    result = await plugin.execute_tool(
        "backup_conversations", {"conversation_id": "not-a-uuid"}, _exec_ctx(),
    )
    assert not result.success
