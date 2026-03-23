"""AL\\CE — WebSocket endpoint for background event streaming.

Clients connect once at startup to ``/api/events/ws`` and receive
push notifications whenever a background task completes, fails,
or changes status.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.core.context import AppContext

router = APIRouter(prefix="/events", tags=["events"])

# Per-IP connection tracking for event WebSocket connections.
_event_connections: dict[str, int] = defaultdict(int)
_event_lock = asyncio.Lock()
_MAX_EVENT_CONNECTIONS_PER_IP = 5


@router.websocket("/ws")
async def ws_events(websocket: WebSocket) -> None:
    """Persistent push channel for background task events.

    Clients connect once at startup and receive push events whenever
    a background task completes, fails, or changes status.
    """
    ctx: AppContext = websocket.app.state.context
    if ctx.ws_connection_manager is None:
        await websocket.close(code=1011, reason="Events service not available")
        return

    client_ip = websocket.client.host if websocket.client else "unknown"

    async with _event_lock:
        if _event_connections.get(client_ip, 0) >= _MAX_EVENT_CONNECTIONS_PER_IP:
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
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                break
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
