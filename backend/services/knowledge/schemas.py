"""AL\\CE — Pydantic API models for the knowledge domain (``/api/memory``).

Response contracts of the memory REST routes (Fase 4).  They convert
:class:`~backend.services.knowledge.protocol.KnowledgeDoc` documents to
the public REST shape — the routes hold no serialisation logic.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.services.knowledge.protocol import KnowledgeDoc


class MemorySearchRequest(BaseModel):
    """Body for ``POST /api/memory/search``."""

    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(10, ge=1, le=50)
    category: str | None = None


class MemoryEntryRead(BaseModel):
    """Public representation of a memory entry."""

    id: str
    content: str
    scope: str
    category: str | None = None
    source: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    conversation_id: str | None = None

    @classmethod
    def from_doc(cls, doc: KnowledgeDoc) -> MemoryEntryRead:
        """Map a memory/fact ``KnowledgeDoc`` to the REST shape."""
        meta = doc.metadata or {}
        return cls(
            id=doc.id,
            content=doc.content,
            scope=str(meta.get("scope") or ""),
            category=meta.get("category"),
            source=meta.get("source"),
            created_at=doc.created_at,
            expires_at=meta.get("expires_at"),
            conversation_id=meta.get("conversation_id"),
        )


class MemoryListResponse(BaseModel):
    """Paginated memory list (``{items, total}`` convention, spec §6)."""

    items: list[MemoryEntryRead]
    total: int


class MemorySearchHit(BaseModel):
    """Search result: entry + similarity score."""

    entry: MemoryEntryRead
    score: float


class MemorySearchResponse(BaseModel):
    """Semantic search results."""

    results: list[MemorySearchHit]


class MemoryDeleteResponse(BaseModel):
    """Single-delete acknowledgement."""

    deleted: bool


class MemoryDeleteCountResponse(BaseModel):
    """Bulk-delete count."""

    deleted_count: int


class MemoryStatsResponse(BaseModel):
    """Aggregate memory statistics."""

    total: int
    by_scope: dict[str, int]
    by_category: dict[str, int]
    db_size_bytes: int
