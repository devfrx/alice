"""O.M.N.I.A. — Memory management REST endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

router = APIRouter(prefix="/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    """Body for POST /memory/search."""

    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(10, ge=1, le=50)
    category: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_memory_service(request: Request):
    """Extract memory_service from app context or raise 503."""
    ctx = request.app.state.context
    svc = ctx.memory_service
    if svc is None:
        raise HTTPException(status_code=503, detail="Memory service not available")
    return svc


def _serialize_entry(entry: Any) -> dict[str, Any]:
    """Normalise a memory entry to a JSON-safe dict."""
    if hasattr(entry, "model_dump"):
        data = entry.model_dump()
    elif hasattr(entry, "to_dict"):
        data = entry.to_dict()
    elif hasattr(entry, "__dict__"):
        data = dict(entry.__dict__)
    else:
        data = dict(entry)

    for key in ("id", "conversation_id"):
        if key in data and data[key] is not None:
            data[key] = str(data[key])

    for key in ("created_at", "expires_at"):
        val = data.get(key)
        if val is not None and hasattr(val, "isoformat"):
            data[key] = val.isoformat()

    return {
        "id": data.get("id"),
        "content": data.get("content", ""),
        "scope": data.get("scope", ""),
        "category": data.get("category"),
        "source": data.get("source"),
        "created_at": data.get("created_at"),
        "expires_at": data.get("expires_at"),
        "conversation_id": data.get("conversation_id"),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def list_memories(
    request: Request,
    scope: str | None = Query(None, description="Filter by scope"),
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> dict[str, Any]:
    """List memory entries with optional filters.

    Returns paginated entries ordered by creation time descending.
    """
    svc = _get_memory_service(request)

    filter_dict: dict[str, Any] = {}
    if scope is not None:
        filter_dict["scope"] = scope
    if category is not None:
        filter_dict["category"] = category

    entries, total = await svc.list(
        filter=filter_dict or None,
        limit=limit,
        offset=offset,
    )

    return {
        "entries": [_serialize_entry(e) for e in entries],
        "total": total,
    }


@router.post("/search")
async def search_memories(
    request: Request,
    body: SearchRequest,
) -> dict[str, Any]:
    """Semantic search over stored memories."""
    svc = _get_memory_service(request)

    filter_dict: dict[str, Any] | None = None
    if body.category is not None:
        filter_dict = {"category": body.category}

    results = await svc.search(
        query=body.query,
        k=body.limit,
        filter=filter_dict,
    )

    serialized: list[dict[str, Any]] = []
    for item in results:
        if isinstance(item, dict) and "entry" in item:
            serialized.append({
                "entry": _serialize_entry(item["entry"]),
                "score": item.get("score", 0.0),
            })
        elif isinstance(item, tuple) and len(item) == 2:
            serialized.append({
                "entry": _serialize_entry(item[0]),
                "score": item[1],
            })
        else:
            serialized.append({
                "entry": _serialize_entry(item),
                "score": 0.0,
            })

    return {"results": serialized}


@router.delete("/all")
async def delete_all_memory(request: Request) -> dict[str, int]:
    """Delete every memory entry (all scopes)."""
    svc = _get_memory_service(request)

    count = await svc.delete_all()
    logger.info("Deleted all {} memories", count)
    return {"deleted_count": count}


@router.delete("/session")
async def delete_session_memory(request: Request) -> dict[str, int]:
    """Delete all session-scoped memories."""
    svc = _get_memory_service(request)

    count = await svc.delete_by_scope("session")
    logger.info("Deleted {} session memories", count)
    return {"deleted_count": count}


@router.delete("/{memory_id}")
async def delete_memory(
    request: Request,
    memory_id: str,
) -> dict[str, bool]:
    """Delete a single memory entry by ID."""
    svc = _get_memory_service(request)

    try:
        uuid.UUID(memory_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid memory ID format")

    deleted = await svc.delete(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")

    logger.info("Deleted memory {}", memory_id)
    return {"deleted": True}


@router.get("/stats")
async def memory_stats(request: Request) -> dict[str, Any]:
    """Return memory usage statistics."""
    svc = _get_memory_service(request)
    return await svc.stats()
