"""AL\\CE — Tests for JSON-kind artifacts (blob store + registry methods)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import ArtifactKind, Conversation
from backend.services.artifacts import ArtifactRegistry
from backend.services.artifacts.blob_store import ArtifactBlobStore


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
async def conversation_id(session_factory) -> uuid.UUID:
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
def registry(session_factory, captured_events, tmp_path) -> ArtifactRegistry:
    async def _cb(event: dict[str, Any]) -> None:
        captured_events.append(event)

    reg = ArtifactRegistry(
        session_factory=session_factory,
        blob_store=ArtifactBlobStore(tmp_path),
    )
    reg.set_event_callback(_cb)
    return reg


_SNAPSHOT = {
    "store": {
        "shape:s1": {"typeName": "shape", "id": "shape:s1"},
        "shape:s2": {"typeName": "shape", "id": "shape:s2"},
        "page:p1": {"typeName": "page", "id": "page:p1"},
    },
}


async def test_create_json_artifact_writes_blob_row_event(
    registry, captured_events, conversation_id, tmp_path,
) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART,
        title="My chart",
        content={
            "chart_id": "x",
            "echarts_option": {"series": []},
            "updated_at": "2026-06-12T00:00:00+00:00",
        },
        conversation_id=conversation_id,
        metadata={"chart_type": "bar"},
    )
    assert artifact.kind is ArtifactKind.CHART
    assert artifact.mime == "application/json"
    assert artifact.size_bytes > 0
    blob = tmp_path / "chart" / f"{artifact.id}.json"
    assert blob.exists()
    assert captured_events[-1]["type"] == "artifact.created"
    assert captured_events[-1]["kind"] == "chart"


async def test_whiteboard_metadata_hook_counts_shapes(registry) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD,
        title="Board",
        content={"board_id": "b", "snapshot": _SNAPSHOT, "updated_at": "2026-06-12T00:00:00+00:00"},
    )
    assert artifact.artifact_metadata["shape_count"] == 2


async def test_read_json_content_roundtrip_and_missing(registry) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART,
        title="c",
        content={"chart_id": "c", "echarts_option": {"series": [1]}},
    )
    result = await registry.read_json_content(artifact.id)
    assert result is not None
    row, content = result
    assert row.id == artifact.id
    assert content["echarts_option"] == {"series": [1]}
    assert await registry.read_json_content(uuid.uuid4()) is None


async def test_update_json_artifact_merges_and_bumps(
    registry, captured_events,
) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD,
        title="Board",
        content={
            "board_id": "b",
            "snapshot": {"store": {}},
            "updated_at": "2026-06-12T00:00:00+00:00",
        },
    )
    assert artifact.artifact_metadata["shape_count"] == 0
    updated = await registry.update_json_artifact(
        artifact.id, content_patch={"snapshot": _SNAPSHOT},
    )
    assert updated is not None
    assert updated.artifact_metadata["shape_count"] == 2
    assert updated.updated_at >= artifact.updated_at
    _row, content = await registry.read_json_content(artifact.id)
    assert content["snapshot"] == _SNAPSHOT
    assert content["updated_at"] != "2026-06-12T00:00:00+00:00"
    assert captured_events[-1] == {
        "type": "artifact.updated", "artifact_id": str(artifact.id),
    }


async def test_update_json_artifact_title_only(registry) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="old",
        content={"chart_id": "c", "echarts_option": {}},
    )
    updated = await registry.update_json_artifact(artifact.id, title="new")
    assert updated is not None and updated.title == "new"


async def test_count_artifacts_by_kind(registry, conversation_id) -> None:
    for i in range(3):
        await registry.create_json_artifact(
            kind=ArtifactKind.CHART, title=f"c{i}",
            content={"chart_id": str(i), "echarts_option": {}},
            conversation_id=conversation_id,
        )
    await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD, title="b",
        content={"board_id": "b", "snapshot": {"store": {}}},
    )
    assert await registry.count_artifacts(kind=ArtifactKind.CHART) == 3
    assert await registry.count_artifacts(kind=ArtifactKind.WHITEBOARD) == 1
    assert await registry.count_artifacts() == 4
    assert await registry.count_artifacts(
        kind=ArtifactKind.CHART, conversation_id=conversation_id,
    ) == 3


async def test_delete_artifact_emits_deleted_event(
    registry, captured_events, tmp_path,
) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="c",
        content={"chart_id": "c", "echarts_option": {}},
    )
    blob = tmp_path / "chart" / f"{artifact.id}.json"
    assert blob.exists()
    assert await registry.delete_artifact(artifact.id, delete_file=True)
    assert not blob.exists()
    assert captured_events[-1] == {
        "type": "artifact.deleted", "artifact_id": str(artifact.id),
    }


async def test_set_pinned_emits_updated_event(registry, captured_events) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="c",
        content={"chart_id": "c", "echarts_option": {}},
    )
    await registry.set_pinned(artifact.id, True)
    assert captured_events[-1] == {
        "type": "artifact.updated", "artifact_id": str(artifact.id),
    }


async def test_delete_for_conversation_detaches_pinned(
    registry, conversation_id, tmp_path,
) -> None:
    pinned = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD, title="keep",
        content={"board_id": "k", "snapshot": {"store": {}}},
        conversation_id=conversation_id,
    )
    await registry.set_pinned(pinned.id, True)
    gone = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="gone",
        content={"chart_id": "g", "echarts_option": {}},
        conversation_id=conversation_id,
    )
    gone_blob = tmp_path / "chart" / f"{gone.id}.json"
    deleted = await registry.delete_for_conversation(conversation_id)
    assert deleted == 1
    assert not gone_blob.exists()
    survivor = await registry.get_artifact(pinned.id)
    assert survivor is not None and survivor.conversation_id is None
    assert await registry.get_artifact(gone.id) is None


async def test_delete_all_wipes_rows_and_files(registry, tmp_path) -> None:
    a1 = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="a",
        content={"chart_id": "a", "echarts_option": {}},
    )
    a2 = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD, title="b",
        content={"board_id": "b", "snapshot": {"store": {}}},
    )
    count = await registry.delete_all()
    assert count == 2
    assert await registry.count_artifacts() == 0
    assert not (tmp_path / "chart" / f"{a1.id}.json").exists()
    assert not (tmp_path / "whiteboard" / f"{a2.id}.json").exists()


async def test_update_json_artifact_patch_and_title_together(registry) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="old",
        content={"chart_id": "c", "echarts_option": {"series": []}},
    )
    updated = await registry.update_json_artifact(
        artifact.id,
        content_patch={"echarts_option": {"series": [1]}},
        title="new",
    )
    assert updated is not None and updated.title == "new"
    _row, content = await registry.read_json_content(artifact.id)
    assert content["echarts_option"] == {"series": [1]}


async def test_unreadable_blob_returns_none(registry, tmp_path) -> None:
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.CHART, title="c",
        content={"chart_id": "c", "echarts_option": {}},
    )
    blob = tmp_path / "chart" / f"{artifact.id}.json"
    blob.write_text("not json", encoding="utf-8")
    assert await registry.read_json_content(artifact.id) is None
    assert await registry.update_json_artifact(
        artifact.id, content_patch={"x": 1},
    ) is None
