"""AL\\CE — Tests for the artifact registry & parsers."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import Artifact, ArtifactKind, Conversation
from backend.services.artifacts import ArtifactRegistry, parse_tool_payload
from backend.services.artifacts.parsers import (
    _parse_cad_generate,
    _parse_cad_generate_from_image,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory():
    """Build an in-memory SQLite + session factory and create all tables."""
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
    """Insert a Conversation row and return its id."""
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
def registry(session_factory, captured_events):
    async def _cb(event: dict[str, Any]) -> None:
        captured_events.append(event)

    reg = ArtifactRegistry(session_factory=session_factory)
    reg.set_event_callback(_cb)
    return reg


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parser_cad_generate_returns_descriptor():
    desc = _parse_cad_generate(
        {
            "model_name": "robot_dog",
            "format": "glb",
            "size_bytes": 12345,
            "file_path": "/tmp/robot_dog.glb",
            "export_url": "/api/cad/models/robot_dog",
            "description": "A small robot dog with red eyes.",
        },
        None,
    )
    assert desc is not None
    assert desc.kind == ArtifactKind.CAD_3D_TEXT
    assert desc.title == "A small robot dog with red eyes."
    assert desc.mime == "model/gltf-binary"
    assert desc.size_bytes == 12345
    assert desc.metadata["model_name"] == "robot_dog"


def test_parser_cad_generate_from_image_includes_source():
    desc = _parse_cad_generate_from_image(
        {
            "model_name": "chair_v1",
            "format": "glb",
            "size_bytes": 99,
            "file_path": "/tmp/chair.glb",
            "source_image": "/uploads/foo.jpg",
            "pipeline_type": "1024_cascade",
            "seed": 42,
        },
        None,
    )
    assert desc is not None
    assert desc.kind == ArtifactKind.CAD_3D_IMAGE
    assert desc.metadata["source_image"] == "/uploads/foo.jpg"
    assert desc.metadata["pipeline_type"] == "1024_cascade"


def test_parser_unknown_tool_returns_none():
    assert parse_tool_payload("does_not_exist", {"foo": 1}, None) is None


def test_parser_malformed_payload_returns_none():
    # missing required file_path
    assert parse_tool_payload("cad_generate", {"description": "x"}, None) is None


# ---------------------------------------------------------------------------
# register_from_tool_result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_creates_row_and_emits_event(
    registry, captured_events, conversation_id, tmp_path,
):
    file_path = tmp_path / "x.glb"
    file_path.write_bytes(b"GLB")
    artifact = await registry.register_from_tool_result(
        conversation_id=conversation_id,
        message_id=None,
        tool_call_id="call_123",
        tool_name="cad_generate",
        payload={
            "model_name": "x",
            "format": "glb",
            "size_bytes": 3,
            "file_path": str(file_path),
            "description": "tiny cube",
        },
        content_type="application/json",
    )
    assert artifact is not None
    assert artifact.kind == ArtifactKind.CAD_3D_TEXT
    assert artifact.tool_call_id == "call_123"
    assert artifact.size_bytes == 3
    assert captured_events == [
        {
            "type": "artifact.created",
            "artifact_id": str(artifact.id),
            "kind": "cad_3d_text",
            "conversation_id": str(conversation_id),
            "title": "tiny cube",
        }
    ]


@pytest.mark.asyncio
async def test_register_unknown_tool_returns_none_and_no_event(
    registry, captured_events, conversation_id,
):
    out = await registry.register_from_tool_result(
        conversation_id=conversation_id,
        message_id=None,
        tool_call_id=None,
        tool_name="nope",
        payload={"file_path": "x"},
        content_type=None,
    )
    assert out is None
    assert captured_events == []


# ---------------------------------------------------------------------------
# pin / list / delete
# ---------------------------------------------------------------------------


async def _seed_artifact(
    registry: ArtifactRegistry, conv_id: uuid.UUID, file_path: Path,
    description: str = "thing",
) -> Artifact:
    file_path.write_bytes(b"data")
    return await registry.register_from_tool_result(  # type: ignore[return-value]
        conversation_id=conv_id,
        message_id=None,
        tool_call_id=None,
        tool_name="cad_generate",
        payload={
            "model_name": "m",
            "format": "glb",
            "size_bytes": 4,
            "file_path": str(file_path),
            "description": description,
        },
        content_type="application/json",
    )


@pytest.mark.asyncio
async def test_set_pinned_updates_flag_and_timestamp(
    registry, conversation_id, tmp_path,
):
    a = await _seed_artifact(registry, conversation_id, tmp_path / "a.glb")
    original_updated = a.updated_at
    pinned = await registry.set_pinned(a.id, True)
    assert pinned is not None
    assert pinned.pinned is True
    assert pinned.updated_at >= original_updated


@pytest.mark.asyncio
async def test_set_pinned_unknown_returns_none(registry):
    out = await registry.set_pinned(uuid.uuid4(), True)
    assert out is None


@pytest.mark.asyncio
async def test_list_artifacts_filters(registry, conversation_id, tmp_path):
    a1 = await _seed_artifact(registry, conversation_id, tmp_path / "1.glb", "one")
    a2 = await _seed_artifact(registry, conversation_id, tmp_path / "2.glb", "two")
    await registry.set_pinned(a1.id, True)

    items, total = await registry.list_artifacts(
        conversation_id=conversation_id,
    )
    assert total == 2
    assert {x.id for x in items} == {a1.id, a2.id}

    pinned_items, total_pinned = await registry.list_artifacts(pinned_only=True)
    assert total_pinned == 1
    assert pinned_items[0].id == a1.id

    by_kind, _ = await registry.list_artifacts(kind=ArtifactKind.CAD_3D_TEXT)
    assert len(by_kind) == 2

    by_other_kind, _ = await registry.list_artifacts(kind=ArtifactKind.CAD_3D_IMAGE)
    assert by_other_kind == []


@pytest.mark.asyncio
async def test_delete_artifact_keeps_file_by_default(
    registry, conversation_id, tmp_path,
):
    a = await _seed_artifact(registry, conversation_id, tmp_path / "k.glb")
    file_path = tmp_path / "k.glb"
    assert file_path.exists()
    assert await registry.delete_artifact(a.id) is True
    assert file_path.exists()  # not removed
    assert await registry.get_artifact(a.id) is None


@pytest.mark.asyncio
async def test_delete_artifact_with_delete_file(
    registry, conversation_id, tmp_path,
):
    a = await _seed_artifact(registry, conversation_id, tmp_path / "z.glb")
    file_path = tmp_path / "z.glb"
    assert file_path.exists()
    assert await registry.delete_artifact(a.id, delete_file=True) is True
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_delete_unknown_returns_false(registry):
    assert await registry.delete_artifact(uuid.uuid4()) is False
