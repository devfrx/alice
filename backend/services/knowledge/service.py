"""AL\\CE — Knowledge domain single entry point (Fase 4).

``KnowledgeService`` is the ONLY entry point tools and routes use for
persistent knowledge (notes, memories, facts): it wraps the composable
:class:`KnowledgeBackend` (composite when Continuum is enabled) plus the
raw ``MemoryService`` for the two admin operations the backend protocol
does not model (``stats`` and ``delete_all``).

Stack construction (qdrant backend + optional composite with Continuum)
lives ONLY in :func:`build_knowledge_service`, used both by the lifespan
(``core/app.py``) and by the runtime re-wiring
(``services/knowledge_init.py``) — one implementation (spec §4.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.services.knowledge.composite_backend import (
    CompositeKnowledgeBackend,
)
from backend.services.knowledge.continuum_backend import ContinuumBackend
from backend.services.knowledge.protocol import (
    BackendHealth,
    KnowledgeBackend,
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeDocPatch,
    KnowledgeHit,
    KnowledgeKind,
)
from backend.services.knowledge.qdrant_backend import QdrantBackend

if TYPE_CHECKING:
    from backend.core.protocols import MemoryServiceProtocol
    from backend.services.knowledge.continuum_client import ContinuumClient


class KnowledgeService:
    """Kind-dispatched facade over the composable knowledge backend.

    Args:
        backend: The backend (composite or qdrant-only) to delegate to.
        memory_service: The raw memory service, or ``None`` when memory
            is disabled/uninitialised.  Used ONLY for the admin
            operations not modelled by the backend protocol.
    """

    def __init__(
        self,
        *,
        backend: KnowledgeBackend,
        memory_service: MemoryServiceProtocol | None,
    ) -> None:
        self._backend = backend
        self._memory = memory_service
        self._log = logger.bind(component="KnowledgeService")

    # ------------------------------------------------------------------
    # Availability / introspection
    # ------------------------------------------------------------------

    @property
    def memory_available(self) -> bool:
        """True when memory/fact-kind operations can succeed."""
        return self._memory is not None

    @property
    def backend(self) -> KnowledgeBackend:
        """The wrapped backend — wiring/tests only, never for consumers."""
        return self._backend

    def _require_memory(self) -> MemoryServiceProtocol:
        if self._memory is None:
            raise RuntimeError("memory service is not available")
        return self._memory

    # ------------------------------------------------------------------
    # Backend delegation (kind-dispatched)
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        kind: KnowledgeKind,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[KnowledgeHit]:
        """Semantic/hybrid search restricted to ``kind``."""
        return await self._backend.search(query, kind=kind, k=k, filters=filters)

    async def get(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        """Fetch a single document by id (``None`` if absent)."""
        return await self._backend.get(doc_id, kind=kind)

    async def create(self, doc: KnowledgeDocCreate) -> KnowledgeDoc:
        """Create a document and return its materialised form."""
        return await self._backend.create(doc)

    async def update(
        self,
        doc_id: str,
        patch: KnowledgeDocPatch,
        *,
        kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        """Apply a partial update (``None`` if not found)."""
        return await self._backend.update(doc_id, patch, kind=kind)

    async def delete(self, doc_id: str, *, kind: KnowledgeKind) -> bool:
        """Delete a document; ``True`` on success."""
        return await self._backend.delete(doc_id, kind=kind)

    async def list(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeDoc], int]:
        """Paginated listing: ``(documents, total_count)``."""
        return await self._backend.list(
            kind=kind, filters=filters, limit=limit, offset=offset,
        )

    async def delete_by_filter(
        self, *, kind: KnowledgeKind, filters: dict[str, Any],
    ) -> int:
        """Bulk delete by filter; returns the number of removed docs."""
        return await self._backend.delete_by_filter(kind=kind, filters=filters)

    async def health(self) -> BackendHealth:
        """Health snapshot of the underlying backend."""
        return await self._backend.health()

    # ------------------------------------------------------------------
    # Memory admin (outside the backend protocol)
    # ------------------------------------------------------------------

    async def memory_stats(self) -> dict[str, Any]:
        """Aggregate memory statistics (raises if memory unavailable)."""
        return await self._require_memory().stats()

    async def delete_all_memories(self) -> int:
        """Delete every memory entry (raises if memory unavailable)."""
        return await self._require_memory().delete_all()


def build_knowledge_service(
    *,
    continuum_enabled: bool,
    memory_service: MemoryServiceProtocol | None,
    continuum_client: ContinuumClient | None,
) -> KnowledgeService:
    """Build the knowledge stack — the single wiring implementation.

    Args:
        continuum_enabled: Whether note knowledge is served by Continuum.
        memory_service: Shared memory service (or ``None`` when disabled).
        continuum_client: The ONE shared Continuum client, or ``None``.

    Returns:
        A ready :class:`KnowledgeService` (composite backend when
        Continuum is enabled AND a client is provided, qdrant-only
        otherwise).
    """
    qdrant_backend = QdrantBackend(memory_service=memory_service)
    backend: KnowledgeBackend = qdrant_backend
    if continuum_enabled and continuum_client is not None:
        backend = CompositeKnowledgeBackend(
            note_backend=ContinuumBackend(client=continuum_client),
            memory_backend=qdrant_backend,
        )
    elif continuum_enabled:
        logger.warning(
            "build_knowledge_service: continuum enabled but no client — "
            "notes disabled",
        )
    return KnowledgeService(backend=backend, memory_service=memory_service)
