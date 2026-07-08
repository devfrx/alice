"""Knowledge/RAG readiness status route."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class RagReadinessResponse(BaseModel):
    """RAG/knowledge readiness verdict."""

    ready: bool
    reason: str
    memory_enabled: bool
    tool_rag_enabled: bool


@router.get(
    "/readiness",
    summary="RAG/knowledge readiness verdict",
    response_model=RagReadinessResponse,
)
async def readiness(request: Request) -> RagReadinessResponse:
    """Return the current RAG readiness verdict (or a not-initialized default)."""
    ctx = request.app.state.context
    rr = getattr(ctx, "rag_readiness", None)
    if rr is None:
        return RagReadinessResponse(
            ready=False,
            reason="not initialized",
            memory_enabled=False,
            tool_rag_enabled=False,
        )
    return RagReadinessResponse(
        ready=rr.ready,
        reason=rr.reason,
        memory_enabled=rr.memory_enabled,
        tool_rag_enabled=rr.tool_rag_enabled,
    )
