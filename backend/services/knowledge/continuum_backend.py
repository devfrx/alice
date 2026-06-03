"""AL\\CE — Continuum-backed :class:`KnowledgeBackend` adapter.

Phase 3 implementation of :class:`KnowledgeBackend` for the ``note``
kind. It delegates persistence to a running Continuum server through
:class:`~backend.services.knowledge.continuum_client.ContinuumClient`,
translating between Alice's unified :class:`KnowledgeDoc` shape and
Continuum's REST ``Note`` payloads.

Scope: this backend handles **only** ``kind == "note"``. ``memory`` and
``fact`` kinds remain Qdrant-backed; the two are composed by
:class:`~backend.services.knowledge.composite_backend.\
CompositeKnowledgeBackend`, so this class never has to know about memory.

Mapping notes:
* ``folder_path`` ↔ Continuum ``folderId`` via the client's folder
  resolver (Alice speaks slash-paths; Continuum stores folder UUIDs).
* ``pinned``/``wikilinks`` have no Continuum equivalent on the note row
  and are surfaced as ``False``/``[]`` so the notes plugin's payload
  contract stays stable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from backend.services.knowledge.continuum_client import (
    ContinuumClient,
    ContinuumError,
)
from backend.services.knowledge.protocol import (
    BackendHealth,
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeDocPatch,
    KnowledgeHit,
    KnowledgeKind,
)

# Continuum requires a non-empty note title; used when a caller omits one.
_DEFAULT_TITLE = "Untitled"


def _coerce_iso(value: Any) -> datetime | None:
    """Best-effort ISO-8601 → ``datetime`` conversion (``None`` on failure)."""
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class ContinuumBackend:
    """``note``-only :class:`KnowledgeBackend` over a Continuum server.

    Args:
        client: Configured :class:`ContinuumClient` for the target server.
    """

    name: str = "continuum"

    def __init__(self, *, client: ContinuumClient) -> None:
        self._client = client
        self._log = logger.bind(component="ContinuumBackend")

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    @staticmethod
    def _require_note(kind: KnowledgeKind) -> None:
        if kind != "note":
            raise ValueError(
                f"ContinuumBackend handles only 'note', got {kind!r}"
            )

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------

    async def _note_to_doc(self, note: dict[str, Any]) -> KnowledgeDoc:
        """Adapt a Continuum ``Note`` payload to a :class:`KnowledgeDoc`."""
        folder_path = await self._client.resolve_folder_path(
            note.get("folderId")
        )
        return KnowledgeDoc(
            id=str(note.get("id", "")),
            kind="note",
            title=note.get("title"),
            content=note.get("content", ""),
            tags=list(note.get("tags") or []),
            metadata={
                "folder_path": folder_path,
                "folder_id": note.get("folderId"),
                "kind_slug": note.get("kind"),
                "locked": bool(note.get("locked", False)),
                "cover_image": note.get("coverImage"),
                "pinned": False,
                "wikilinks": [],
            },
            created_at=_coerce_iso(note.get("createdAt")),
            updated_at=_coerce_iso(note.get("updatedAt")),
        )

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        kind: KnowledgeKind,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeHit]:
        """Semantic note search via ``POST /api/notes/search``.

        Hits carry the server-provided snippet as ``content``; call
        :meth:`get` for the full body when needed.
        """
        self._require_note(kind)
        folder_id = await self._client.resolve_folder_id(
            (filters or {}).get("folder")
        )
        hits = await self._client.search_notes(query, limit=k, folder_id=folder_id)
        return [
            KnowledgeHit(
                doc=KnowledgeDoc(
                    id=str(hit.get("id", "")),
                    kind="note",
                    title=hit.get("title"),
                    content=hit.get("snippet", ""),
                    metadata={"snippet": True},
                ),
                score=float(hit.get("score", 0.0)),
            )
            for hit in hits
        ]

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------

    async def get(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        """Fetch a single note; ``None`` if absent."""
        self._require_note(kind)
        note = await self._client.get_note(doc_id)
        return await self._note_to_doc(note) if note is not None else None

    # ------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------

    async def create(self, doc: KnowledgeDocCreate) -> KnowledgeDoc:
        """Create a note from a :class:`KnowledgeDocCreate`."""
        self._require_note(doc.kind)
        meta = doc.metadata or {}
        folder_id = await self._client.resolve_folder_id(meta.get("folder_path"))
        body: dict[str, Any] = {
            "title": (doc.title or "").strip() or _DEFAULT_TITLE,
            "content": doc.content,
            "tags": list(doc.tags) if doc.tags else [],
        }
        if folder_id is not None:
            body["folderId"] = folder_id
        if meta.get("kind_slug"):
            body["kind"] = meta["kind_slug"]
        note = await self._client.create_note(body)
        return await self._note_to_doc(note)

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------

    async def update(
        self,
        doc_id: str,
        patch: KnowledgeDocPatch,
        *,
        kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        """Apply a partial update; ``None`` if the note is missing."""
        self._require_note(kind)
        meta = patch.metadata or {}
        body: dict[str, Any] = {}
        if patch.title is not None:
            body["title"] = patch.title.strip() or _DEFAULT_TITLE
        if patch.content is not None:
            body["content"] = patch.content
        if patch.tags is not None:
            body["tags"] = list(patch.tags)
        if "folder_path" in meta:
            body["folderId"] = await self._client.resolve_folder_id(
                meta.get("folder_path")
            )
        if not body:
            # Nothing to change — return the current state for consistency.
            return await self.get(doc_id, kind="note")
        note = await self._client.update_note(doc_id, body)
        return await self._note_to_doc(note) if note is not None else None

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------

    async def delete(self, doc_id: str, *, kind: KnowledgeKind) -> bool:
        """Delete a note. Returns ``True`` on success."""
        self._require_note(kind)
        return await self._client.delete_note(doc_id)

    # ------------------------------------------------------------------
    # list
    # ------------------------------------------------------------------

    async def list(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeDoc], int]:
        """Paginated listing.

        Continuum's ``GET /api/notes`` returns the full vault (the same
        shape its own web client consumes), so folder/tag filtering and
        pagination are applied client-side here.
        """
        self._require_note(kind)
        filters = filters or {}
        notes = await self._client.list_notes()

        folder = filters.get("folder")
        if folder is not None:
            target_id = await self._client.resolve_folder_id(folder)
            notes = [n for n in notes if n.get("folderId") == target_id]

        tags = filters.get("tags")
        if tags:
            wanted = set(tags)
            notes = [n for n in notes if wanted & set(n.get("tags") or [])]

        total = len(notes)
        window = notes[offset : offset + limit]
        docs = [await self._note_to_doc(n) for n in window]
        return docs, total

    # ------------------------------------------------------------------
    # delete_by_filter
    # ------------------------------------------------------------------

    async def delete_by_filter(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any],
    ) -> int:
        """Bulk delete notes matching ``filters`` (currently ``folder``).

        Implemented as list-then-delete because Continuum exposes
        ``bulk-delete`` by id rather than by predicate.
        """
        self._require_note(kind)
        docs, _ = await self.list(kind="note", filters=filters, limit=10_000)
        deleted = 0
        for doc in docs:
            if await self._client.delete_note(doc.id):
                deleted += 1
        return deleted

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------

    async def health(self) -> BackendHealth:
        """Probe the server by listing folders (a cheap authenticated call)."""
        try:
            await self._client.resolve_folder_id("__health_probe__")
            return BackendHealth(status="up", detail=None)
        except ContinuumError as exc:
            return BackendHealth(status="down", detail=str(exc))
