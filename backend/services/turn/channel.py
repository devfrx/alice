"""AL\\CE — Inbound interaction channel for turn execution.

This is the **input** counterpart to :class:`~backend.services.turn.sink.WSEventSink`.
Where the sink abstracts *outbound* events (``token``, ``tool_call``, …),
this module abstracts *inbound* request/response interactions and the
single read-pump that owns the WebSocket's ``receive`` side.

Why a single pump
-----------------
Historically several coroutines called ``websocket.receive_text()``
concurrently on the same socket — the per-tool confirmation waiter, the
client-tool waiter, the streaming-phase cancel reader, and the idle
``ws_chat`` loop.  Concurrent receivers on one ASGI WebSocket is undefined
behaviour and was the root of the "v3-1 cancel reader" workaround.

:class:`WebSocketInteractionChannel` replaces all of them with **one**
read-pump task that demultiplexes every inbound frame:

*   a frame whose ``execution_id`` matches a pending request resolves that
    request's future (confirmation, client-tool, future ``ask_user`` …);
*   a ``{"type": "cancel"}`` frame sets the turn's cancel event and unblocks
    every pending request;
*   a stale interaction response (known response type, no matching pending
    request) is discarded;
*   anything else is a user/idle frame and is queued for the ``ws_chat``
    loop to consume via :meth:`next_user_message`.

The contract is expressed as a :class:`Protocol` so executors depend on the
abstraction, never on a raw ``WebSocket``.  :class:`ScriptedInteractionChannel`
is the in-memory test double — the twin of ``RecordingEventSink``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from loguru import logger

from backend.services.turn.sink import is_websocket_closed_runtime_error

if TYPE_CHECKING:  # pragma: no cover — typing only
    from fastapi import WebSocket


# Mapping of semantic interaction *kind* → (outbound frame type, inbound
# response type).  Adding ``ask_user`` here (Fase 4) is a one-line change.
_REQUEST_SPECS: dict[str, tuple[str, str]] = {
    "tool_confirmation": ("tool_confirmation_required", "tool_confirmation_response"),
    "client_tool_call": ("client_tool_call", "client_tool_result"),
    "ask_user": ("ask_user_required", "ask_user_response"),
}

# Inbound frame types that are interaction *responses*.  A response whose
# ``execution_id`` has no pending request is stale and must be discarded
# (never surfaced to the idle loop as a user message).
_RESPONSE_TYPES: frozenset[str] = frozenset(
    resp_type for _, resp_type in _REQUEST_SPECS.values()
)


@runtime_checkable
class InteractionChannel(Protocol):
    """Structural type for the inbound interaction channel.

    Executors use :meth:`request` to perform a round-trip interaction with
    the client (confirmation, client-side execution, user clarification)
    and inspect :attr:`cancelled` / :attr:`connected` to interpret a
    ``None`` outcome.
    """

    async def request(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        execution_id: str,
        timeout_s: float,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any] | None:
        """Send an interaction request and await its correlated response.

        Args:
            kind: Semantic interaction kind (see ``_REQUEST_SPECS``).
            payload: Frame body merged into the outbound request (must not
                include ``type``/``execution_id`` — those are set here).
            execution_id: Correlation id echoed by the client in its reply.
            timeout_s: Maximum seconds to wait for the reply.
            cancel_event: Event whose firing aborts the wait early; defaults
                to the channel's own turn cancel event.

        Returns:
            The parsed response frame, or ``None`` on timeout, cancellation
            or disconnect.  Disambiguate via :attr:`cancelled` /
            :attr:`connected`.
        """
        ...

    @property
    def cancelled(self) -> bool:
        """Whether a cancel signal has been observed for the current turn."""
        ...

    @property
    def connected(self) -> bool:
        """Whether the underlying transport is still usable."""
        ...


@dataclass
class _Pending:
    """A request awaiting its correlated response frame."""

    response_type: str
    future: asyncio.Future[dict[str, Any] | None]


# Sentinel placed on the user-message queue when the socket disconnects so
# that :meth:`next_user_message` can wake and report end-of-stream.
_DISCONNECT_SENTINEL: dict[str, Any] = {"__disconnect__": True}

#: Key set on a user-queue frame the pump could not JSON-decode.  The idle
#: loop turns it into the legacy ``{"type": "error", "content": "Invalid
#: JSON"}`` response instead of silently dropping malformed input.
MALFORMED_FRAME_KEY = "__malformed__"


class WebSocketInteractionChannel:
    """Production channel wrapping a FastAPI ``WebSocket`` with one pump.

    The pump is started with :meth:`start` and stopped with :meth:`aclose`.
    A single turn's cancel lifecycle is scoped with :meth:`begin_turn`,
    which returns the :class:`asyncio.Event` the executor should honour.

    Args:
        ws: The accepted FastAPI ``WebSocket`` to read from / reply on.
        frame_validator: Optional callable injected by the api layer to
            validate outbound frames against the typed contract.  The
            ``services`` layer must never import ``backend.api.ws_schema``
            directly (spec §4).
    """

    def __init__(
        self,
        ws: WebSocket,
        frame_validator: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._ws = ws
        self._pending: dict[str, _Pending] = {}
        self._user_messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._cancel_event = asyncio.Event()
        self._cancelled = False
        self._connected = True
        self._pump_task: asyncio.Task[None] | None = None
        self._validate = frame_validator

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the single read-pump task (idempotent)."""
        if self._pump_task is None:
            self._pump_task = asyncio.create_task(self._pump())

    async def aclose(self) -> None:
        """Stop the pump and fail any still-pending requests."""
        if self._pump_task is not None:
            self._pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._pump_task
            self._pump_task = None
        self._resolve_all(None)

    def begin_turn(self) -> asyncio.Event:
        """Reset cancel state for a new turn and return its cancel event.

        The returned event is the one the pump sets on a ``cancel`` frame,
        so the executor and the pump always agree on the same signal.
        """
        self._cancel_event = asyncio.Event()
        self._cancelled = False
        return self._cancel_event

    @property
    def cancel_event(self) -> asyncio.Event:
        """The current turn's cancel event (set by the pump on cancel)."""
        return self._cancel_event

    @property
    def cancelled(self) -> bool:
        """Whether a cancel frame was seen during the current turn."""
        return self._cancelled or self._cancel_event.is_set()

    @property
    def connected(self) -> bool:
        """Whether the WebSocket read side is still alive."""
        return self._connected

    # ------------------------------------------------------------------
    # Request/response
    # ------------------------------------------------------------------

    async def request(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        execution_id: str,
        timeout_s: float,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any] | None:
        """See :meth:`InteractionChannel.request`."""
        try:
            req_type, resp_type = _REQUEST_SPECS[kind]
        except KeyError as exc:
            raise ValueError(f"Unknown interaction kind: {kind!r}") from exc

        if not self._connected:
            return None

        ce = cancel_event if cancel_event is not None else self._cancel_event
        if ce.is_set():
            return None

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any] | None] = loop.create_future()
        self._pending[execution_id] = _Pending(resp_type, future)
        try:
            sent = await self._send(
                {"type": req_type, "execution_id": execution_id, **payload},
            )
            if not sent:
                return None
            return await self._await_response(future, ce, timeout_s)
        finally:
            self._pending.pop(execution_id, None)

    async def _await_response(
        self,
        future: asyncio.Future[dict[str, Any] | None],
        cancel_event: asyncio.Event,
        timeout_s: float,
    ) -> dict[str, Any] | None:
        """Await *future*, racing the cancel event under a timeout."""
        cancel_waiter = asyncio.ensure_future(cancel_event.wait())
        try:
            waiters: set[asyncio.Future[Any]] = {future, cancel_waiter}
            done, _pending = await asyncio.wait(
                waiters,
                timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if future in done and not future.cancelled():
                # ``None`` here means the pump resolved it as cancel/disconnect.
                return future.result()
            return None
        finally:
            cancel_waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await cancel_waiter

    # ------------------------------------------------------------------
    # Idle / user messages
    # ------------------------------------------------------------------

    async def next_user_message(self) -> dict[str, Any] | None:
        """Return the next non-interaction (user/idle) frame.

        Blocks until the pump routes a user frame.  Returns ``None`` once
        the socket has disconnected and the queue is drained, signalling
        the idle ``ws_chat`` loop to exit.
        """
        msg = await self._user_messages.get()
        if msg is _DISCONNECT_SENTINEL:
            return None
        return msg

    # ------------------------------------------------------------------
    # Pump
    # ------------------------------------------------------------------

    async def _pump(self) -> None:
        """Single reader: demultiplex every inbound frame (see module doc)."""
        # Lazy import keeps this module FastAPI-free at type-check time.
        from fastapi import WebSocketDisconnect

        try:
            while True:
                raw = await self._ws.receive_text()
                self._dispatch(raw)
        except WebSocketDisconnect:
            logger.debug("InteractionChannel pump: client disconnected")
            self._on_disconnect()
        except asyncio.CancelledError:
            raise
        except RuntimeError as exc:
            if not is_websocket_closed_runtime_error(exc):
                logger.warning("InteractionChannel pump runtime error: {}", exc)
            self._on_disconnect()
        except Exception:  # pragma: no cover — defensive
            logger.exception("InteractionChannel pump stopped unexpectedly")
            self._on_disconnect()

    def _dispatch(self, raw: str) -> None:
        """Route a single raw frame to the right consumer."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            # Surface malformed input to the idle loop so it can reply with
            # the legacy "Invalid JSON" error rather than swallow it.
            logger.debug("InteractionChannel: malformed (non-JSON) frame")
            self._user_messages.put_nowait({MALFORMED_FRAME_KEY: True})
            return
        if not isinstance(msg, dict):
            return

        mtype = msg.get("type")
        if mtype == "cancel":
            self._cancelled = True
            self._cancel_event.set()
            self._resolve_all(None)
            logger.debug("InteractionChannel: cancel observed")
            return

        exec_id = msg.get("execution_id")
        if exec_id is not None and exec_id in self._pending:
            pending = self._pending[exec_id]
            if mtype == pending.response_type:
                if not pending.future.done():
                    pending.future.set_result(msg)
                return
            # Wrong response type for this id — stale, drop it.
            logger.debug(
                "InteractionChannel: type '{}' mismatched pending {}",
                mtype, exec_id,
            )
            return

        if mtype in _RESPONSE_TYPES:
            # Interaction response with no pending request → stale, discard.
            logger.debug("InteractionChannel: discarding stale {}", mtype)
            return

        # Anything else is a user/idle frame for the ws_chat loop.
        self._user_messages.put_nowait(msg)

    def _on_disconnect(self) -> None:
        """Mark disconnected, fail pending requests, wake the idle loop."""
        if not self._connected:
            return
        self._connected = False
        self._cancel_event.set()
        self._resolve_all(None)
        self._user_messages.put_nowait(_DISCONNECT_SENTINEL)

    def _resolve_all(self, value: dict[str, Any] | None) -> None:
        """Resolve every pending request future with *value*."""
        for pending in list(self._pending.values()):
            if not pending.future.done():
                pending.future.set_result(value)
        self._pending.clear()

    async def _send(self, frame: dict[str, Any]) -> bool:
        """Send an outbound request frame; return ``False`` on disconnect."""
        if self._validate is not None:
            self._validate(frame)
        from fastapi import WebSocketDisconnect

        try:
            await self._ws.send_json(frame)
            return True
        except WebSocketDisconnect:
            self._on_disconnect()
            return False
        except RuntimeError as exc:
            if is_websocket_closed_runtime_error(exc):
                self._on_disconnect()
                return False
            logger.warning("InteractionChannel: send failed ({})", exc)
            return False


class ScriptedInteractionChannel:
    """In-memory test double — the twin of ``RecordingEventSink``.

    Queue responses (or ``None`` outcomes) up front; each :meth:`request`
    pops the next one and records the call.  Flip :attr:`_cancelled` /
    :attr:`_connected` to exercise the disambiguation branches that follow
    a ``None`` result.

    Args:
        responses: Ordered outcomes returned by successive ``request`` calls
            (a response dict, or ``None`` for timeout/cancel/disconnect).
        is_connected: Initial connection flag.
    """

    def __init__(
        self,
        responses: list[dict[str, Any] | None] | None = None,
        *,
        is_connected: bool = True,
    ) -> None:
        self._responses: list[dict[str, Any] | None] = list(responses or [])
        self.requests: list[dict[str, Any]] = []
        self._cancel_event = asyncio.Event()
        self._cancelled = False
        self._connected = is_connected
        self._user_messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def request(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        execution_id: str,
        timeout_s: float,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any] | None:
        """Record the call and return the next scripted outcome."""
        if kind not in _REQUEST_SPECS:
            raise ValueError(f"Unknown interaction kind: {kind!r}")
        self.requests.append(
            {
                "kind": kind,
                "payload": payload,
                "execution_id": execution_id,
                "timeout_s": timeout_s,
            },
        )
        if self._responses:
            return self._responses.pop(0)
        return None

    def begin_turn(self) -> asyncio.Event:
        """Reset cancel state and return the turn cancel event."""
        self._cancel_event = asyncio.Event()
        self._cancelled = False
        return self._cancel_event

    @property
    def cancel_event(self) -> asyncio.Event:
        return self._cancel_event

    def feed_user_message(self, msg: dict[str, Any]) -> None:
        """Enqueue a user frame for :meth:`next_user_message`."""
        self._user_messages.put_nowait(msg)

    async def next_user_message(self) -> dict[str, Any] | None:
        msg = await self._user_messages.get()
        if msg is _DISCONNECT_SENTINEL:
            return None
        return msg

    @property
    def cancelled(self) -> bool:
        return self._cancelled or self._cancel_event.is_set()

    @cancelled.setter
    def cancelled(self, value: bool) -> None:
        self._cancelled = value

    @property
    def connected(self) -> bool:
        return self._connected

    @connected.setter
    def connected(self, value: bool) -> None:
        self._connected = value


__all__ = [
    "MALFORMED_FRAME_KEY",
    "InteractionChannel",
    "ScriptedInteractionChannel",
    "WebSocketInteractionChannel",
]
