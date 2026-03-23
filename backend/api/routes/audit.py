"""AL\\CE — Tool confirmation audit REST endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from sqlalchemy import func as sa_func
from sqlmodel import select, col

from backend.db.models import ToolConfirmationAudit

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/confirmations")
async def list_confirmations(
    request: Request,
    conversation_id: uuid.UUID | None = Query(None, description="Filter by conversation"),
    tool_name: str | None = Query(None, description="Filter by tool name"),
    approved: bool | None = Query(None, description="Filter by approval status"),
    limit: int = Query(50, ge=1, le=500, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> dict[str, Any]:
    """List tool confirmation audit entries with optional filters.

    Returns paginated audit log entries ordered by creation time descending.
    """
    ctx = request.app.state.context
    if ctx.db is None:
        raise HTTPException(status_code=503, detail="Database not available")

    async with ctx.db() as session:
        # Count query for pagination total.
        count_stmt = select(sa_func.count(ToolConfirmationAudit.id))
        if conversation_id is not None:
            count_stmt = count_stmt.where(
                ToolConfirmationAudit.conversation_id == conversation_id
            )
        if tool_name is not None:
            count_stmt = count_stmt.where(
                ToolConfirmationAudit.tool_name == tool_name
            )
        if approved is not None:
            count_stmt = count_stmt.where(
                ToolConfirmationAudit.user_approved == approved
            )
        total = (await session.exec(count_stmt)).one()

        # Data query.
        stmt = select(ToolConfirmationAudit).order_by(
            col(ToolConfirmationAudit.created_at).desc()
        )

        if conversation_id is not None:
            stmt = stmt.where(
                ToolConfirmationAudit.conversation_id == conversation_id
            )
        if tool_name is not None:
            stmt = stmt.where(
                ToolConfirmationAudit.tool_name == tool_name
            )
        if approved is not None:
            stmt = stmt.where(
                ToolConfirmationAudit.user_approved == approved
            )

        stmt = stmt.offset(offset).limit(limit)
        results = await session.exec(stmt)
        entries = results.all()

    return {
        "entries": [
            {
                "id": str(e.id),
                "conversation_id": str(e.conversation_id),
                "execution_id": e.execution_id,
                "tool_name": e.tool_name,
                "args_json": e.args_json,
                "risk_level": e.risk_level,
                "user_approved": e.user_approved,
                "rejection_reason": e.rejection_reason,
                "thinking_content": e.thinking_content,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "total": total,
        "count": len(entries),
        "offset": offset,
        "limit": limit,
    }
