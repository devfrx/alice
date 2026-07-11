"""AL\\CE — API tests for explicit conversation backup (Fase 2)."""

from __future__ import annotations

import uuid
from pathlib import Path

from httpx import AsyncClient


async def test_backup_endpoint_exports_to_custom_dir(
    client: AsyncClient, tmp_path: Path,
) -> None:
    """POST /backup writes {id}.json files into dest_dir and reports count."""
    # Crea una conversazione via API così esiste nel DB dell'app di test.
    created = await client.post(
        "/api/chat/conversations", json={"id": str(uuid.uuid4())},
    )
    assert created.status_code == 200
    conv_id = created.json()["id"]

    dest = tmp_path / "out"
    resp = await client.post(
        "/api/chat/conversations/backup", json={"dest_dir": str(dest)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["exported"] >= 1
    assert body["path"] == str(dest)
    assert (dest / f"{conv_id}.json").exists()


async def test_backup_endpoint_rejects_relative_dir(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/chat/conversations/backup", json={"dest_dir": "relative/path"},
    )
    assert resp.status_code == 400


async def test_file_path_endpoint_removed(client: AsyncClient) -> None:
    resp = await client.get(
        f"/api/chat/conversations/{uuid.uuid4()}/file-path",
    )
    assert resp.status_code == 404
    # Route-level 404 (unmatched path), NOT the old endpoint's
    # "Conversation not found" — proves the route itself is gone.
    assert resp.json() == {"detail": "Not Found"}
