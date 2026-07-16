"""Tests for the Continuum knowledge backend and the kind-dispatching composite.

The HTTP layer (:class:`ContinuumClient`) is replaced by an ``AsyncMock`` so
these tests exercise the mapping/dispatch logic without a live server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from backend.services.knowledge import (
    CompositeKnowledgeBackend,
    ContinuumBackend,
    KnowledgeDocCreate,
)
from backend.services.knowledge.protocol import BackendHealth, KnowledgeHit

if TYPE_CHECKING:
    from backend.services.knowledge.continuum_client import ContinuumClient

_NOTE = {
    "id": "11111111-1111-1111-1111-111111111111",
    "title": "Test Note",
    "kind": "note",
    "content": "# Hello",
    "tags": ["a", "b"],
    "folderId": "ffffffff-ffff-ffff-ffff-ffffffffffff",
    "locked": False,
    "coverImage": None,
    "createdAt": "2026-01-01T00:00:00Z",
    "updatedAt": "2026-01-02T00:00:00Z",
}


@pytest.fixture
def client() -> AsyncMock:
    """An AsyncMock standing in for :class:`ContinuumClient`."""
    mock = AsyncMock()
    mock.resolve_folder_path.return_value = "work/projects"
    mock.resolve_folder_id.return_value = _NOTE["folderId"]
    return mock


@pytest.fixture
def backend(client: AsyncMock) -> ContinuumBackend:
    return ContinuumBackend(client=client)


# ---------------------------------------------------------------------------
# ContinuumBackend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_maps_note_to_doc(backend: ContinuumBackend, client: AsyncMock):
    client.get_note.return_value = _NOTE
    doc = await backend.get(_NOTE["id"], kind="note")
    assert doc is not None
    assert doc.id == _NOTE["id"]
    assert doc.kind == "note"
    assert doc.title == "Test Note"
    assert doc.tags == ["a", "b"]
    assert doc.metadata["folder_path"] == "work/projects"
    assert doc.metadata["pinned"] is False


@pytest.mark.asyncio
async def test_get_missing_returns_none(backend: ContinuumBackend, client: AsyncMock):
    client.get_note.return_value = None
    assert await backend.get("missing", kind="note") is None


@pytest.mark.asyncio
async def test_create_resolves_folder_and_defaults_title(
    backend: ContinuumBackend, client: AsyncMock,
):
    client.create_note.return_value = _NOTE
    await backend.create(
        KnowledgeDocCreate(
            kind="note",
            content="body",
            title="   ",
            metadata={"folder_path": "work/projects"},
        )
    )
    sent = client.create_note.call_args.args[0]
    assert sent["title"] == "Untitled"  # blank title falls back
    assert sent["folderId"] == _NOTE["folderId"]


@pytest.mark.asyncio
async def test_search_maps_hits(backend: ContinuumBackend, client: AsyncMock):
    client.resolve_folder_id.return_value = None
    client.search_notes.return_value = [
        {"id": "x", "title": "T", "snippet": "snip", "score": 0.9},
    ]
    hits = await backend.search("q", kind="note", k=3)
    assert len(hits) == 1
    assert isinstance(hits[0], KnowledgeHit)
    assert hits[0].doc.content == "snip"
    assert hits[0].score == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_list_filters_and_paginates(
    backend: ContinuumBackend, client: AsyncMock,
):
    notes = [
        {**_NOTE, "id": str(i), "folderId": None, "tags": ["keep"]}
        for i in range(5)
    ]
    client.list_notes.return_value = notes
    client.resolve_folder_path.return_value = ""
    docs, total = await backend.list(
        kind="note", filters={"tags": ["keep"]}, limit=2, offset=1,
    )
    assert total == 5
    assert [d.id for d in docs] == ["1", "2"]


@pytest.mark.asyncio
async def test_non_note_kind_rejected(backend: ContinuumBackend):
    with pytest.raises(ValueError):
        await backend.get("x", kind="memory")


# ---------------------------------------------------------------------------
# CompositeKnowledgeBackend
# ---------------------------------------------------------------------------


@pytest.fixture
def composite() -> tuple[CompositeKnowledgeBackend, AsyncMock, AsyncMock]:
    note_backend = AsyncMock()
    note_backend.name = "continuum"
    memory_backend = AsyncMock()
    memory_backend.name = "qdrant"
    comp = CompositeKnowledgeBackend(
        note_backend=note_backend, memory_backend=memory_backend,
    )
    return comp, note_backend, memory_backend


@pytest.mark.asyncio
async def test_composite_routes_note_to_note_backend(composite):
    comp, note_backend, memory_backend = composite
    await comp.get("x", kind="note")
    note_backend.get.assert_awaited_once()
    memory_backend.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_composite_routes_memory_to_memory_backend(composite):
    comp, note_backend, memory_backend = composite
    await comp.search("q", kind="fact")
    memory_backend.search.assert_awaited_once()
    note_backend.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_composite_health_aggregates_worst_case(composite):
    comp, note_backend, memory_backend = composite
    note_backend.health.return_value = BackendHealth(status="up")
    memory_backend.health.return_value = BackendHealth(status="degraded")
    health = await comp.health()
    assert health.status == "degraded"


# ---------------------------------------------------------------------------
# ContinuumClient folder cache
# ---------------------------------------------------------------------------


def _make_real_client() -> ContinuumClient:
    from backend.services.knowledge.continuum_client import ContinuumClient

    return ContinuumClient(
        base_url="http://localhost:3001",
        api_token=None,
        timeout_s=5.0,
        folder_cache_ttl_s=30.0,
    )


@pytest.mark.asyncio
async def test_folder_cache_is_reused_within_ttl():
    """The folder forest is fetched once and served from cache within TTL."""
    client = _make_real_client()
    client.request = AsyncMock(return_value=[{"id": "f1", "slug": "work"}])

    assert await client.resolve_folder_id("work") == "f1"
    assert await client.resolve_folder_id("work") == "f1"
    client.request.assert_awaited_once_with("GET", "/folders")


@pytest.mark.asyncio
async def test_invalidate_folder_cache_forces_refetch():
    """After invalidation the next resolve refetches the folder tree and
    sees a folder created since the last fetch."""
    client = _make_real_client()
    client.request = AsyncMock(return_value=[{"id": "f1", "slug": "work"}])

    assert await client.resolve_folder_id("work") == "f1"
    # A new folder is created out-of-band; without invalidation the stale
    # cache would resolve it to root (None).
    client.request.return_value = [
        {"id": "f1", "slug": "work"},
        {"id": "f2", "slug": "ideas"},
    ]
    assert await client.resolve_folder_id("ideas") is None  # still cached

    client.invalidate_folder_cache()
    assert await client.resolve_folder_id("ideas") == "f2"

