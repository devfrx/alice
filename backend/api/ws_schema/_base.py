"""AL\\CE — Flat WS envelope shared by every WebSocket message (spec §6).

Every WS frame on both channels is a Pydantic model carrying:

* ``type`` — the Literal discriminant (declared per message);
* ``origin`` — who caused the frame (``user`` | ``agent`` | ``system``);
* ``correlation_id`` — reserved for request/response correlation in the
  Command Layer RPC (spec §7); interaction frames keep their existing
  ``execution_id`` field unchanged.

The envelope is FLAT — no ``payload`` wrapper. The current wire format is
flat and wrapping would force a synchronized FE+BE migration for zero
added guarantee (design decision, 2026-06-10).

``origin`` and ``correlation_id`` have defaults so today's frames (which
do not carry them yet) validate unchanged: the schema documents the
target envelope while staying truthful about the wire.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Origin = Literal["user", "agent", "system"]


class WsFrame(BaseModel):
    """Base class for every WS message; ``extra='forbid'`` keeps drift loud."""

    model_config = ConfigDict(extra="forbid")

    origin: Origin = "system"
    correlation_id: str | None = None


class EventsServerFrame(WsFrame):
    """Server→client frame on the events channel (background push)."""


class ChatServerFrame(WsFrame):
    """Server→client frame on the chat channel (turn streaming)."""

    origin: Origin = "agent"


class ClientFrame(WsFrame):
    """Client→server frame on either channel."""

    origin: Origin = "user"
