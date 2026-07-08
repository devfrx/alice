"""AL\\CE — Memory management REST endpoints.

Every endpoint delegates to the :class:`KnowledgeServiceProtocol`
(single entry point to the knowledge domain, Fase 4) with
``kind="memory"`` — no domain logic lives here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger

from backend.core.protocols import KnowledgeServiceProtocol
from backend.services.knowledge.schemas import (
    MemoryDeleteCountResponse,
    MemoryDeleteResponse,
    MemoryEntryRead,
    MemoryListResponse,
    MemorySearchHit,
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryStatsResponse,
)

router = APIRouter(prefix="/memory", tags=["memory"])


def _get_knowledge_service(request: Request) -> KnowledgeServiceProtocol:
    """Extract the knowledge service from app context or raise 503."""
    ctx = request.app.state.context
    svc: KnowledgeServiceProtocol | None = getattr(ctx, "knowledge_service", None)
    if svc is None or not svc.memory_available:
        raise HTTPException(status_code=503, detail="Memory service not available")
    return svc


@router.get("", response_model=MemoryListResponse)
async def list_memories(
    request: Request,
    scope: str | None = Query(None, description="Filter by scope"),
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> MemoryListResponse:
    """List memory entries with optional filters."""
    svc = _get_knowledge_service(request)

    filters: dict[str, str] = {}
    if scope is not None:
        filters["scope"] = scope
    if category is not None:
        filters["category"] = category

    docs, total = await svc.list(
        kind="memory", filters=filters or None, limit=limit, offset=offset,
    )
    return MemoryListResponse(
        items=[MemoryEntryRead.from_doc(d) for d in docs],
        total=total,
    )


@router.post("/search", response_model=MemorySearchResponse)
async def search_memories(
    request: Request,
    body: MemorySearchRequest,
) -> MemorySearchResponse:
    """Semantic search over stored memories."""
    svc = _get_knowledge_service(request)

    filters = {"category": body.category} if body.category is not None else None
    hits = await svc.search(body.query, kind="memory", k=body.limit, filters=filters)
    return MemorySearchResponse(
        results=[
            MemorySearchHit(entry=MemoryEntryRead.from_doc(h.doc), score=h.score)
            for h in hits
        ],
    )


@router.delete("/all", response_model=MemoryDeleteCountResponse)
async def delete_all_memory(request: Request) -> MemoryDeleteCountResponse:
    """Delete every memory entry (all scopes)."""
    svc = _get_knowledge_service(request)

    count = await svc.delete_all_memories()
    logger.info("Deleted all {} memories", count)
    return MemoryDeleteCountResponse(deleted_count=count)


@router.delete("/session", response_model=MemoryDeleteCountResponse)
async def delete_session_memory(request: Request) -> MemoryDeleteCountResponse:
    """Delete all session-scoped memories."""
    svc = _get_knowledge_service(request)

    count = await svc.delete_by_filter(kind="memory", filters={"scope": "session"})
    logger.info("Deleted {} session memories", count)
    return MemoryDeleteCountResponse(deleted_count=count)


@router.delete("/{memory_id}", response_model=MemoryDeleteResponse)
async def delete_memory(
    request: Request,
    memory_id: str,
) -> MemoryDeleteResponse:
    """Delete a single memory entry by ID."""
    svc = _get_knowledge_service(request)

    try:
        uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid memory ID format")

    deleted = await svc.delete(memory_id, kind="memory")
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")

    logger.info("Deleted memory {}", memory_id)
    return MemoryDeleteResponse(deleted=True)


@router.get("/stats", response_model=MemoryStatsResponse)
async def memory_stats(request: Request) -> MemoryStatsResponse:
    """Return memory usage statistics."""
    svc = _get_knowledge_service(request)
    return MemoryStatsResponse(**await svc.memory_stats())
