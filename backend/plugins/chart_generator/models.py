"""Modelli Pydantic per il plugin chart_generator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class ChartSpec(BaseModel):
    """Specifica completa di un grafico, persistita su disco."""

    chart_id: str
    title: str
    chart_type: str
    description: str = ""
    echarts_option: dict[str, Any]
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class ChartPayload(BaseModel):
    """Payload serializzato nel ToolResult.content (senza echarts_option)."""

    chart_id: str
    title: str
    chart_type: str
    chart_url: str
    created_at: datetime


class ChartListItem(BaseModel):
    """Elemento della lista grafici."""

    chart_id: str
    title: str
    chart_type: str
    description: str
    created_at: datetime
    updated_at: datetime
