"""AL\\CE — Knowledge backend abstraction.

Phase 1 preparation for Phase 3 (Continuum migration).  Plugins that
need persistent semantic storage (notes, memory, facts) depend on the
:class:`~backend.services.knowledge.protocol.KnowledgeBackend` Protocol
instead of concrete services.

The only Phase 1 implementation is
:class:`~backend.services.knowledge.qdrant_backend.QdrantBackend`, a
thin adapter that wraps the existing ``MemoryService`` and
``NoteService``.
"""

from __future__ import annotations

from backend.services.knowledge.protocol import (
    KnowledgeBackend,
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeDocPatch,
    KnowledgeHit,
    KnowledgeKind,
    BackendHealth,
)
from backend.services.knowledge.qdrant_backend import QdrantBackend

__all__ = [
    "BackendHealth",
    "KnowledgeBackend",
    "KnowledgeDoc",
    "KnowledgeDocCreate",
    "KnowledgeDocPatch",
    "KnowledgeHit",
    "KnowledgeKind",
    "QdrantBackend",
]
