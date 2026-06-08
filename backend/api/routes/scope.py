"""AL\\CE — Conversation workspace-scope REST API.

Endpoints (mounted under ``/api/scope``):

* ``GET /{conversation_id}`` — read the conversation's scope folders together
  with an ``is_idle`` flag (``True`` when no turn is currently running).
* ``PUT /{conversation_id}`` — replace the scope folders.
* ``DELETE /{conversation_id}`` — clear the scope folders.

The two mutating verbs are **idle-only**: while a turn is in flight for the
conversation they are rejected with ``409`` / ``scope_locked`` (the in-flight
turn captured the scope at start, so changing it mid-turn would be unsound).
Idle-ness is read from the chat busy registry
(:func:`backend.api.routes.chat._shared.is_conversation_active`), which keys on
the **canonical** conversation-id string — so the guard parses the path id to a
UUID first and checks ``str(conv_uuid)``.

This module never broadcasts itself: a successful ``set_scope`` / ``clear_scope``
emits the ``scope.updated`` event through
:class:`~backend.services.scope_service.ScopeService`'s own event callback
(wired to the events WebSocket in the app lifespan).  It mirrors
:mod:`backend.api.routes.plans`: the :class:`~backend.core.context.AppContext`
is read off ``request.app.state`` and a path UUID is validated with the same
400-on-bad-id helper.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.api.routes.chat._shared import is_conversation_active
from backend.services.scope_service import ScopeService

router = APIRouter(prefix="/scope", tags=["scope"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ScopeResponse(BaseModel):
    """The workspace scope for a single conversation.

    Attributes:
        conversation_id: The owning conversation id (canonical string form).
        folders: The scope folders as absolute path strings (possibly empty).
        is_idle: ``True`` when no turn is running for the conversation, i.e.
            when the mutating verbs would be accepted rather than ``409``-ed.
    """

    conversation_id: str
    folders: list[str]
    is_idle: bool


class ScopeUpdateRequest(BaseModel):
    """Request body for ``PUT /scope/{conversation_id}``.

    Attributes:
        folders: The candidate absolute folder paths to confine tools to.  An
            empty list clears the scope (equivalent to ``DELETE``).
    """

    folders: list[str] = Field(default_factory=list)


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


def _get_scope_service(request: Request) -> ScopeService | None:
    """Fetch the scope service off ``app.state.context`` (``None`` if absent).

    Defensive by design: the service is always wired in production, but a
    missing context or unset service yields ``None`` so the read path can
    return an empty scope and the write paths can return ``503`` rather than
    raising an opaque ``AttributeError``.
    """
    ctx = getattr(request.app.state, "context", None)
    service: ScopeService | None = (
        getattr(ctx, "scope_service", None) if ctx else None
    )
    return service


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{conversation_id}",
    response_model=ScopeResponse,
    summary="Read a conversation's workspace scope",
)
async def get_conversation_scope(
    conversation_id: str, request: Request,
) -> ScopeResponse:
    """Return the scope folders for *conversation_id* plus an ``is_idle`` flag.

    Read-only and always succeeds for a valid id: an unknown conversation, an
    unwired scope service, or a missing app context all yield an empty
    ``folders`` list (never a 5xx).  ``is_idle`` reflects the live busy
    registry — ``False`` while a turn runs for the conversation.

    Args:
        conversation_id: The owning conversation id (a UUID string).
        request: The incoming request (carries ``app.state.context``).

    Returns:
        A :class:`ScopeResponse` with the canonical conversation id, the scope
        folders (possibly empty), and the idle flag.

    Raises:
        HTTPException: ``400`` when *conversation_id* is not a valid UUID.
    """
    conv_uuid = _to_uuid(conversation_id)
    idle = not is_conversation_active(str(conv_uuid))
    service = _get_scope_service(request)
    if service is None:
        return ScopeResponse(
            conversation_id=str(conv_uuid), folders=[], is_idle=idle,
        )
    folders = await service.get_scope(conv_uuid)
    return ScopeResponse(
        conversation_id=str(conv_uuid), folders=folders, is_idle=idle,
    )


@router.put(
    "/{conversation_id}",
    response_model=ScopeResponse,
    summary="Replace a conversation's workspace scope (idle only)",
)
async def put_conversation_scope(
    conversation_id: str, body: ScopeUpdateRequest, request: Request,
) -> ScopeResponse:
    """Replace the scope folders for *conversation_id* (rejected while busy).

    Guard order is deliberate: an unwired service is reported first (``503``)
    so a genuinely-missing service never masquerades as a transient ``409``;
    only then is the idle guard applied (``409`` / ``scope_locked`` while a
    turn runs); finally the folders are validated and persisted by the service
    (a bad folder surfaces as ``400``).  The ``scope.updated`` broadcast is
    emitted by :meth:`ScopeService.set_scope` itself, not here.

    Args:
        conversation_id: The owning conversation id (a UUID string).
        body: The new scope folders.
        request: The incoming request (carries ``app.state.context``).

    Returns:
        A :class:`ScopeResponse` echoing the persisted folders with
        ``is_idle=True`` (the conversation was idle for the mutation to apply).

    Raises:
        HTTPException: ``400`` for a bad UUID or a folder that fails
            validation, ``409`` (``scope_locked``) while a turn is in flight,
            ``503`` when the scope service is unavailable.
    """
    conv_uuid = _to_uuid(conversation_id)
    service = _get_scope_service(request)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scope service unavailable",
        )
    if is_conversation_active(str(conv_uuid)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="scope_locked",
        )
    try:
        await service.set_scope(conv_uuid, body.folders)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    folders = await service.get_scope(conv_uuid)
    return ScopeResponse(
        conversation_id=str(conv_uuid), folders=folders, is_idle=True,
    )


@router.delete(
    "/{conversation_id}",
    response_model=ScopeResponse,
    summary="Clear a conversation's workspace scope (idle only)",
)
async def delete_conversation_scope(
    conversation_id: str, request: Request,
) -> ScopeResponse:
    """Clear the scope folders for *conversation_id* (rejected while busy).

    Same guard order as :func:`put_conversation_scope`: ``503`` when the
    service is unwired, then ``409`` / ``scope_locked`` while a turn runs, then
    the clear.  Clearing an already-empty scope is a no-op that still returns
    ``200`` with an empty ``folders`` list; the ``scope.updated`` broadcast is
    emitted by :meth:`ScopeService.clear_scope` itself.

    Args:
        conversation_id: The owning conversation id (a UUID string).
        request: The incoming request (carries ``app.state.context``).

    Returns:
        A :class:`ScopeResponse` with an empty ``folders`` list and
        ``is_idle=True``.

    Raises:
        HTTPException: ``400`` for a bad UUID, ``409`` (``scope_locked``) while
            a turn is in flight, ``503`` when the scope service is unavailable.
    """
    conv_uuid = _to_uuid(conversation_id)
    service = _get_scope_service(request)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scope service unavailable",
        )
    if is_conversation_active(str(conv_uuid)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="scope_locked",
        )
    await service.clear_scope(conv_uuid)
    return ScopeResponse(
        conversation_id=str(conv_uuid), folders=[], is_idle=True,
    )
