"""AL\\CE — WebSocket connection manager for background events.

Maintains persistent client connections on ``/api/events/ws`` and
provides ``broadcast()`` / ``send_to()`` for pushing task status
updates and other background events.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket
from loguru import logger


class WSConnectionManager:
    """Manages persistent event WebSocket connections for background push."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        """Accept and register a WebSocket connection.

        Args:
            session_id: Unique identifier for this connection.
            ws: The FastAPI WebSocket instance.
        """
        await ws.accept()
        async with self._lock:
            self._connections[session_id] = ws
        logger.debug("Events WS connected: {}", session_id)

    async def disconnect(self, session_id: str) -> None:
        """Remove a WebSocket connection.

        Args:
            session_id: The session to remove.
        """
        async with self._lock:
            self._connections.pop(session_id, None)
        logger.debug("Events WS disconnected: {}", session_id)

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Send event to all connected clients.

        Snapshots connections under the lock, then sends OUTSIDE it —
        holding an asyncio.Lock during ``await send_json()`` would cause
        starvation if any client is slow to receive.

        Args:
            event: JSON-serializable event dict to broadcast.
        """
        async with self._lock:
            snapshot = list(self._connections.items())

        dead: list[tuple[str, WebSocket]] = []
        for sid, ws in snapshot:
            try:
                await ws.send_json(event)
            except Exception as exc:
                logger.debug("Events WS send failed for {}: {}", sid, exc)
                dead.append((sid, ws))

        if dead:
            async with self._lock:
                for sid, ws in dead:
                    # Only remove if the connection hasn't been replaced
                    # by a new WebSocket since the snapshot was taken.
                    if self._connections.get(sid) is ws:
                        del self._connections[sid]

    async def send_to(self, session_id: str, event: dict[str, Any]) -> None:
        """Send event to a specific session. No-op if disconnected.

        Args:
            session_id: Target session.
            event: JSON-serializable event dict.
        """
        async with self._lock:
            ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_json(event)
            except Exception as exc:
                logger.debug("Events WS send_to failed for {}: {}", session_id, exc)
                async with self._lock:
                    # Only remove if the connection hasn't been replaced.
                    if self._connections.get(session_id) is ws:
                        del self._connections[session_id]

    @property
    def connection_count(self) -> int:
        """Return the number of active connections."""
        return len(self._connections)
