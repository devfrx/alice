"""AL\\CE — Vector store management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from backend.core.context import AppContext

router = APIRouter(prefix="/vector-store", tags=["vector-store"])


def _get_ctx(request: Request) -> AppContext:
    return request.app.state.context


def _rag_status(ctx: AppContext) -> dict[str, Any]:
    """Snapshot the current RAG readiness verdict for the UI.

    Reflects whether memory search and tool-RAG are effectively usable —
    independent of the persisted ``tool_rag_enabled`` toggle — so the
    frontend can show *why* Tool RAG is disabled (e.g. Qdrant unavailable).
    """
    rag = getattr(ctx, "rag_readiness", None)
    if rag is None:
        return {
            "ready": False,
            "reason": "not initialised",
            "memory_enabled": False,
            "tool_rag_enabled": False,
        }
    return {
        "ready": bool(rag.ready),
        "reason": rag.reason,
        "memory_enabled": bool(rag.memory_enabled),
        "tool_rag_enabled": bool(rag.tool_rag_enabled),
    }


async def _build_stats(ctx: AppContext) -> dict[str, Any]:
    """Build the vector-store status payload (shared by /stats and /repair)."""
    if not ctx.qdrant_service:
        return {
            "mode": "unavailable",
            "connected": False,
            "collections": [],
            "rag": _rag_status(ctx),
        }

    from backend.services.qdrant_service import (
        COLLECTION_MEMORY,
        COLLECTION_TOOLS,
    )

    collections_info: list[dict[str, Any]] = []
    for coll_name in (COLLECTION_MEMORY, COLLECTION_TOOLS):
        try:
            count = await ctx.qdrant_service.count(coll_name)
            dim = await ctx.qdrant_service.get_collection_dim(coll_name)
            collections_info.append({
                "name": coll_name,
                "points_count": count,
                "vectors_size": dim if dim is not None else 0,
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

    mode = ctx.config.qdrant.mode
    if ctx.qdrant_service.in_memory:
        mode = "in-memory (fallback)"

    return {
        "mode": mode,
        "connected": True,
        "collections": collections_info,
        "rag": _rag_status(ctx),
    }


@router.get("/stats")
async def get_stats(request: Request) -> dict[str, Any]:
    """Return Qdrant vector store statistics + RAG readiness."""
    return await _build_stats(_get_ctx(request))


@router.post("/repair")
async def repair(request: Request) -> dict[str, Any]:
    """Reset the embedded vector store and re-wire the RAG stack.

    Manual, user-triggered recovery (the "Ripara/Reset" CTA): clears the
    persisted embedded data (destructive — regenerable memories/facts) and
    re-initialises Qdrant + memory + tool-RAG in place, then returns the
    refreshed status so the UI reflects the new state immediately.
    """
    ctx = _get_ctx(request)
    from backend.services.knowledge_init import repair_vector_store

    try:
        await repair_vector_store(ctx)
    except Exception as exc:  # repair never raises, but stay defensive
        logger.error("Vector store repair failed: {}", exc)
        raise HTTPException(500, "Vector store repair failed") from exc

    return await _build_stats(ctx)


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
        raise HTTPException(500, "Re-embedding failed") from exc
