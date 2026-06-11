"""AL\\CE — Typed WebSocket contract (spec §6).

Every message on the two WS channels (``chat``, ``events``) is a Pydantic
model with a flat envelope (``type`` discriminant + ``origin`` +
``correlation_id?``). The channel unions are injected into the OpenAPI
export (``backend/api/openapi_export.py``) so the frontend consumes them
as generated discriminated TS unions.
"""

from __future__ import annotations

import typing
from typing import Any

from pydantic import TypeAdapter

from backend.api.ws_schema.events import (
    EventsClientMessage,
    EventsServerMessage,
)


def _union_member_types(union: Any) -> frozenset[str]:
    """Extract the ``type`` Literal of every member of a discriminated union."""
    members = typing.get_args(typing.get_args(union)[0])
    found: set[str] = set()
    for member in members:
        literal = member.model_fields["type"].annotation
        found.update(typing.get_args(literal))
    return frozenset(found)


_EVENTS_SERVER_ADAPTER: TypeAdapter[Any] = TypeAdapter(EventsServerMessage)
_EVENTS_CLIENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(EventsClientMessage)

EVENTS_SERVER_TYPES: frozenset[str] = _union_member_types(EventsServerMessage)
EVENTS_CLIENT_TYPES: frozenset[str] = _union_member_types(EventsClientMessage)

#: Union name -> adapter; consumed by the OpenAPI export to inject the WS
#: contract as named components (Task 5 extends this dict for the chat channel).
WS_CONTRACT_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "EventsServerMessage": _EVENTS_SERVER_ADAPTER,
    "EventsClientMessage": _EVENTS_CLIENT_ADAPTER,
}


def validate_events_server(frame: dict[str, Any]) -> Any:
    """Validate a server→client events frame; raises ``ValidationError``."""
    return _EVENTS_SERVER_ADAPTER.validate_python(frame)


def validate_events_client(frame: dict[str, Any]) -> Any:
    """Validate a client→server events frame; raises ``ValidationError``."""
    return _EVENTS_CLIENT_ADAPTER.validate_python(frame)


__all__ = [
    "EVENTS_CLIENT_TYPES",
    "EVENTS_SERVER_TYPES",
    "EventsClientMessage",
    "EventsServerMessage",
    "WS_CONTRACT_ADAPTERS",
    "validate_events_client",
    "validate_events_server",
]
