"""AL\\CE — Qdrant-backed :class:`KnowledgeBackend` adapter.

Phase 1 implementation of :class:`KnowledgeBackend` that **wraps**
the existing :class:`~backend.services.memory_service.MemoryService`
without duplicating any storage logic. ``note`` knowledge is served by
Continuum (see :class:`~backend.services.knowledge.continuum_backend.\
ContinuumBackend`), so this adapter only handles ``memory``/``fact``.

Routing rule (see ``docs/architecture/phase1-alice-finalization.md``
section 6):

============== =========================== ========================
``kind``       Underlying service           Qdrant collection
============== =========================== ========================
``memory``     ``MemoryService`` (long_term/session) ``COLLECTION_MEMORY``
``fact``       ``MemoryService`` (user_fact)         ``COLLECTION_MEMORY``
============== =========================== ========================

The adapter is intentionally thin: no business logic, no extra
caching, no retries.  Its only job is to translate between the
unified :class:`KnowledgeDoc` shape and the existing service API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.services.knowledge.protocol import (
    BackendHealth,
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeDocPatch,
    KnowledgeHit,
    KnowledgeKind,
)

if TYPE_CHECKING:
    from backend.core.protocols import MemoryServiceProtocol
    from backend.services.memory_service import MemoryEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MEMORY_KINDS: frozenset[str] = frozenset({"memory", "fact"})

_FACT_SCOPE: str = "user_fact"
_DEFAULT_MEMORY_SCOPE: str = "long_term"


# ---------------------------------------------------------------------------
# QdrantBackend
# ---------------------------------------------------------------------------

class QdrantBackend:
    """Thin :class:`KnowledgeBackend` wrapper over the Memory service.

    Args:
        memory_service: Existing :class:`MemoryService` instance, or
            ``None`` if memory is disabled in the current configuration.

    The service may legitimately be absent (the corresponding plugin
    will then surface a "service not available" error to callers).  The
    backend itself never raises on construction.
    """

    name: str = "qdrant"

    def __init__(
        self,
        *,
        memory_service: MemoryServiceProtocol | None,
    ) -> None:
        self._memory = memory_service
        self._log = logger.bind(component="QdrantBackend")

    # ------------------------------------------------------------------
    # Public dispatch helpers
    # ------------------------------------------------------------------

    def _require_memory(self) -> MemoryServiceProtocol:
        if self._memory is None:
            raise RuntimeError("memory_service is not available")
        return self._memory

    @staticmethod
    def _is_memory_kind(kind: str) -> bool:
        return kind in _MEMORY_KINDS

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
        """Dispatch a semantic search to ``MemoryService.search``."""
        if self._is_memory_kind(kind):
            mem = self._require_memory()
            mem_filter = self._build_memory_filter(kind, filters)
            results = await mem.search(query, k=k, filter=mem_filter)
            return [
                KnowledgeHit(
                    doc=_memory_entry_to_doc(r["entry"]),
                    score=float(r.get("score", 0.0)),
                )
                for r in results
            ]

        raise ValueError(f"Unsupported knowledge kind: {kind!r}")

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------

    async def get(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> KnowledgeDoc | None:
        """Single-doc fetch.

        ``MemoryService`` does not currently expose a get-by-id method,
        so for memory kinds this returns ``None``.  Callers that need
        memory lookup should use :meth:`search` or :meth:`list`.
        """
        if self._is_memory_kind(kind):
            # MemoryService has no get-by-id; documented limitation.
            return None

        raise ValueError(f"Unsupported knowledge kind: {kind!r}")

    # ------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------

    async def create(self, doc: KnowledgeDocCreate) -> KnowledgeDoc:
        """Create a document of the requested ``kind``."""
        kind = doc.kind
        meta = doc.metadata or {}

        if self._is_memory_kind(kind):
            mem = self._require_memory()
            scope = meta.get("scope") or (
                _FACT_SCOPE if kind == "fact" else _DEFAULT_MEMORY_SCOPE
            )
            entry = await mem.add(
                content=doc.content,
                scope=scope,
                category=meta.get("category"),
                source=meta.get("source", "llm"),
                conversation_id=meta.get("conversation_id"),
                expires_at=meta.get("expires_at"),
            )
            return _memory_entry_to_doc(entry)

        raise ValueError(f"Unsupported knowledge kind: {kind!r}")

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
        """Apply a partial update.  Memory-kind updates are unsupported."""
        if self._is_memory_kind(kind):
            # MemoryService is append-only by design.
            self._log.debug(
                "update() on memory kind {!r} is a no-op (id={})",
                kind, doc_id,
            )
            return None

        raise ValueError(f"Unsupported knowledge kind: {kind!r}")

    # ------------------------------------------------------------------
    # delete
    # ------------------------------------------------------------------

    async def delete(
        self, doc_id: str, *, kind: KnowledgeKind,
    ) -> bool:
        """Single-doc delete."""
        if self._is_memory_kind(kind):
            mem = self._require_memory()
            return bool(await mem.delete(doc_id))

        raise ValueError(f"Unsupported knowledge kind: {kind!r}")

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
        """Paginated listing."""
        filters = filters or {}

        if self._is_memory_kind(kind):
            mem = self._require_memory()
            mem_filter = self._build_memory_filter(kind, filters)
            entries, total = await mem.list(
                filter=mem_filter,
                limit=limit,
                offset=offset,
            )
            return [_memory_entry_to_doc(e) for e in entries], total

        raise ValueError(f"Unsupported knowledge kind: {kind!r}")

    # ------------------------------------------------------------------
    # delete_by_filter
    # ------------------------------------------------------------------

    async def delete_by_filter(
        self,
        *,
        kind: KnowledgeKind,
        filters: dict[str, Any],
    ) -> int:
        """Bulk delete.  Currently supports memory ``scope`` filter."""
        if self._is_memory_kind(kind):
            mem = self._require_memory()
            scope = filters.get("scope")
            if scope is None:
                raise ValueError(
                    "delete_by_filter for memory requires a 'scope' filter",
                )
            return int(await mem.delete_by_scope(scope))

        raise ValueError(
            f"delete_by_filter not supported for kind {kind!r}",
        )

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------

    async def health(self) -> BackendHealth:
        """Return ``up`` if the memory service is wired."""
        if self._memory is None:
            return BackendHealth(
                status="down",
                detail="memory_service unavailable",
            )
        return BackendHealth(status="up", detail=None)

    # ------------------------------------------------------------------
    # Internal — filter translation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_memory_filter(
        kind: KnowledgeKind,
        filters: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Translate generic filters into ``MemoryService``'s filter dict.

        For ``kind == "fact"`` the scope is forced to ``user_fact``
        unless the caller explicitly overrides it.
        """
        result: dict[str, Any] = {}
        if filters:
            if "scope" in filters and filters["scope"] is not None:
                result["scope"] = filters["scope"]
            if "category" in filters and filters["category"] is not None:
                result["category"] = filters["category"]

        if kind == "fact" and "scope" not in result:
            result["scope"] = _FACT_SCOPE

        return result or None


# ---------------------------------------------------------------------------
# Entry → KnowledgeDoc converters
# ---------------------------------------------------------------------------

def _memory_entry_to_doc(entry: MemoryEntry) -> KnowledgeDoc:
    """Adapt a :class:`MemoryEntry` to a :class:`KnowledgeDoc`."""
    scope = getattr(entry, "scope", _DEFAULT_MEMORY_SCOPE)
    kind: KnowledgeKind = "fact" if scope == _FACT_SCOPE else "memory"
    conv_id = getattr(entry, "conversation_id", None)
    expires = getattr(entry, "expires_at", None)
    return KnowledgeDoc(
        id=str(getattr(entry, "id", "")),
        kind=kind,
        title=None,
        content=getattr(entry, "content", ""),
        tags=[],
        metadata={
            "scope": scope,
            "category": getattr(entry, "category", None),
            "source": getattr(entry, "source", None),
            "conversation_id": str(conv_id) if conv_id else None,
            "expires_at": expires,
            "embedding_model": getattr(entry, "embedding_model", ""),
        },
        created_at=getattr(entry, "created_at", None),
        updated_at=None,
    )
