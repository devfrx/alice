"""AL\\CE — kind-dispatching :class:`KnowledgeBackend` composite.

Combines two backends behind the single :class:`KnowledgeBackend`
interface so plugins keep one uniform call site:

* ``note``            → the *note* backend (e.g. Continuum);
* ``memory`` / ``fact`` → the *memory* backend (Qdrant).

This is the seam that lets Continuum own long-form documents while
Alice's Qdrant store keeps owning the agent's short-term/long-term
memory, with no duplication and no plugin changes.
"""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger

from backend.services.knowledge.protocol import (
    BackendHealth,
    KnowledgeBackend,
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeDocPatch,
    KnowledgeHit,
    KnowledgeKind,
)


class CompositeKnowledgeBackend:
    """Route :class:`KnowledgeBackend` operations by ``kind``.

    Args:
        note_backend: Backend handling ``kind == "note"``.
        memory_backend: Backend handling ``kind in {"memory", "fact"}``.
    """

    name: str = "composite"

    def __init__(
        self,
        *,
        note_backend: KnowledgeBackend,
        memory_backend: KnowledgeBackend,
    ) -> None:
        self._note = note_backend
        self._memory = memory_backend
        self._log = logger.bind(component="CompositeKnowledgeBackend")

    def _for(self, kind: KnowledgeKind) -> KnowledgeBackend:
        """Select the backend responsible for ``kind``."""
        if kind == "note":
            return self._note
        if kind in ("memory", "fact"):
            return self._memory
        raise ValueError(f"Unsupported knowledge kind: {kind!r}")

    # ------------------------------------------------------------------
    # Delegation
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        kind: KnowledgeKind,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeHit]:
        return await self._for(kind).search(query, kind=kind, k=k, filters=filters)

    async def get(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        return await self._for(kind).get(doc_id, kind=kind)

    async def create(self, doc: KnowledgeDocCreate) -> KnowledgeDoc:
        return await self._for(doc.kind).create(doc)

    async def update(
        self,
        doc_id: str,
        patch: KnowledgeDocPatch,
        *,
        kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        return await self._for(kind).update(doc_id, patch, kind=kind)

    async def delete(self, doc_id: str, *, kind: KnowledgeKind) -> bool:
        return await self._for(kind).delete(doc_id, kind=kind)

    async def list(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeDoc], int]:
        return await self._for(kind).list(
            kind=kind, filters=filters, limit=limit, offset=offset,
        )

    async def delete_by_filter(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any],
    ) -> int:
        return await self._for(kind).delete_by_filter(kind=kind, filters=filters)

    async def health(self) -> BackendHealth:
        """Aggregate health: ``down`` if either side is down, else worst case."""
        note_health = await self._note.health()
        memory_health = await self._memory.health()
        statuses = {note_health.status, memory_health.status}
        if "down" in statuses:
            status: Literal["up", "degraded", "down"] = "down"
        elif "degraded" in statuses:
            status = "degraded"
        else:
            status = "up"
        detail = (
            f"note={self._note.name}:{note_health.status}, "
            f"memory={self._memory.name}:{memory_health.status}"
        )
        return BackendHealth(status=status, detail=detail)
