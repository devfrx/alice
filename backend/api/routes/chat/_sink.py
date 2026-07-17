"""AL\\CE — Chat done-frame event sink (api-layer owned).

The AgentEngine (``services/agent``) emits its own wire frames through the
:class:`~backend.services.agent.adapters.ws.WsEventPort`.  The post-turn
persistence path (:mod:`._persist`), however, still needs a thin outbound
sink to deliver the ``done`` / ``context_info`` / compression frames it
builds itself — a concern that belongs to the api layer, not to the engine.

This module owns that sink after the demolition of ``services/turn`` (Task
19).  It intentionally lives in the api layer: it wraps a FastAPI
``WebSocket`` and is consumed only by the chat route package.

Public surface:
    * :class:`WSEventSink` — structural protocol (``send`` + ``is_connected``).
    * :class:`WebSocketEventSink` — production sink over a FastAPI WebSocket.
    * :class:`NullEventSink` — drop sink for headless (autonomous) turns.
    * :func:`is_websocket_closed_runtime_error` — closed-socket detector.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from loguru import logger
from starlette.websockets import WebSocketState

if TYPE_CHECKING:  # pragma: no cover — typing only
    from fastapi import WebSocket


_CLOSED_WEBSOCKET_RUNTIME_MARKERS = (
    "WebSocket is not connected",
    "Cannot call \"send\" once a close message has been sent",
    "Cannot call \"receive\" once a disconnect message has been received",
    "Unexpected ASGI message \"websocket.send\"",
)


def is_websocket_closed_runtime_error(exc: RuntimeError) -> bool:
    """Return whether *exc* is Starlette reporting a closed WebSocket.

    Starlette sometimes surfaces normal close races as ``RuntimeError``
    instead of :class:`fastapi.WebSocketDisconnect`; the message can even
    say that ``accept()`` was not called although the socket had already
    been accepted and then closed.  Treat only these known transport-state
    messages as disconnects so unrelated runtime errors still surface.
    """
    message = str(exc)
    return any(marker in message for marker in _CLOSED_WEBSOCKET_RUNTIME_MARKERS)


@runtime_checkable
class WSEventSink(Protocol):
    """Structural type for outbound event sinks used by the persist path.

    The persist path emits events as plain JSON-serialisable dicts
    (``done``, ``context_info``, ``context_compression_*`` …).
    Implementations decide how to deliver them (WebSocket, drop, buffer).
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

    Args:
        ws: The accepted FastAPI ``WebSocket`` to forward events to.
        frame_validator: Optional callable injected by the api layer to
            validate outbound frames against the typed contract.
    """

    def __init__(
        self,
        ws: WebSocket,
        frame_validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._ws = ws
        self._closed = False
        self._validate = frame_validator

    async def send(self, event: dict[str, Any]) -> None:
        """Send ``event`` as JSON; swallow disconnect / runtime errors.

        Callers inspect :attr:`is_connected` to decide whether to keep
        emitting after a failure, so this method never raises on
        transport-level issues.
        """
        if self._validate is not None:
            self._validate(event)
        # Lazy import keeps this module free of FastAPI at type-check time.
        from fastapi import WebSocketDisconnect

        try:
            await self._ws.send_json(event)
        except WebSocketDisconnect:
            self._closed = True
            logger.debug("WebSocketEventSink: client disconnected on send")
        except RuntimeError as exc:
            # Typical when the socket has already been closed.
            if is_websocket_closed_runtime_error(exc):
                self._closed = True
            logger.debug("WebSocketEventSink: send failed ({})", exc)

    @property
    def is_connected(self) -> bool:
        """Return ``True`` while the WebSocket is in CONNECTED state."""
        try:
            return (
                not self._closed
                and self._ws.client_state == WebSocketState.CONNECTED
                and self._ws.application_state == WebSocketState.CONNECTED
            )
        except Exception:  # pragma: no cover — defensive
            return False


class NullEventSink:
    """Sink for headless (autonomous) turns: no surface, events dropped.

    Observability of autonomous turns rides the background-task events
    (Fase 8), not the chat stream — there is no client on the other side.
    """

    async def send(self, event: dict[str, Any]) -> None:
        """Drop ``event``; a headless turn has no outbound transport."""
        return None

    @property
    def is_connected(self) -> bool:
        """Always ``True`` — the (null) surface can never be lost."""
        return True


__all__ = [
    "NullEventSink",
    "WSEventSink",
    "WebSocketEventSink",
    "is_websocket_closed_runtime_error",
]
