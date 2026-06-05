"""AL\\CE — Chat package shared state and primitives.

Holds the singleton ``APIRouter`` plus the small, dependency-light helpers
and module-level state shared across the chat route modules
(``ws``, ``conversations``, ``io``) and the internal helpers.

Splitting these out keeps every route module importing **one** router
instance so the ``@router`` decorators register on the same object.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
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
