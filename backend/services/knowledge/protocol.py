"""AL\\CE — :class:`KnowledgeBackend` Protocol and document data models.

This module defines the structural interface every persistent
knowledge backend must satisfy.  In Phase 1 the only implementation is
:class:`~backend.services.knowledge.qdrant_backend.QdrantBackend`,
which wraps the existing ``MemoryService`` + ``NoteService``.  In
Phase 3 a Continuum-backed implementation will be swapped in
configuration without touching plugin code.

The contract is intentionally **kind-dispatched**: each operation
takes a ``kind`` argument so the backend can route to the correct
underlying store (e.g. notes vs. memory) while keeping a single,
uniform call site for plugins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------

KnowledgeKind = Literal["note", "memory", "fact"]
"""Categories of persisted knowledge.

* ``note``: long-form, titled, user-visible Markdown documents.
* ``memory``: short atomic facts (long-term or session scope).
* ``fact``: long-term user fact (``user_fact`` scope on the memory store).
"""


# ---------------------------------------------------------------------------
# Document models
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class KnowledgeDoc:
    """Materialised knowledge document returned by a backend.

    Attributes:
        id: Stable document identifier (UUID string).
        kind: One of :data:`KnowledgeKind`.
        title: Optional human-readable title (always present for notes).
        content: Body text.
        tags: Free-form tags.
        metadata: Backend-specific extras.  For ``note`` documents this
            carries ``folder_path``, ``pinned``, ``wikilinks``.  For
            ``memory``/``fact`` documents this carries ``scope``,
            ``category``, ``source``, ``conversation_id``,
            ``expires_at``, ``embedding_model``.
        created_at: Creation timestamp (UTC, optional).
        updated_at: Last update timestamp (UTC, optional).
    """

    id: str
    kind: KnowledgeKind
    content: str
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class KnowledgeDocCreate:
    """Payload for :meth:`KnowledgeBackend.create`.

    See :class:`KnowledgeDoc` for the meaning of ``metadata`` per kind.
    """

    kind: KnowledgeKind
    content: str
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeDocPatch:
    """Partial update payload for :meth:`KnowledgeBackend.update`.

    Only fields set to a value other than ``None`` are applied.
    """

    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class KnowledgeHit:
    """Search result: a document plus its similarity score."""

    doc: KnowledgeDoc
    score: float


@dataclass(slots=True)
class BackendHealth:
    """Lightweight health snapshot for a knowledge backend.

    A richer ``ServiceHealth`` model lives in ``service_orchestrator``
    (Phase 1 Stream B).  ``KnowledgeBackend`` keeps its own minimal
    structure to avoid coupling.
    """

    status: Literal["up", "degraded", "down"]
    detail: str | None = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class KnowledgeBackend(Protocol):
    """Persistent knowledge store contract used by plugins.

    Implementations dispatch to the right underlying collection based
    on the ``kind`` parameter.  Every I/O operation is async.
    """

    name: str
    """Human-readable backend identifier (e.g. ``"qdrant"``)."""

    async def search(
        self,
        query: str,
        *,
        kind: KnowledgeKind,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeHit]:
        """Semantic / hybrid search restricted to ``kind``.

        Args:
            query: Natural-language query text.
            kind: Document family to search.
            k: Maximum number of hits to return.
            filters: Optional kind-specific filters (e.g.
                ``{"scope": "long_term"}`` for memory,
                ``{"folder": "work", "tags": ["urgent"]}`` for notes).

        Returns:
            Hits sorted by descending similarity score.
        """
        ...

    async def get(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        """Fetch a single document by id.  Returns ``None`` if absent."""
        ...

    async def create(self, doc: KnowledgeDocCreate) -> KnowledgeDoc:
        """Create a new document and return its materialised form."""
        ...

    async def update(
        self,
        doc_id: str,
        patch: KnowledgeDocPatch,
        *,
        kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        """Apply a partial update.  Returns ``None`` if not found."""
        ...

    async def delete(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> bool:
        """Delete a document.  Returns ``True`` on success."""
        ...

    async def list(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeDoc], int]:
        """Paginated listing.  Returns ``(documents, total_count)``."""
        ...

    async def delete_by_filter(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any],
    ) -> int:
        """Bulk delete by filter.  Returns number of removed documents.

        Used e.g. by ``clear_session_memory`` (``filters={"scope":
        "session"}``).
        """
        ...

    async def health(self) -> BackendHealth:
        """Return a lightweight health snapshot for the backend."""
        ...
