"""AL\\CE — Integration: ScopeService confines PermissionService by construction.

Wires a **real** :class:`~backend.services.scope_service.ScopeService` into a
real :class:`~backend.services.permission_service.PermissionService` (no mock
provider) and proves the confinement contract end-to-end through
:meth:`~backend.services.permission_service.PermissionService.decide`:

* a filesystem-tagged tool is denied a path outside the conversation scope;
* the same tool is allowed a path inside the scope;
* a conversation with **no** scope set hits the no-scope breaker (deny);
* a tool that is *not* filesystem-tagged is never confined;
* ``..`` traversal escaping the scope is denied (the layer resolves first).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.config import WorkspaceScopeConfig
from backend.core.plugin_models import ToolDefinition
from backend.db.models import Conversation
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_service import (
    GateAction,
    PermissionOutcome,
    PermissionService,
)
from backend.services.scope_service import ScopeService

# ---------------------------------------------------------------------------
# Fixtures (in-memory SQLite + FK pragma — mirrors test_scope_service.py)
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory():
    """In-memory SQLite + session factory with FK enforcement enabled."""
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
def scope_service(session_factory) -> ScopeService:
    """A real ScopeService over the in-memory engine."""
    return ScopeService(
        session_factory=session_factory,
        config=WorkspaceScopeConfig(),
    )


def _fs_tool() -> ToolDefinition:
    """A filesystem-tagged tool whose ``path`` arg is scope-confined."""
    return ToolDefinition(
        name="fs_tool",
        description="A filesystem-tagged tool.",
        capabilities=("fs_write",),
        path_args=("path",),
        risk_level="safe",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_scope_path_is_allowed(
    scope_service, conversation_id, tmp_path,
):
    inside = tmp_path / "inside"
    inside.mkdir()
    await scope_service.set_scope(conversation_id, [str(inside)])

    perm = PermissionService(
        scope_provider=scope_service.scope_roots, forbidden_paths=[],
    )
    decision = perm.decide(
        tool_name="fs_tool",
        args={"path": str(inside / "f.txt")},
        tool_def=_fs_tool(),
        conversation_id=str(conversation_id),
        mode=PermissionMode.STRICT,
    )

    assert decision.action is GateAction.ALLOW
    assert decision.outcome is PermissionOutcome.ALLOW


@pytest.mark.asyncio
async def test_out_of_scope_path_is_denied(
    scope_service, conversation_id, tmp_path,
):
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    await scope_service.set_scope(conversation_id, [str(inside)])

    perm = PermissionService(
        scope_provider=scope_service.scope_roots, forbidden_paths=[],
    )
    decision = perm.decide(
        tool_name="fs_tool",
        args={"path": str(outside / "f.txt")},
        tool_def=_fs_tool(),
        conversation_id=str(conversation_id),
        mode=PermissionMode.STRICT,
    )

    assert decision.action is GateAction.DENY
    assert decision.outcome is PermissionOutcome.DENY_SCOPE


@pytest.mark.asyncio
async def test_conversation_without_scope_hits_no_scope_breaker(
    scope_service, conversation_id, tmp_path,
):
    # One conversation has a scope; a *different* one has none ⇒ for a
    # filesystem-tagged tool the no-scope breaker denies (any tier).
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    await scope_service.set_scope(conversation_id, [str(inside)])

    perm = PermissionService(
        scope_provider=scope_service.scope_roots, forbidden_paths=[],
    )
    other = uuid.uuid4()
    decision = perm.decide(
        tool_name="fs_tool",
        args={"path": str(outside / "f.txt")},
        tool_def=_fs_tool(),
        conversation_id=str(other),
        mode=PermissionMode.STRICT,
    )

    assert decision.action is GateAction.DENY
    assert decision.outcome is PermissionOutcome.DENY_NO_SCOPE


@pytest.mark.asyncio
async def test_non_fs_tagged_tool_is_never_confined(
    scope_service, conversation_id, tmp_path,
):
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    await scope_service.set_scope(conversation_id, [str(inside)])

    perm = PermissionService(
        scope_provider=scope_service.scope_roots, forbidden_paths=[],
    )
    # capabilities=() ⇒ not a path-confined tool, even with an out-of-scope path.
    untagged = ToolDefinition(
        name="plain_tool",
        description="Not filesystem-tagged.",
        capabilities=(),
        path_args=("path",),
    )
    decision = perm.decide(
        tool_name="plain_tool",
        args={"path": str(outside / "f.txt")},
        tool_def=untagged,
        conversation_id=str(conversation_id),
        mode=PermissionMode.STRICT,
    )

    assert decision.action is GateAction.ALLOW


@pytest.mark.asyncio
async def test_dotdot_traversal_escaping_scope_is_denied(
    scope_service, conversation_id, tmp_path,
):
    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    await scope_service.set_scope(conversation_id, [str(inside)])

    perm = PermissionService(
        scope_provider=scope_service.scope_roots, forbidden_paths=[],
    )
    # Resolves to <tmp>/outside/f.txt — outside the scope (proves resolve-first).
    traversal = str(inside / ".." / "outside" / "f.txt")
    decision = perm.decide(
        tool_name="fs_tool",
        args={"path": traversal},
        tool_def=_fs_tool(),
        conversation_id=str(conversation_id),
        mode=PermissionMode.STRICT,
    )

    assert decision.action is GateAction.DENY
    assert decision.outcome is PermissionOutcome.DENY_SCOPE
