"""AL\\CE — REST tests for /api/artifacts."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.db.models import ArtifactKind, Conversation


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
async def test_download_missing_file_returns_404(app, client, tmp_path):
    conv_id = await _create_conversation(app)
    a_id = await _seed_artifact(app, conv_id, tmp_path)
    # Erase the file on disk
    artifact = await app.state.context.artifact_registry.get_artifact(a_id)
    Path(artifact.file_path).unlink()
    resp = await client.get(f"/api/artifacts/{a_id}/download")
    assert resp.status_code == 404
