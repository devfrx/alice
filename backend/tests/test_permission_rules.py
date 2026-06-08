"""AL\\CE — Tests for the persistent permission-rule service (Fase 7)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import Conversation
from backend.services.permission_rules import PermissionRuleService, RuleEffect


@pytest.fixture
async def session_factory():
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
async def conv(session_factory) -> uuid.UUID:
    async with session_factory() as session:
        c = Conversation(title="t")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        return c.id


async def _svc(session_factory) -> PermissionRuleService:
    svc = PermissionRuleService(session_factory=session_factory)
    await svc.load_all()
    return svc


class TestMatch:
    async def test_no_rule_returns_none(self, session_factory, conv) -> None:
        svc = await _svc(session_factory)
        assert svc.match(str(conv), "any_tool") is None

    async def test_global_rule_applies_everywhere(self, session_factory) -> None:
        svc = await _svc(session_factory)
        await svc.add_rule(tool_name="write_text_file", effect=RuleEffect.DENY)
        assert svc.match(str(uuid.uuid4()), "write_text_file") is RuleEffect.DENY

    async def test_conversation_rule_shadows_global(self, session_factory, conv) -> None:
        svc = await _svc(session_factory)
        await svc.add_rule(tool_name="write_text_file", effect=RuleEffect.DENY)  # global
        await svc.add_rule(
            tool_name="write_text_file", effect=RuleEffect.ALLOW, conversation_id=conv,
        )
        assert svc.match(str(conv), "write_text_file") is RuleEffect.ALLOW
        # A different conversation still sees the global deny.
        assert svc.match(str(uuid.uuid4()), "write_text_file") is RuleEffect.DENY


class TestUpsertAndRemove:
    async def test_add_is_upsert(self, session_factory, conv) -> None:
        svc = await _svc(session_factory)
        await svc.add_rule(tool_name="t", effect=RuleEffect.ALLOW, conversation_id=conv)
        await svc.add_rule(tool_name="t", effect=RuleEffect.ASK, conversation_id=conv)
        assert svc.match(str(conv), "t") is RuleEffect.ASK
        rules = await svc.list_rules(conv)
        assert len([r for r in rules if r.tool_name == "t"]) == 1  # no duplicate

    async def test_remove_rule(self, session_factory, conv) -> None:
        svc = await _svc(session_factory)
        row = await svc.add_rule(tool_name="t", effect=RuleEffect.DENY, conversation_id=conv)
        assert svc.match(str(conv), "t") is RuleEffect.DENY
        await svc.remove_rule(row.id)
        assert svc.match(str(conv), "t") is None

    async def test_list_includes_global_and_conversation(self, session_factory, conv) -> None:
        svc = await _svc(session_factory)
        await svc.add_rule(tool_name="a", effect=RuleEffect.ALLOW)  # global
        await svc.add_rule(tool_name="b", effect=RuleEffect.DENY, conversation_id=conv)
        names = {r.tool_name for r in await svc.list_rules(conv)}
        assert names == {"a", "b"}

    async def test_persists_across_reload(self, session_factory, conv) -> None:
        svc = await _svc(session_factory)
        await svc.add_rule(tool_name="t", effect=RuleEffect.DENY, conversation_id=conv)
        svc2 = await _svc(session_factory)
        assert svc2.match(str(conv), "t") is RuleEffect.DENY
