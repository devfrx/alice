"""AL\\CE — REST tests for /api/artifacts."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from backend.db.models import ArtifactKind, Conversation
from backend.services.artifacts.blob_store import ArtifactBlobStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_conversation(app) -> uuid.UUID:
    """Insert a Conversation row directly via the app's session factory."""
    ctx = app.state.context
    async with ctx.db() as session:
        conv = Conversation(title="t")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv.id


async def _seed_artifact(
    app, conv_id: uuid.UUID, tmp_path: Path, *, description: str = "thing",
) -> str:
    """Use the registry to create an artifact; return its id (str)."""
    file_path = tmp_path / f"{uuid.uuid4().hex}.glb"
    file_path.write_bytes(b"GLB-DATA")
    registry = app.state.context.artifact_registry
    artifact = await registry.register_from_tool_result(
        conversation_id=conv_id,
        message_id=None,
        tool_call_id=None,
        tool_name="cad_generate",
        payload={
            "model_name": "m",
            "format": "glb",
            "size_bytes": len(b"GLB-DATA"),
            "file_path": str(file_path),
            "description": description,
        },
        content_type="application/json",
    )
    assert artifact is not None
    return str(artifact.id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_empty(client):
    resp = await client.get("/api/artifacts")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_get_unknown_returns_404(client):
    resp = await client.get(f"/api/artifacts/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pin_unknown_returns_404(client):
    resp = await client.patch(
        f"/api/artifacts/{uuid.uuid4()}/pin", json={"pinned": True},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_full_pin_and_filter_flow(app, client, tmp_path):
    conv_id = await _create_conversation(app)
    a_id = await _seed_artifact(app, conv_id, tmp_path, description="alpha")
    b_id = await _seed_artifact(app, conv_id, tmp_path, description="beta")

    # list returns both
    resp = await client.get(
        "/api/artifacts", params={"conversation_id": str(conv_id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {item["id"] for item in body["items"]} == {a_id, b_id}
    for item in body["items"]:
        assert item["download_url"] == f"/api/artifacts/{item['id']}/download"
        assert item["kind"] == ArtifactKind.CAD_3D_TEXT.value

    # pin one
    resp = await client.patch(
        f"/api/artifacts/{a_id}/pin", json={"pinned": True},
    )
    assert resp.status_code == 200
    assert resp.json()["pinned"] is True

    # filter pinned only
    resp = await client.get("/api/artifacts", params={"pinned": "true"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == a_id


@pytest.mark.asyncio
async def test_delete_returns_204(app, client, tmp_path):
    conv_id = await _create_conversation(app)
    a_id = await _seed_artifact(app, conv_id, tmp_path)
    resp = await client.delete(f"/api/artifacts/{a_id}")
    assert resp.status_code == 204
    # subsequent GET → 404
    resp = await client.get(f"/api/artifacts/{a_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_serves_binary(app, client, tmp_path):
    conv_id = await _create_conversation(app)
    a_id = await _seed_artifact(app, conv_id, tmp_path, description="binmodel")
    resp = await client.get(f"/api/artifacts/{a_id}/download")
    assert resp.status_code == 200
    assert resp.content == b"GLB-DATA"
    assert resp.headers["content-type"] == "model/gltf-binary"
    cd = resp.headers.get("content-disposition", "")
    assert "binmodel.glb" in cd


@pytest.mark.asyncio
async def test_download_serves_image_kind(app: Any, client: Any, tmp_path: Path) -> None:
    """T16: un artifact IMAGE creato dal registry è scaricabile senza modifiche
    alla route (200, MIME dell'artifact, byte identici al blob)."""
    import base64

    conv_id = await _create_conversation(app)
    registry = app.state.context.artifact_registry
    registry._blob_store = ArtifactBlobStore(tmp_path)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    artifact = await registry.create_image_artifact(
        conversation_id=conv_id,
        message_id=None,
        tool_call_id="tc-img",
        tool_name="browser_screenshot",
        mime="image/png",
        base64_data=base64.b64encode(png).decode("ascii"),
    )
    assert artifact is not None

    resp = await client.get(f"/api/artifacts/{artifact.id}/download")
    assert resp.status_code == 200
    assert resp.content == png
    assert resp.headers["content-type"] == "image/png"
    assert ".png" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_download_missing_file_returns_404(app, client, tmp_path):
    conv_id = await _create_conversation(app)
    a_id = await _seed_artifact(app, conv_id, tmp_path)
    # Erase the file on disk
    artifact = await app.state.context.artifact_registry.get_artifact(a_id)
    Path(artifact.file_path).unlink()
    resp = await client.get(f"/api/artifacts/{a_id}/download")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_content_roundtrip(app, client, tmp_path):
    """GET/PATCH /content: blob JSON servito e aggiornato via merge."""
    registry = app.state.context.artifact_registry
    registry._blob_store = ArtifactBlobStore(tmp_path)
    artifact = await registry.create_json_artifact(
        kind=ArtifactKind.WHITEBOARD,
        title="b",
        content={
            "board_id": "b1",
            "snapshot": {"store": {}},
            "updated_at": "2026-06-12T00:00:00+00:00",
        },
    )

    r = await client.get(f"/api/artifacts/{artifact.id}/content")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "whiteboard"
    assert body["content"]["board_id"] == "b1"

    r2 = await client.patch(
        f"/api/artifacts/{artifact.id}/content",
        json={"content": {"snapshot": {"store": {"shape:s1": {"typeName": "shape"}}}}},
    )
    assert r2.status_code == 200
    assert r2.json()["artifact_id"] == str(artifact.id)

    r2b = await client.get(f"/api/artifacts/{artifact.id}/content")
    assert r2b.status_code == 200
    assert "shape:s1" in r2b.json()["content"]["snapshot"]["store"]

    r3 = await client.get(f"/api/artifacts/{artifact.id}")
    assert r3.json()["artifact_metadata"]["shape_count"] == 1


@pytest.mark.asyncio
async def test_content_404_for_binary_artifact(app, client, tmp_path):
    """GET /content su un artifact binario (CAD) → 404."""
    registry = app.state.context.artifact_registry
    glb = tmp_path / "m.glb"
    glb.write_bytes(b"glTF")
    artifact = await registry.register_from_tool_result(
        conversation_id=uuid.uuid4(),
        message_id=None,
        tool_call_id="tc1",
        tool_name="cad_generate",
        payload={"file_path": str(glb), "model_name": "m", "description": "d"},
        content_type=None,
    )
    assert artifact is not None
    r = await client.get(f"/api/artifacts/{artifact.id}/content")
    assert r.status_code == 404

    r2 = await client.patch(
        f"/api/artifacts/{artifact.id}/content",
        json={"content": {"x": 1}},
    )
    assert r2.status_code == 404
