"""AL\\CE — Conversation-tasks REST API.

Endpoints (mounted under ``/api/tasks``):

* ``GET /{conversation_id}`` — fetch the persisted task list for a conversation.

The task list is the model-owned todo-list maintained through the
``update_tasks`` meta-tool and persisted per conversation by
:class:`~backend.services.plan_service.PlanService`.  This read-only endpoint
lets the frontend render the live task list for a conversation.  It mirrors
:mod:`backend.api.routes.artifacts`: the
:class:`~backend.core.context.AppContext` is read off ``request.app.state``
and a path UUID is validated with the same 400-on-bad-id helper.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from backend.services.plan_service import PlanService

router = APIRouter(prefix="/tasks", tags=["tasks"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TasksResponse(BaseModel):
    """The persisted task list for a single conversation.

    Attributes:
        conversation_id: The owning conversation id (string form).
        steps: Ordered ``{"step": str, "status": str}`` items (possibly empty).
    """

    conversation_id: str
    steps: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_uuid(value: str) -> uuid.UUID:
    """Validate *value* as a UUID or raise a 400."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID: {value}",
        ) from exc


def _get_plan_service(request: Request) -> PlanService | None:
    """Fetch the plan service off ``app.state.context`` (``None`` if absent).

    Defensive by design: the service is always wired in production, but a
    missing context or unset service yields ``None`` so the caller can return
    an empty task list instead of erroring.
    """
    ctx = getattr(request.app.state, "context", None)
    service: PlanService | None = (
        getattr(ctx, "plan_service", None) if ctx else None
    )
    return service


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{conversation_id}",
    response_model=TasksResponse,
    summary="Get a conversation's persisted task list",
)
async def get_conversation_plan(
    conversation_id: str, request: Request,
) -> TasksResponse:
    """Return the persisted task steps for *conversation_id*.

    The task list is the model-owned todo-list (``update_tasks``) stored per
    conversation.  An unknown conversation (no task row) yields an empty
    ``steps`` list, and an unwired plan service is treated the same way
    rather than raising.

    Args:
        conversation_id: The owning conversation id (a UUID string).
        request: The incoming request (carries ``app.state.context``).

    Returns:
        A :class:`TasksResponse` carrying the conversation id and the ordered
        ``{"step", "status"}`` step dicts (possibly empty).

    Raises:
        HTTPException: ``400`` when *conversation_id* is not a valid UUID.
    """
    conv_uuid = _to_uuid(conversation_id)
    plan_service = _get_plan_service(request)
    if plan_service is None:
        return TasksResponse(conversation_id=str(conversation_id), steps=[])
    steps = await plan_service.get_plan(conv_uuid)
    return TasksResponse(conversation_id=str(conversation_id), steps=steps)
