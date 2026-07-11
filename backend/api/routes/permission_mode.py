"""AL\\CE — Conversation permission-tier REST API (Fase 7).

Endpoints (mounted under ``/api/permission-mode``):

* ``GET /{conversation_id}`` — read the conversation's permission tier.
* ``PUT /{conversation_id}`` — set the conversation's permission tier.

Unlike :mod:`backend.api.routes.scope`, the mutating verb is **NOT** idle-only:
the turn engine reads the mode synchronously *per tool-call*, so changing it
mid-turn (the user "hitting the brakes") is sound and takes effect on the next
gate. The tier is settable only here (and the matching WS path) — never from a
tool — which is the anti-privilege-escalation invariant: the model cannot widen
its own authorization.

A successful ``set_mode`` emits the ``permission_mode.updated`` event through
:class:`~backend.services.permission_mode_service.PermissionModeService`'s own
event callback (wired to the events WebSocket in the app lifespan); this module
never broadcasts itself, mirroring :mod:`backend.api.routes.scope`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from backend.services.permission_mode_service import (
    PermissionMode,
    PermissionModeService,
)

router = APIRouter(prefix="/permission-mode", tags=["permissions"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PermissionModeResponse(BaseModel):
    """The permission tier for a single conversation.

    Attributes:
        conversation_id: The owning conversation id (canonical string form).
        mode: The authorization tier (:class:`PermissionMode`):
            ``strict`` / ``auto_edits`` / ``plan`` / ``autopilot``.
    """

    conversation_id: str
    mode: PermissionMode


class PermissionModeUpdateRequest(BaseModel):
    """Request body for ``PUT /permission-mode/{conversation_id}``.

    Attributes:
        mode: The new tier (must be a valid :class:`PermissionMode` value).
    """

    mode: str


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


def _get_mode_service(request: Request) -> PermissionModeService | None:
    """Fetch the permission-mode service off ``app.state.context``.

    Defensive by design: the service is always wired in production, but a
    missing context or unset service yields ``None`` so the read path can return
    the default tier and the write path can return ``503`` rather than raising an
    opaque ``AttributeError``.
    """
    ctx = getattr(request.app.state, "context", None)
    service: PermissionModeService | None = (
        getattr(ctx, "permission_mode_service", None) if ctx else None
    )
    return service


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{conversation_id}",
    response_model=PermissionModeResponse,
    summary="Read a conversation's permission tier",
)
async def get_permission_mode(
    conversation_id: str, request: Request,
) -> PermissionModeResponse:
    """Return the permission tier for *conversation_id*.

    Read-only and always succeeds for a valid id: an unknown conversation or an
    unwired service yields the default tier (never a 5xx).

    Args:
        conversation_id: The owning conversation id (a UUID string).
        request: The incoming request (carries ``app.state.context``).

    Returns:
        A :class:`PermissionModeResponse` with the canonical conversation id and
        the resolved tier.

    Raises:
        HTTPException: ``400`` when *conversation_id* is not a valid UUID.
    """
    conv_uuid = _to_uuid(conversation_id)
    service = _get_mode_service(request)
    if service is None:
        return PermissionModeResponse(
            conversation_id=str(conv_uuid), mode=PermissionMode.STRICT,
        )
    mode = service.get_mode(conv_uuid)
    return PermissionModeResponse(conversation_id=str(conv_uuid), mode=mode)


@router.put(
    "/{conversation_id}",
    response_model=PermissionModeResponse,
    summary="Set a conversation's permission tier (any time)",
)
async def put_permission_mode(
    conversation_id: str, body: PermissionModeUpdateRequest, request: Request,
) -> PermissionModeResponse:
    """Set the permission tier for *conversation_id* (no idle guard).

    Guard order: an unwired service is reported first (``503``); then the tier
    string is validated (``400`` on an unknown tier); then it is persisted and
    broadcast by the service.  There is intentionally **no** idle guard — the
    tier is read per tool-call, so a mid-turn change is consistent.

    Args:
        conversation_id: The owning conversation id (a UUID string).
        body: The new tier.
        request: The incoming request (carries ``app.state.context``).

    Returns:
        A :class:`PermissionModeResponse` echoing the persisted tier.

    Raises:
        HTTPException: ``400`` for a bad UUID or an unknown tier, ``503`` when
            the permission-mode service is unavailable.
    """
    conv_uuid = _to_uuid(conversation_id)
    service = _get_mode_service(request)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Permission-mode service unavailable",
        )
    try:
        mode = PermissionMode(body.mode)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid permission mode: {body.mode}",
        ) from exc
    await service.set_mode(conv_uuid, mode)
    return PermissionModeResponse(conversation_id=str(conv_uuid), mode=mode)
