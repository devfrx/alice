"""AL\\CE — Runtime wire guard for outbound WS frames.

Validates outgoing frames against the typed contract. Outside tests a
violation only logs a warning (a malformed push must never take down a
turn); under ``ALICE_WS_STRICT_CONTRACTS=1`` (set by the test suite) it
raises so drift fails loudly.

The validators are plain callables meant to be INJECTED into the send
chokepoints (``WSConnectionManager`` on the events channel,
``TransportEventSink`` on the chat persist path) by the api layer /
composition root — ``services`` modules must never import this package
(spec §4).

The AgentEngine's own wire (``services/agent/adapters/wire.py``) is NOT one
of those chokepoints: it is not wired to these validators. Its guarantee is
by-construction instead — every engine frame is built THROUGH its Pydantic
contract model, so a frame that does not validate cannot be constructed. The
runtime validator here is applied by ``TransportEventSink`` on the persist
path.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from loguru import logger
from pydantic import ValidationError

from backend.api.ws_schema import validate_chat_server, validate_events_server

_STRICT_ENV = "ALICE_WS_STRICT_CONTRACTS"


class WsContractViolation(AssertionError):  # noqa: N818
    """An outbound WS frame does not match the typed contract."""


def _validate(channel: Literal["chat", "events"], frame: dict[str, Any]) -> None:
    try:
        if channel == "chat":
            validate_chat_server(frame)
        else:
            validate_events_server(frame)
    except ValidationError as exc:
        message = f"WS contract violation on '{channel}' channel: {exc}"
        if os.environ.get(_STRICT_ENV) == "1":
            raise WsContractViolation(message) from exc
        logger.warning(message)


def chat_frame_validator(frame: dict[str, Any]) -> None:
    """Validate a server→client chat frame (inject into chat send paths)."""
    _validate("chat", frame)


def events_frame_validator(frame: dict[str, Any]) -> None:
    """Validate a server→client events frame (inject into the WS manager)."""
    _validate("events", frame)


__all__ = [
    "WsContractViolation",
    "chat_frame_validator",
    "events_frame_validator",
]
