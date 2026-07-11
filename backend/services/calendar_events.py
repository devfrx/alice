"""AL\\CE — Shared calendar domain model and RRULE validation.

``CalendarEvent`` (the SQLModel table) and the RRULE validation helpers
are shared between the calendar plugin (tools) and the calendar REST
routes — defined at the services layer so routes never import plugin
internals (layering contract §4).  The plugin still OWNS the table
lifecycle via ``get_db_models``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from dateutil.rrule import rrulestr
from sqlmodel import Field, SQLModel

# ---------------------------------------------------------------------------
# DB Model
# ---------------------------------------------------------------------------


class CalendarEvent(SQLModel, table=True):
    """A single calendar event stored locally."""

    __tablename__ = "calendar_events"
    __table_args__ = (
        sa.Index("ix_calendar_events_start_time", "start_time"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    start_time: datetime = Field(
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    end_time: datetime = Field(
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    recurrence_rule: str | None = Field(default=None, max_length=512)
    reminder_minutes: int | None = Field(default=None)
    external_id: str | None = Field(default=None, max_length=256)
    external_source: str | None = Field(default=None, max_length=128)
    created_by: str = Field(default="user", max_length=64)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# RRULE validation
# ---------------------------------------------------------------------------

# Maximum RRULE occurrences per event to prevent DoS.
MAX_OCCURRENCES = 500

# Allowed RRULE frequency values.
_ALLOWED_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}


def validate_rrule(rule_str: str) -> str | None:
    """Validate an RRULE string.

    Args:
        rule_str: An RFC 5545 RRULE string to validate.

    Returns:
        An error message string if the rule is invalid, or ``None``
        if the rule is valid (or empty/blank).
    """
    if not rule_str or not rule_str.strip():
        return None
    upper = rule_str.upper()
    freq_found = False
    for part in upper.replace(";", "\n").split("\n"):
        part = part.strip()
        if part.startswith("FREQ="):
            freq = part.split("=", 1)[1]
            if freq not in _ALLOWED_FREQUENCIES:
                return (
                    f"Frequency '{freq}' not allowed "
                    "(use DAILY, WEEKLY, MONTHLY, YEARLY)"
                )
            freq_found = True
    if not freq_found:
        return "RRULE must contain a FREQ= clause"
    try:
        rrulestr(rule_str, dtstart=datetime.now(UTC))
    except Exception as exc:
        return f"Invalid RRULE: {exc}"
    return None
