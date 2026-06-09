"""Knowledge/RAG readiness status route."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/readiness", summary="RAG/knowledge readiness verdict")
async def readiness(request: Request) -> dict[str, object]:
    """Return the current RAG readiness verdict (or a not-initialized default)."""
    ctx = request.app.state.context
    rr = getattr(ctx, "rag_readiness", None)
    if rr is None:
        return {
            "ready": False,
            "reason": "not initialized",
            "memory_enabled": False,
            "tool_rag_enabled": False,
        }
    return {
        "ready": rr.ready,
        "reason": rr.reason,
        "memory_enabled": rr.memory_enabled,
        "tool_rag_enabled": rr.tool_rag_enabled,
    }
