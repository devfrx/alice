"""AL\\CE — Vector store management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from backend.core.context import AppContext

router = APIRouter(prefix="/vector-store", tags=["vector-store"])


def _get_ctx(request: Request) -> AppContext:
    return request.app.state.context


@router.get("/stats")
async def get_stats(request: Request) -> dict[str, Any]:
    """Return Qdrant vector store statistics."""
    ctx = _get_ctx(request)

    if not ctx.qdrant_service:
        return {
            "mode": "unavailable",
            "connected": False,
            "collections": [],
        }

    collections_info: list[dict[str, Any]] = []
    from backend.services.qdrant_service import (
        COLLECTION_MEMORY,
        COLLECTION_NOTES,
        COLLECTION_TOOLS,
    )

    for coll_name in (COLLECTION_MEMORY, COLLECTION_NOTES, COLLECTION_TOOLS):
        try:
            count = await ctx.qdrant_service.count(coll_name)
            dim = await ctx.qdrant_service.get_collection_dim(coll_name)
            collections_info.append({
                "name": coll_name,
                "points_count": count,
                "vectors_size": dim,
            })
        except Exception as exc:
            logger.warning(
                "Failed to get stats for collection '{}': {}",
                coll_name, exc,
            )
            collections_info.append({
                "name": coll_name,
                "points_count": 0,
                "vectors_size": 0,
            })

    qdrant_svc = ctx.qdrant_service
    mode = ctx.config.qdrant.mode
    if qdrant_svc.in_memory:
        mode = "in-memory (fallback)"

    return {
        "mode": mode,
        "connected": True,
        "collections": collections_info,
    }


@router.post("/reembed-tools")
async def reembed_tools(request: Request) -> dict[str, str]:
    """Trigger re-embedding of all registered tools."""
    ctx = _get_ctx(request)

    if not ctx.tool_registry:
        raise HTTPException(503, "Tool registry not available")

    try:
        await ctx.tool_registry.embed_tools()
        return {"status": "ok"}
    except Exception as exc:
        logger.error("Re-embed tools failed: {}", exc)
        raise HTTPException(500, "Re-embedding failed")
