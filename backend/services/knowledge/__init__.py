"""AL\\CE — Knowledge backend abstraction.

Plugins that need persistent semantic storage (memory, facts) depend on
the :class:`~backend.services.knowledge.protocol.KnowledgeBackend`
Protocol instead of concrete services.

:class:`~backend.services.knowledge.qdrant_backend.QdrantBackend` is a
thin adapter over the existing ``MemoryService`` (``memory``/``fact``
kinds). ``note`` knowledge is served by
:class:`~backend.services.knowledge.continuum_backend.ContinuumBackend`,
composed with Qdrant behind
:class:`~backend.services.knowledge.composite_backend.\
CompositeKnowledgeBackend`.
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
from backend.services.knowledge.continuum_backend import ContinuumBackend
from backend.services.knowledge.continuum_client import (
    ContinuumClient,
    ContinuumError,
)
from backend.services.knowledge.composite_backend import (
    CompositeKnowledgeBackend,
)

__all__ = [
    "BackendHealth",
    "CompositeKnowledgeBackend",
    "ContinuumBackend",
    "ContinuumClient",
    "ContinuumError",
    "KnowledgeBackend",
    "KnowledgeDoc",
    "KnowledgeDocCreate",
    "KnowledgeDocPatch",
    "KnowledgeHit",
    "KnowledgeKind",
    "QdrantBackend",
]
