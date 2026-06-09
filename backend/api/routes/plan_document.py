"""AL\\CE — Conversation plan-document REST API.

Endpoints (mounted under ``/api/plan-document``):

* ``GET /{conversation_id}`` — fetch the persisted plan document for a
  conversation.

The plan document is the free-form markdown write-up maintained per
conversation and persisted by
:class:`~backend.services.plan_document_service.PlanDocumentService`.  This
read-only endpoint lets the frontend render the live document.  It mirrors
:mod:`backend.api.routes.tasks`: the
:class:`~backend.core.context.AppContext` is read off ``request.app.state``
and a path UUID is validated with the same 400-on-bad-id helper.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from backend.services.plan_document_service import PlanDocumentService

router = APIRouter(prefix="/plan-document", tags=["plan-document"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PlanDocumentResponse(BaseModel):
    """The persisted plan document for a single conversation.

    Attributes:
        conversation_id: The owning conversation id (string form).
        title: The optional short heading (``""`` when unset).
        body: The markdown body text (``""`` when unset).
        updated_at: When the document was last written (``None`` when unset).
    """

    conversation_id: str
    title: str
    body: str
    updated_at: datetime | None


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


def _get_plan_document_service(request: Request) -> PlanDocumentService | None:
    """Fetch the plan-document service off ``app.state.context`` (``None`` if absent).

    Defensive by design: the service is always wired in production, but a
    missing context or unset service yields ``None`` so the caller can return
    an empty document instead of erroring.
    """
    ctx = getattr(request.app.state, "context", None)
    service: PlanDocumentService | None = (
        getattr(ctx, "plan_document_service", None) if ctx else None
    )
    return service


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{conversation_id}",
    response_model=PlanDocumentResponse,
    summary="Get a conversation's persisted plan document",
)
async def get_conversation_plan_document(
    conversation_id: str, request: Request,
) -> PlanDocumentResponse:
    """Return the persisted plan document for *conversation_id*.

    An unknown conversation (no document row) yields an empty document
    (``title=""``, ``body=""``, ``updated_at=None``), and an unwired service is
    treated the same way rather than raising.

    Args:
        conversation_id: The owning conversation id (a UUID string).
        request: The incoming request (carries ``app.state.context``).

    Returns:
        A :class:`PlanDocumentResponse` carrying the conversation id and the
        stored document (empty when unset).

    Raises:
        HTTPException: ``400`` when *conversation_id* is not a valid UUID.
    """
    conv_uuid = _to_uuid(conversation_id)
    service = _get_plan_document_service(request)
    doc = await service.get_document(conv_uuid) if service is not None else None
    if not doc:
        return PlanDocumentResponse(
            conversation_id=str(conversation_id),
            title="",
            body="",
            updated_at=None,
        )
    return PlanDocumentResponse(
        conversation_id=str(conversation_id),
        title=str(doc.get("title", "")),
        body=str(doc.get("body", "")),
        updated_at=doc.get("updated_at"),
    )
