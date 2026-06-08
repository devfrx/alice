"""AL\\CE — Interactive PTY terminal REST API (Fase 7 E1).

Endpoints (mounted under ``/api/terminal``):

* ``GET /{conversation_id}`` — list the conversation's live sessions (+ whether
  the terminal capability is enabled).
* ``POST /{conversation_id}`` — open a new PTY session (scope-confined).
* ``PATCH /{conversation_id}/{session_id}`` — rename and/or (re)assign to agent.
* ``DELETE /{conversation_id}/{session_id}`` — kill a session (process tree).

**No idle guard.**  Unlike scope mutations — which an in-flight turn captured at
start — interactive terminals are session-scoped resources independent of turn
lifecycle: the user explicitly wants to *open a terminal while the agent works*
and *kill a runaway process during a turn*.  So none of these verbs are
``409``-gated, and live keystroke I/O (``terminal.input`` / ``terminal.resize``)
travels over the always-on events WebSocket receive loop, never REST.

Lifecycle broadcasts (``terminal.session_opened`` / ``output`` / ``closed`` /
``renamed`` / ``assigned``) are emitted by the
:class:`~backend.services.terminal.manager.TerminalSessionManager` itself, not
here.  The whole terminal capability is gated by ``config.terminal.enabled``
(off by default); when disabled, mutating verbs return ``403`` and the list
endpoint reports ``enabled: false`` so the UI can show a clear hint.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.services.terminal.manager import TerminalSessionManager
from backend.services.terminal.pty_backend import PtySpawnError

router = APIRouter(prefix="/terminal", tags=["terminal"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TerminalSessionOut(BaseModel):
    """A single live terminal session (mirrors ``TerminalSession.snapshot``)."""

    id: str
    conversation_id: str
    title: str
    cwd: str
    rows: int
    cols: int
    agent_assigned: bool
    created_at: str
    pid: int | None
    alive: bool


class TerminalListResponse(BaseModel):
    """The conversation's sessions plus the capability flag."""

    enabled: bool
    sessions: list[TerminalSessionOut]


class TerminalCreateRequest(BaseModel):
    """Request body for ``POST /terminal/{conversation_id}``."""

    cwd: str | None = None
    title: str | None = None
    rows: int = Field(default=24, ge=1, le=512)
    cols: int = Field(default=80, ge=1, le=512)
    assign_to_agent: bool = False


class TerminalUpdateRequest(BaseModel):
    """Request body for ``PATCH /terminal/{conversation_id}/{session_id}``.

    Both fields are optional: set ``title`` to rename, set ``assign_to_agent``
    to ``true`` to make this the conversation's agent session.
    """

    title: str | None = None
    assign_to_agent: bool | None = None


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


def _get_manager(request: Request) -> TerminalSessionManager | None:
    """Fetch the terminal manager off ``app.state.context`` (``None`` if absent)."""
    ctx = getattr(request.app.state, "context", None)
    mgr: TerminalSessionManager | None = (
        getattr(ctx, "terminal_session_manager", None) if ctx else None
    )
    return mgr


def _terminal_enabled(request: Request) -> bool:
    """Whether the terminal capability is enabled in config."""
    ctx = getattr(request.app.state, "context", None)
    if ctx is None:
        return False
    return bool(ctx.config.terminal.enabled)


def _require_enabled_manager(request: Request) -> TerminalSessionManager:
    """Return the manager, or raise 403 (disabled) / 503 (unwired)."""
    if not _terminal_enabled(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="terminal_disabled",
        )
    mgr = _get_manager(request)
    if mgr is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Terminal service unavailable",
        )
    return mgr


def _out(snapshot: dict[str, Any]) -> TerminalSessionOut:
    """Build the response model from a session snapshot."""
    return TerminalSessionOut(**snapshot)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/{conversation_id}",
    response_model=TerminalListResponse,
    summary="List a conversation's interactive terminal sessions",
)
async def list_terminals(
    conversation_id: str, request: Request,
) -> TerminalListResponse:
    """Return the live sessions for *conversation_id* plus the enabled flag.

    Read-only and always succeeds for a valid id: an unwired manager or a
    disabled terminal both yield an empty list (with ``enabled`` reflecting
    config).

    Raises:
        HTTPException: ``400`` when *conversation_id* is not a valid UUID.
    """
    conv_uuid = _to_uuid(conversation_id)
    enabled = _terminal_enabled(request)
    mgr = _get_manager(request)
    sessions = mgr.list_sessions(str(conv_uuid)) if mgr else []
    return TerminalListResponse(
        enabled=enabled,
        sessions=[_out(s.snapshot()) for s in sessions],
    )


@router.post(
    "/{conversation_id}",
    response_model=TerminalSessionOut,
    summary="Open a new interactive terminal session (scope-confined)",
)
async def create_terminal(
    conversation_id: str, body: TerminalCreateRequest, request: Request,
) -> TerminalSessionOut:
    """Spawn a PTY session confined to the conversation's workspace scope.

    Raises:
        HTTPException: ``400`` for a bad UUID / no scope set / out-of-scope cwd /
            session cap reached, ``403`` (``terminal_disabled``) when off,
            ``503`` when the manager is unwired or the PTY backend is missing.
    """
    conv_uuid = _to_uuid(conversation_id)
    mgr = _require_enabled_manager(request)
    try:
        session = await mgr.create_session(
            str(conv_uuid),
            cwd=body.cwd,
            title=body.title,
            rows=body.rows,
            cols=body.cols,
            assign_to_agent=body.assign_to_agent,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc
    except PtySpawnError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        ) from exc
    return _out(session.snapshot())


@router.patch(
    "/{conversation_id}/{session_id}",
    response_model=TerminalSessionOut,
    summary="Rename and/or assign a terminal session to the agent",
)
async def update_terminal(
    conversation_id: str,
    session_id: str,
    body: TerminalUpdateRequest,
    request: Request,
) -> TerminalSessionOut:
    """Rename and/or (re)assign a session; returns the updated snapshot.

    Raises:
        HTTPException: ``400`` for a bad UUID, ``403`` when disabled, ``404``
            when the session is unknown, ``503`` when unwired.
    """
    conv_uuid = _to_uuid(conversation_id)
    mgr = _require_enabled_manager(request)
    conv = str(conv_uuid)
    if mgr.get_session(conv, session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown_session")
    if body.title is not None:
        await mgr.rename(conv, session_id, body.title)
    if body.assign_to_agent:
        await mgr.assign_to_agent(conv, session_id)
    session = mgr.get_session(conv, session_id)
    if session is None:  # pragma: no cover — would mean a concurrent kill
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown_session")
    return _out(session.snapshot())


@router.delete(
    "/{conversation_id}/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Kill a terminal session (its whole process tree)",
)
async def delete_terminal(
    conversation_id: str, session_id: str, request: Request,
) -> None:
    """Terminate a session and its process tree.

    Not idle-guarded by design — killing a runaway process is the terminal's
    job, during a turn as much as after it.

    Raises:
        HTTPException: ``400`` for a bad UUID, ``403`` when disabled, ``404``
            when the session is unknown, ``503`` when unwired.
    """
    conv_uuid = _to_uuid(conversation_id)
    mgr = _require_enabled_manager(request)
    killed = await mgr.kill_session(str(conv_uuid), session_id)
    if not killed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown_session")
