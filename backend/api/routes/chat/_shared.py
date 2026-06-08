"""AL\\CE — Chat package shared state and primitives.

Holds the singleton ``APIRouter`` plus the small, dependency-light helpers
and module-level state shared across the chat route modules
(``ws``, ``conversations``, ``io``) and the internal helpers.

Splitting these out keeps every route module importing **one** router
instance so the ``@router`` decorators register on the same object.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.core.config import PROJECT_ROOT
from backend.core.context import AppContext
from backend.services.turn import is_websocket_closed_runtime_error

router = APIRouter(tags=["chat"])

# Base path for uploaded files.
_UPLOADS_BASE: Path = (PROJECT_ROOT / "data" / "uploads").resolve()

# Active WebSocket connections per IP (for rate limiting).
_ws_connections: dict[str, int] = defaultdict(int)
# Per-loop WS locks: maps event-loop id → asyncio.Lock.  This allows tests
# that run in multiple event loops (e.g. threads with TestClient) to each
# get a lock bound to the correct loop.
_ws_locks: dict[int, asyncio.Lock] = {}

# Conversations with an in-flight turn (Fase 6b idle-guard).  A conversation
# in this set is "busy": workspace-scope mutations are rejected (409) until the
# turn completes.  Membership is bound to the turn lifecycle in ``ws.py``.
_active_conversations: set[str] = set()


def is_conversation_active(conversation_id: str) -> bool:
    """Return whether a turn is currently executing for the conversation.

    Args:
        conversation_id: Canonical string form of the conversation id.

    Returns:
        ``True`` while a turn is in flight for the conversation, else ``False``.
    """
    return conversation_id in _active_conversations


@contextlib.contextmanager
def conversation_active(conversation_id: str) -> Iterator[None]:
    """Mark a conversation busy for the duration of a turn (idle-guard).

    The id is added on entry and **always** discarded on exit — normal
    completion, cancellation, or error — so the idle state stays bound to the
    turn lifecycle and a crashed turn never leaves a conversation wedged
    "busy".

    Args:
        conversation_id: Canonical string form of the conversation id.

    Yields:
        ``None`` for the duration of the active turn.
    """
    _active_conversations.add(conversation_id)
    try:
        yield
    finally:
        _active_conversations.discard(conversation_id)


def _get_ws_lock() -> asyncio.Lock:
    """Return an ``asyncio.Lock`` bound to the *current* event loop."""
    loop = asyncio.get_running_loop()
    lock = _ws_locks.get(id(loop))
    if lock is None:
        lock = asyncio.Lock()
        _ws_locks[id(loop)] = lock
    return lock


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ctx(ws_or_request: Any) -> AppContext:
    """Extract the ``AppContext`` from the ASGI app state."""
    return ws_or_request.app.state.context


async def _receive_ws_text(websocket: WebSocket) -> str:
    """Receive text while normalising closed-socket runtime errors."""
    try:
        return await websocket.receive_text()
    except RuntimeError as exc:
        if is_websocket_closed_runtime_error(exc):
            raise WebSocketDisconnect() from exc
        raise


def _attachment_url(file_path: str) -> str:
    """Build a safe ``/uploads/…`` URL from an attachment's file_path.

    Uses :meth:`pathlib.Path.relative_to` instead of string splitting
    to avoid path-traversal issues.  Components are percent-encoded.
    """
    try:
        relative = Path(file_path).resolve().relative_to(_UPLOADS_BASE)
        # Use POSIX-style separators so the URL works on Windows where
        # ``Path.__str__`` would otherwise yield backslashes (which the
        # static-file mount at ``/uploads`` does not match).
        return f"/uploads/{quote(relative.as_posix(), safe='/')}"
    except ValueError:
        logger.warning("Attachment path outside uploads base: {}", file_path)
        return ""
