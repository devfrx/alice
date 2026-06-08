"""AL\\CE — Tests for the per-conversation permission-mode service (Fase 7)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import Conversation
from backend.services.permission_mode_service import (
    PermissionMode,
    PermissionModeService,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
async def conversation_id(session_factory) -> uuid.UUID:
    async with session_factory() as session:
        conv = Conversation(title="t")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv.id


def _service(session_factory, default=PermissionMode.STRICT) -> PermissionModeService:
    return PermissionModeService(session_factory=session_factory, default_mode=default)


# ---------------------------------------------------------------------------
# Coerce
# ---------------------------------------------------------------------------


class TestCoerce:
    def test_valid_member_passthrough(self) -> None:
        assert PermissionMode.coerce("autopilot", PermissionMode.STRICT) is PermissionMode.AUTOPILOT

    def test_invalid_falls_back(self) -> None:
        assert PermissionMode.coerce("nonsense", PermissionMode.STRICT) is PermissionMode.STRICT

    def test_none_and_objects_fall_back(self) -> None:
        assert PermissionMode.coerce(None, PermissionMode.PLAN) is PermissionMode.PLAN
        assert PermissionMode.coerce(object(), PermissionMode.PLAN) is PermissionMode.PLAN

    def test_member_passthrough(self) -> None:
        out = PermissionMode.coerce(PermissionMode.PLAN, PermissionMode.STRICT)
        assert out is PermissionMode.PLAN


# ---------------------------------------------------------------------------
# get_mode / set_mode
# ---------------------------------------------------------------------------


class TestModeService:
    async def test_unset_returns_default(self, session_factory) -> None:
        svc = _service(session_factory, default=PermissionMode.STRICT)
        await svc.load_all()
        assert svc.get_mode(uuid.uuid4()) is PermissionMode.STRICT

    async def test_custom_default(self, session_factory) -> None:
        svc = _service(session_factory, default=PermissionMode.AUTO_EDITS)
        assert svc.get_mode(uuid.uuid4()) is PermissionMode.AUTO_EDITS

    async def test_set_then_get(self, session_factory, conversation_id) -> None:
        svc = _service(session_factory)
        await svc.set_mode(conversation_id, PermissionMode.AUTOPILOT)
        assert svc.get_mode(conversation_id) is PermissionMode.AUTOPILOT

    async def test_set_is_idempotent_upsert(self, session_factory, conversation_id) -> None:
        svc = _service(session_factory)
        await svc.set_mode(conversation_id, PermissionMode.PLAN)
        await svc.set_mode(conversation_id, PermissionMode.AUTO_EDITS)
        assert svc.get_mode(conversation_id) is PermissionMode.AUTO_EDITS

    async def test_persists_across_reload(self, session_factory, conversation_id) -> None:
        svc = _service(session_factory)
        await svc.set_mode(conversation_id, PermissionMode.PLAN)
        # A fresh service instance loading the same DB sees the persisted tier.
        svc2 = _service(session_factory)
        await svc2.load_all()
        assert svc2.get_mode(conversation_id) is PermissionMode.PLAN

    async def test_emits_event_on_set(self, session_factory, conversation_id) -> None:
        events: list[dict[str, Any]] = []

        async def _cb(event: dict[str, Any]) -> None:
            events.append(event)

        svc = _service(session_factory)
        svc.set_event_callback(_cb)
        await svc.set_mode(conversation_id, PermissionMode.AUTOPILOT)
        assert len(events) == 1
        assert events[0]["type"] == "permission_mode.updated"
        assert events[0]["conversation_id"] == str(conversation_id)
        assert events[0]["mode"] == "autopilot"

    async def test_event_callback_failure_is_swallowed(
        self, session_factory, conversation_id,
    ) -> None:
        async def _boom(_event: dict[str, Any]) -> None:
            raise RuntimeError("nope")

        svc = _service(session_factory)
        svc.set_event_callback(_boom)
        # Must not raise — the mutation still succeeds.
        await svc.set_mode(conversation_id, PermissionMode.PLAN)
        assert svc.get_mode(conversation_id) is PermissionMode.PLAN
