"""Modelli Pydantic per il plugin whiteboard (tldraw)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class SimpleShape(BaseModel):
    """Astrazione shape LLM-friendly per generare contenuto tldraw."""

    type: Literal["geo", "note", "arrow", "text"]
    id: str | None = None
    x: float = 0
    y: float = 0
    w: float = 200
    h: float = 100
    text: str = ""
    color: Literal[
        "cream", "sage", "amber", "steel", "coral", "lavender", "teal"
    ] = "cream"
    from_id: str | None = None
    to_id: str | None = None
    geo: Literal["rectangle", "ellipse", "diamond", "hexagon"] = "rectangle"


class WhiteboardSpec(BaseModel):
    """Specifica completa di una lavagna, persistita su disco."""

    board_id: str
    title: str
    description: str = ""
    conversation_id: str | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WhiteboardPayload(BaseModel):
    """Payload serializzato nel ToolResult.content (senza snapshot)."""

    board_id: str
    title: str
    board_url: str
    conversation_id: str | None = None
    created_at: datetime


class WhiteboardListItem(BaseModel):
    """Elemento della lista lavagne."""

    board_id: str
    title: str
    description: str
    conversation_id: str | None = None
    created_at: datetime
    updated_at: datetime
    shape_count: int = 0
