"""AL\\CE — Tests for the whiteboard plugin on the unified registry."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.config import WhiteboardConfig
from backend.core.plugin_models import ExecutionContext
from backend.db.models import ArtifactKind, Conversation
from backend.plugins.whiteboard.plugin import WhiteboardPlugin
from backend.services.artifacts import ArtifactRegistry
from backend.services.artifacts.blob_store import ArtifactBlobStore


@pytest.fixture
async def session_factory():
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
async def conversation_id(session_factory) -> uuid.UUID:
    async with session_factory() as session:
        conv = Conversation(title="Conv title")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv.id


@pytest.fixture
def registry(session_factory, tmp_path) -> ArtifactRegistry:
    return ArtifactRegistry(
        session_factory=session_factory,
        blob_store=ArtifactBlobStore(tmp_path),
    )


class _StubConfig:
    def __init__(self) -> None:
        self.whiteboard = WhiteboardConfig(enabled=True)


class _StubCtx:
    def __init__(self, registry: ArtifactRegistry) -> None:
        self.artifact_registry = registry
        self.config = _StubConfig()


@pytest.fixture
def plugin(registry) -> WhiteboardPlugin:
    p = WhiteboardPlugin()
    p._ctx = _StubCtx(registry)  # bypass full AppContext wiring
    return p


def _exec_ctx(conversation_id: uuid.UUID | None = None) -> ExecutionContext:
    return ExecutionContext(
        session_id="s",
        conversation_id=str(conversation_id) if conversation_id else "",
        execution_id="e",
    )


_SHAPES = [
    {"type": "geo", "id": "n1", "text": "Start"},
    {"type": "geo", "id": "n2", "text": "End", "x": 250},
]


async def test_create_whiteboard_counts_shapes(
    plugin, registry, conversation_id,
) -> None:
    result = await plugin.execute_tool(
        "create", {"title": "B", "shapes": _SHAPES}, _exec_ctx(conversation_id),
    )
    assert result.success, result.content
    payload = json.loads(result.content)
    aid = payload["board_id"]
    assert payload["board_url"] == f"/api/artifacts/{aid}/content"
    artifact = await registry.get_artifact(aid)
    assert artifact is not None
    assert artifact.kind is ArtifactKind.WHITEBOARD
    assert artifact.conversation_id == conversation_id
    assert artifact.artifact_metadata["shape_count"] == 2


async def test_get_whiteboard_summarises_shapes(plugin, conversation_id) -> None:
    created = await plugin.execute_tool(
        "create", {"title": "B", "shapes": _SHAPES}, _exec_ctx(conversation_id),
    )
    aid = json.loads(created.content)["board_id"]
    res = await plugin.execute_tool("get", {"board_id": aid}, _exec_ctx())
    assert res.success
    data = json.loads(res.content)
    assert data["board_id"] == aid
    assert data["shape_count"] == 2


async def test_add_shapes_merges_snapshot(plugin, registry, conversation_id) -> None:
    created = await plugin.execute_tool(
        "create", {"title": "B", "shapes": _SHAPES}, _exec_ctx(conversation_id),
    )
    aid = json.loads(created.content)["board_id"]
    res = await plugin.execute_tool(
        "add_shapes",
        {"board_id": aid, "shapes": [{"type": "note", "id": "n3", "text": "Nota"}]},
        _exec_ctx(),
    )
    assert res.success, res.content
    artifact = await registry.get_artifact(aid)
    assert artifact.artifact_metadata["shape_count"] == 3


async def test_list_scoped_to_current_conversation(
    plugin, conversation_id,
) -> None:
    await plugin.execute_tool(
        "create", {"title": "Mine"}, _exec_ctx(conversation_id),
    )
    await plugin.execute_tool("create", {"title": "Orphan"}, _exec_ctx())
    res = await plugin.execute_tool("list", {}, _exec_ctx(conversation_id))
    assert res.success
    payload = json.loads(res.content)
    assert payload["total"] == 1
    assert payload["boards"][0]["title"] == "Mine"


async def test_delete_whiteboard_removes_row_and_blob(
    plugin, registry, tmp_path,
) -> None:
    created = await plugin.execute_tool("create", {"title": "B"}, _exec_ctx())
    aid = json.loads(created.content)["board_id"]
    res = await plugin.execute_tool("delete", {"board_id": aid}, _exec_ctx())
    assert res.success
    assert await registry.get_artifact(aid) is None
    assert not (tmp_path / "whiteboard" / f"{aid}.json").exists()


async def test_update_replaces_content_and_title(
    plugin, registry, conversation_id,
) -> None:
    created = await plugin.execute_tool(
        "create", {"title": "B", "shapes": _SHAPES}, _exec_ctx(conversation_id),
    )
    aid = json.loads(created.content)["board_id"]
    res = await plugin.execute_tool(
        "update",
        {
            "board_id": aid,
            "shapes": [{"type": "geo", "id": "x1", "text": "Only"}],
            "title": "B2",
        },
        _exec_ctx(),
    )
    assert res.success, res.error_message
    artifact = await registry.get_artifact(aid)
    assert artifact is not None
    assert artifact.title == "B2"
    assert artifact.artifact_metadata["shape_count"] == 1


async def test_missing_board_is_clean_error(plugin) -> None:
    missing = str(uuid.uuid4())
    for tool, args in (
        ("get", {"board_id": missing}),
        ("add_shapes", {"board_id": missing, "shapes": [{"type": "note", "text": "n"}]}),
        ("update", {"board_id": missing, "shapes": [{"type": "note", "text": "n"}]}),
        ("delete", {"board_id": missing}),
    ):
        res = await plugin.execute_tool(tool, args, _exec_ctx())
        assert not res.success
        assert "non trovata" in (res.error_message or "")


async def test_disabled_plugin_exposes_no_tools_and_errors(registry) -> None:
    p = WhiteboardPlugin()
    stub = _StubCtx(registry)
    stub.config.whiteboard = WhiteboardConfig(enabled=False)
    p._ctx = stub
    assert p.get_tools() == []
    res = await p.execute_tool("create", {"title": "X"}, _exec_ctx())
    assert not res.success


async def test_unknown_tool_returns_error(plugin) -> None:
    res = await plugin.execute_tool("nope", {}, _exec_ctx())
    assert not res.success


async def test_create_respects_max_boards(plugin) -> None:
    plugin.ctx.config.whiteboard.max_boards = 1
    first = await plugin.execute_tool("create", {"title": "B1"}, _exec_ctx())
    assert first.success
    second = await plugin.execute_tool("create", {"title": "B2"}, _exec_ctx())
    assert not second.success
    assert "Limite massimo" in (second.error_message or "")
