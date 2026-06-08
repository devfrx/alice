"""AL\\CE — WebSocket endpoint for background event streaming.

Clients connect once at startup to ``/api/events/ws`` and receive
push notifications whenever a background task completes, fails,
or changes status.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.core.context import AppContext

router = APIRouter(prefix="/events", tags=["events"])

# Per-IP connection tracking for event WebSocket connections.
_event_connections: dict[str, int] = defaultdict(int)
_event_lock = asyncio.Lock()
_MAX_EVENT_CONNECTIONS_PER_IP = 5


async def _handle_terminal_frame(
    ctx: AppContext, frame_type: str, data: dict[str, Any],
) -> None:
    """Route a live terminal control frame to the session manager.

    Handles ``terminal.input`` (``{conversation_id, session_id, data}``) and
    ``terminal.resize`` (``{conversation_id, session_id, rows, cols}``).
    Best-effort: unknown sessions and a disabled/unwired manager are silently
    ignored — the user simply sees no echo.  Never raises (a bad frame must not
    drop the events socket).
    """
    mgr = getattr(ctx, "terminal_session_manager", None)
    if mgr is None or not ctx.config.terminal.enabled:
        return
    conv = data.get("conversation_id")
    session_id = data.get("session_id")
    if not isinstance(conv, str) or not isinstance(session_id, str):
        return
    try:
        if frame_type == "terminal.input":
            payload = data.get("data")
            if isinstance(payload, str):
                await mgr.write_input(conv, session_id, payload)
        else:  # terminal.resize
            rows = data.get("rows")
            cols = data.get("cols")
            if isinstance(rows, int) and isinstance(cols, int):
                await mgr.resize(conv, session_id, rows, cols)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("terminal control frame failed: {}", exc)


@router.websocket("/ws")
async def ws_events(websocket: WebSocket) -> None:
    """Persistent push channel for background task events.

    Clients connect once at startup and receive push events whenever
    a background task completes, fails, or changes status.
    """
    ctx: AppContext = websocket.app.state.context
    client_ip = websocket.client.host if websocket.client else "unknown"

    if ctx.ws_connection_manager is None:
        await websocket.accept()
        await websocket.close(code=1011, reason="Events service not available")
        return

    async with _event_lock:
        if _event_connections.get(client_ip, 0) >= _MAX_EVENT_CONNECTIONS_PER_IP:
            await websocket.accept()
            await websocket.close(
                code=1008, reason="Too many event connections",
            )
            return
        _event_connections[client_ip] += 1

    session_id = f"events-{uuid.uuid4().hex[:12]}"
    try:
        await ctx.ws_connection_manager.connect(session_id, websocket)

        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(), timeout=60.0,
                )
                mtype = data.get("type")
                if mtype == "ping":
                    await websocket.send_json({"type": "pong"})
                elif mtype in ("terminal.input", "terminal.resize"):
                    # Live terminal keystrokes / resizes. Never idle-guarded —
                    # the user types during a turn. Output flows back out via
                    # the broadcast channel (terminal.output events).
                    await _handle_terminal_frame(ctx, mtype, data)
            except TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                break
            except ValueError:
                # Malformed JSON from client — ignore and continue.
                logger.debug("Events WS {}: ignoring invalid JSON", session_id)
                continue
    except Exception as exc:
        logger.debug("Events WS error for {}: {}", session_id, exc)
    finally:
        async with _event_lock:
            _event_connections[client_ip] = max(
                0, _event_connections.get(client_ip, 1) - 1,
            )
            if _event_connections.get(client_ip, 0) <= 0:
                _event_connections.pop(client_ip, None)
        await ctx.ws_connection_manager.disconnect(session_id)
