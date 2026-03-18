"""Tests for the Notes REST API routes (Phase 13)."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.app import create_app

pytestmark = pytest.mark.asyncio


# ── fixtures (override: disable sqlite-vec to avoid import error) ──────────


@pytest.fixture
async def app():
    """App with note-service embeddings disabled (no sqlite_vec needed)."""
    application = create_app(testing=True)
    application.state._config.notes.embedding_enabled = False
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    """Async HTTP client wired to the test application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── helpers ────────────────────────────────────────────────────────────────


def _random_title() -> str:
    return f"test-note-{uuid.uuid4().hex[:8]}"


async def _create_note(
    client: AsyncClient,
    *,
    title: str | None = None,
    content: str = "body",
    folder_path: str = "",
    tags: list[str] | None = None,
) -> dict:
    resp = await client.post(
        "/api/notes",
        json={
            "title": title or _random_title(),
            "content": content,
            "folder_path": folder_path,
            "tags": tags or [],
        },
    )
    assert resp.status_code == 201
    return resp.json()


# ── CRUD flow ──────────────────────────────────────────────────────────────


async def test_create_note(client: AsyncClient):
    data = await _create_note(client, title="Hello", content="World")
    assert data["title"] == "Hello"
    assert data["content"] == "World"
    assert "id" in data


async def test_get_created_note(client: AsyncClient):
    created = await _create_note(client, title="Readable")
    resp = await client.get(f"/api/notes/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Readable"


async def test_update_note(client: AsyncClient):
    created = await _create_note(client, title="Before")
    resp = await client.put(
        f"/api/notes/{created['id']}", json={"title": "After"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "After"


async def test_delete_note(client: AsyncClient):
    created = await _create_note(client, title="Doomed")
    resp = await client.delete(f"/api/notes/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}


async def test_get_deleted_note_returns_404(client: AsyncClient):
    created = await _create_note(client)
    await client.delete(f"/api/notes/{created['id']}")
    resp = await client.get(f"/api/notes/{created['id']}")
    assert resp.status_code == 404


# ── list & filter ──────────────────────────────────────────────────────────


async def test_list_all_notes(client: AsyncClient):
    await _create_note(client, title="L1")
    await _create_note(client, title="L2")
    resp = await client.get("/api/notes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    assert isinstance(body["notes"], list)


async def test_list_filter_by_folder(client: AsyncClient):
    await _create_note(client, title="InDir", folder_path="work")
    await _create_note(client, title="Root", folder_path="")
    resp = await client.get("/api/notes", params={"folder": "work"})
    titles = [n["title"] for n in resp.json()["notes"]]
    assert "InDir" in titles
    assert "Root" not in titles


async def test_list_filter_by_tags(client: AsyncClient):
    await _create_note(client, title="Tagged", tags=["python"])
    await _create_note(client, title="NoTag", tags=[])
    resp = await client.get("/api/notes", params={"tags": "python"})
    titles = [n["title"] for n in resp.json()["notes"]]
    assert "Tagged" in titles


async def test_list_pinned_only(client: AsyncClient):
    created = await _create_note(client, title="PinMe")
    await client.put(
        f"/api/notes/{created['id']}", json={"pinned": True},
    )
    resp = await client.get("/api/notes", params={"pinned": True})
    titles = [n["title"] for n in resp.json()["notes"]]
    assert "PinMe" in titles


# ── search ─────────────────────────────────────────────────────────────────


async def test_search_notes(client: AsyncClient):
    await _create_note(client, title="Quantum", content="entanglement")
    resp = await client.post(
        "/api/notes/search", json={"query": "Quantum"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["results"], list)


async def test_search_empty_query_returns_422(client: AsyncClient):
    resp = await client.post("/api/notes/search", json={"query": ""})
    assert resp.status_code == 422


# ── folders ────────────────────────────────────────────────────────────────


async def test_list_folders(client: AsyncClient):
    await _create_note(client, folder_path="projects")
    resp = await client.get("/api/notes/folders")
    assert resp.status_code == 200


async def test_delete_folder_move(client: AsyncClient):
    await _create_note(client, title="Mv", folder_path="old-dir")
    resp = await client.post(
        "/api/notes/folders/delete",
        json={"folder_path": "old-dir", "mode": "move"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "move"
    assert "affected" in body


async def test_delete_folder_delete(client: AsyncClient):
    await _create_note(client, title="Rm", folder_path="trash-dir")
    resp = await client.post(
        "/api/notes/folders/delete",
        json={"folder_path": "trash-dir", "mode": "delete"},
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "delete"


# ── edge cases ─────────────────────────────────────────────────────────────


_FAKE_UUID = str(uuid.uuid4())


@pytest.mark.parametrize(
    "method,url",
    [
        ("GET", f"/api/notes/{_FAKE_UUID}"),
        ("PUT", f"/api/notes/{_FAKE_UUID}"),
        ("DELETE", f"/api/notes/{_FAKE_UUID}"),
    ],
    ids=["get", "update", "delete"],
)
async def test_nonexistent_note_returns_404(
    client: AsyncClient, method: str, url: str,
):
    kwargs: dict = {}
    if method == "PUT":
        kwargs["json"] = {"title": "Nope"}
    resp = await client.request(method, url, **kwargs)
    assert resp.status_code == 404


async def test_create_note_empty_title_returns_422(client: AsyncClient):
    resp = await client.post(
        "/api/notes", json={"title": "", "content": "x"},
    )
    assert resp.status_code == 422


async def test_invalid_uuid_returns_400(client: AsyncClient):
    resp = await client.get("/api/notes/not-a-uuid")
    assert resp.status_code == 400


# ── event emission (smoke) ─────────────────────────────────────────────────


async def test_crud_with_events_does_not_crash(client: AsyncClient):
    """Create, update, delete cycle succeeds even with event_bus wired."""
    n = await _create_note(client, title="EventTest")
    nid = n["id"]

    resp = await client.put(f"/api/notes/{nid}", json={"title": "Edited"})
    assert resp.status_code == 200

    resp = await client.delete(f"/api/notes/{nid}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


# ── validation / security ─────────────────────────────────────────────────


async def test_create_note_path_traversal_rejected(client) -> None:
    """folder_path containing '..' must be rejected (422)."""
    resp = await client.post(
        "/api/notes",
        json={"title": "x", "content": "x", "folder_path": "../etc"},
    )
    assert resp.status_code == 422


async def test_create_note_absolute_path_rejected(client) -> None:
    """folder_path starting with '/' must be rejected (422)."""
    resp = await client.post(
        "/api/notes",
        json={"title": "x", "content": "x", "folder_path": "/etc"},
    )
    assert resp.status_code == 422


async def test_update_note_path_traversal_rejected(client) -> None:
    """folder_path containing '..' in update must be rejected (422)."""
    note = await _create_note(client)
    resp = await client.put(
        f"/api/notes/{note['id']}",
        json={"folder_path": "../../secrets"},
    )
    assert resp.status_code == 422


async def test_create_note_tags_whitespace_stripped(client) -> None:
    """Tags with leading/trailing whitespace should be stripped; empty strings removed."""
    note = await _create_note(client, tags=["  python  ", "", "  AI  "])
    # Empty string should be filtered out, whitespace trimmed
    assert "python" in note["tags"]
    assert "AI" in note["tags"]
    assert "" not in note["tags"]
    assert len(note["tags"]) == 2
