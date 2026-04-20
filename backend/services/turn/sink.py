"""AL\\CE — WebSocket event sinks for turn execution.

Defines the :class:`WSEventSink` protocol used by the turn executors
together with two concrete implementations:

*   :class:`WebSocketEventSink` — production sink wrapping a FastAPI
    :class:`fastapi.WebSocket`.  Exposes ``_ws`` as a Phase 1 escape
    hatch so :func:`backend.api.routes._tool_loop.run_tool_loop` (which
    still expects a raw WebSocket) keeps working unchanged.
*   :class:`RecordingEventSink` — in-memory test double that captures
    every event emitted by an executor.

See ``alice/agent_loop_plan.md`` §3.3 for the full contract.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from loguru import logger
from starlette.websockets import WebSocketState

if TYPE_CHECKING:  # pragma: no cover — typing only
    from fastapi import WebSocket


@runtime_checkable
class WSEventSink(Protocol):
    """Structural type for outbound event sinks used by turn executors.

    Executors emit events as plain JSON-serialisable dicts (``token``,
    ``thinking``, ``tool_call``, ``done``, ``error``, ``agent.*`` …).
    Implementations decide how to deliver them (WebSocket, buffer, …).
    """

    async def send(self, event: dict[str, Any]) -> None:
        """Deliver ``event`` to the underlying transport."""
        ...

    @property
    def is_connected(self) -> bool:
        """Whether the underlying transport is still usable."""
        ...


class WebSocketEventSink:
    """Production sink that forwards events to a FastAPI WebSocket.

    The raw WebSocket is exposed via :attr:`_ws` because the legacy
    :func:`backend.api.routes._tool_loop.run_tool_loop` still accepts a
    ``WebSocket`` directly (Phase 1 escape hatch — see plan §3.3).

    Args:
        ws: The accepted FastAPI ``WebSocket`` to forward events to.
    """

    def __init__(self, ws: "WebSocket") -> None:
        self._ws = ws

    async def send(self, event: dict[str, Any]) -> None:
        """Send ``event`` as JSON; swallow disconnect / runtime errors.

        The executor inspects :attr:`is_connected` (or its own cancel
        signal) to decide whether to keep streaming after a failure, so
        this method never raises on transport-level issues.
        """
        # Lazy import keeps this module free of FastAPI at type-check time.
        from fastapi import WebSocketDisconnect

        try:
            await self._ws.send_json(event)
        except WebSocketDisconnect:
            logger.debug("WebSocketEventSink: client disconnected on send")
        except RuntimeError as exc:
            # Typical when the socket has already been closed.
            logger.debug("WebSocketEventSink: send failed ({})", exc)

    @property
    def is_connected(self) -> bool:
        """Return ``True`` while the WebSocket is in CONNECTED state."""
        try:
            return self._ws.client_state == WebSocketState.CONNECTED
        except Exception:  # pragma: no cover — defensive
            return False


class RecordingEventSink:
    """Test double that records every event in :attr:`events`.

    Args:
        is_connected: Initial connection flag (default ``True``).  Tests
            can flip :attr:`_is_connected` to simulate a disconnect.
    """

    _ws: None = None  # No real WebSocket — the executor must handle this.

    def __init__(self, *, is_connected: bool = True) -> None:
        self.events: list[dict[str, Any]] = []
        self._is_connected = is_connected

    async def send(self, event: dict[str, Any]) -> None:
        """Append ``event`` to :attr:`events`.

        The event is shallow-copied so subsequent caller-side mutations
        do not affect the recorded history.
        """
        with contextlib.suppress(Exception):
            event = dict(event)
        self.events.append(event)

    @property
    def is_connected(self) -> bool:
        """Mirror the configurable connection flag."""
        return self._is_connected

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        self._is_connected = value


__all__ = [
    "RecordingEventSink",
    "WSEventSink",
    "WebSocketEventSink",
]
