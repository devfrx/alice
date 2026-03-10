"""O.M.N.I.A. — Calendar plugin.

Local calendar with events, reminders, and RRULE recurrence support.
Provides five tools: create_event, list_events, update_event,
delete_event, and get_today_summary.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from dateutil import parser as dt_parser
from dateutil.rrule import rrulestr
from loguru import logger
from sqlmodel import Field, SQLModel, select
from zoneinfo import ZoneInfo

from backend.core.event_bus import OmniaEvent
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.calendar.utils import (
    MAX_OCCURRENCES,
    validate_rrule,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext


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
        default_factory=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# RRULE expansion
# ---------------------------------------------------------------------------


# Maximum RRULE occurrences per event to prevent DoS.
_MAX_OCCURRENCES = MAX_OCCURRENCES

# Allowed RRULE frequency values (kept for _expand_recurring).
_ALLOWED_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}


def _validate_rrule(rule_str: str) -> str | None:
    """Validate an RRULE string. Delegates to shared utility."""
    return validate_rrule(rule_str)


def _expand_recurring(
    events: list[CalendarEvent],
    range_start: datetime,
    range_end: datetime,
    tz: ZoneInfo,
) -> list[CalendarEvent]:
    """Expand recurring events into individual occurrences within range."""

    def _utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    result: list[CalendarEvent] = []
    for ev in events:
        if not ev.recurrence_rule:
            result.append(ev)
            continue

        start = _utc(ev.start_time)
        end = _utc(ev.end_time)
        duration = end - start

        try:
            rule = rrulestr(ev.recurrence_rule, dtstart=start.astimezone(tz))
            occurrences = rule.between(
                range_start.astimezone(tz),
                range_end.astimezone(tz),
                inc=True,
            )
            if len(occurrences) > _MAX_OCCURRENCES:
                logger.warning(
                    "RRULE for event {} produced {} occurrences, "
                    "capping to {}",
                    ev.id, len(occurrences), _MAX_OCCURRENCES,
                )
                occurrences = occurrences[:_MAX_OCCURRENCES]
            for occ in occurrences:
                occ_utc = occ.astimezone(timezone.utc)
                virtual = CalendarEvent(
                    id=ev.id,
                    title=ev.title,
                    description=ev.description,
                    start_time=occ_utc,
                    end_time=occ_utc + duration,
                    recurrence_rule=ev.recurrence_rule,
                    reminder_minutes=ev.reminder_minutes,
                    external_id=ev.external_id,
                    external_source=ev.external_source,
                    created_by=ev.created_by,
                    created_at=ev.created_at,
                )
                result.append(virtual)
        except Exception as exc:
            logger.warning(
                "Failed to expand RRULE for event {}: {}", ev.id, exc,
            )
            result.append(ev)

    result.sort(key=lambda e: _utc(e.start_time))
    return result


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------


class CalendarPlugin(BasePlugin):
    """Local calendar with events, reminders, and RRULE recurrence."""

    plugin_name: str = "calendar"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Local calendar with events, reminders and RRULE recurrence."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 30

    def __init__(self) -> None:
        super().__init__()
        self._tz: ZoneInfo = ZoneInfo("Europe/Rome")
        self._reminder_check_interval_s: int = 60
        self._reminder_task: asyncio.Task | None = None
        self._fired_reminders: set[tuple[uuid.UUID, str]] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Store config-driven timezone and reminder interval.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)
        self._tz = ZoneInfo(ctx.config.calendar.timezone)
        self._reminder_check_interval_s = (
            ctx.config.calendar.reminder_check_interval_s
        )
        self.logger.info(
            "Calendar plugin ready (tz={}, reminder_interval={}s)",
            self._tz,
            self._reminder_check_interval_s,
        )

    async def on_app_startup(self) -> None:
        """Start the background reminder loop."""
        self._reminder_task = asyncio.create_task(
            self._reminder_loop(), name="calendar-reminder-loop",
        )
        self.logger.debug("Reminder loop started")

    async def on_app_shutdown(self) -> None:
        """Cancel the background reminder loop."""
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
            try:
                await self._reminder_task
            except asyncio.CancelledError:
                pass
            self.logger.debug("Reminder loop stopped")

    async def cleanup(self) -> None:
        """Cancel the reminder task and release resources."""
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
            try:
                await self._reminder_task
            except asyncio.CancelledError:
                pass
        self._fired_reminders.clear()
        await super().cleanup()

    # ------------------------------------------------------------------
    # Dependency / health
    # ------------------------------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Return missing optional dependencies (none for calendar).

        Returns:
            An empty list — python-dateutil is a hard dependency.
        """
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Report connection status.

        Returns:
            ``ConnectionStatus.CONNECTED`` — local DB-backed plugin.
        """
        return ConnectionStatus.CONNECTED

    # ------------------------------------------------------------------
    # DB models
    # ------------------------------------------------------------------

    @classmethod
    def get_db_models(cls) -> list[type]:
        """Return the CalendarEvent model for auto-table creation.

        Returns:
            A single-element list containing :class:`CalendarEvent`.
        """
        return [CalendarEvent]

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return the five calendar tool definitions.

        Returns:
            A list of ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="create_event",
                description=(
                    "Create a new calendar event. "
                    "IMPORTANT: use the current date/time from system "
                    "context to resolve relative expressions like "
                    "'domani', 'oggi', 'prossima settimana', etc. "
                    "Dates must be ISO 8601 "
                    "(e.g. '2025-03-15T10:00:00'). Past dates are allowed "
                    "for logging historical events. "
                    "recurrence_rule accepts an RFC 5545 RRULE string "
                    "(allowed frequencies: DAILY, WEEKLY, MONTHLY, YEARLY)."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Event title.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional event description.",
                        },
                        "start": {
                            "type": "string",
                            "description": (
                                "Start datetime in ISO 8601 format."
                            ),
                        },
                        "end": {
                            "type": "string",
                            "description": (
                                "End datetime in ISO 8601 format."
                            ),
                        },
                        "reminder_minutes": {
                            "type": "integer",
                            "description": (
                                "Minutes before the event to trigger "
                                "a reminder (must be >= 1)."
                            ),
                            "minimum": 1,
                        },
                        "recurrence_rule": {
                            "type": "string",
                            "description": (
                                "RFC 5545 RRULE string "
                                "(e.g. 'FREQ=WEEKLY;BYDAY=MO,WE,FR' or "
                                "'FREQ=MONTHLY;BYMONTHDAY=15;COUNT=12')."
                            ),
                        },
                    },
                    "required": ["title", "start", "end"],
                },
                risk_level="safe",
            ),
            ToolDefinition(
                name="list_events",
                description=(
                    "List calendar events in a date range. Returns up to "
                    "max_results events ordered by start time."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": (
                                "Start of date range (ISO 8601). "
                                "Defaults to today."
                            ),
                        },
                        "end_date": {
                            "type": "string",
                            "description": (
                                "End of date range (ISO 8601). "
                                "Defaults to 7 days from start_date."
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": (
                                "Maximum number of events to return "
                                "(default 20)."
                            ),
                        },
                    },
                },
                risk_level="safe",
            ),
            ToolDefinition(
                name="update_event",
                description=(
                    "Update an existing calendar event by ID. Only the "
                    "provided fields are updated (partial update); "
                    "omitted fields remain unchanged."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "UUID of the event to update.",
                        },
                        "title": {
                            "type": "string",
                            "description": "New title.",
                        },
                        "description": {
                            "type": "string",
                            "description": "New description.",
                        },
                        "start": {
                            "type": "string",
                            "description": "New start datetime (ISO 8601).",
                        },
                        "end": {
                            "type": "string",
                            "description": "New end datetime (ISO 8601).",
                        },
                        "reminder_minutes": {
                            "type": "integer",
                            "description": (
                                "Minutes before the event to trigger "
                                "a reminder (must be >= 1, or null to "
                                "remove)."
                            ),
                            "minimum": 1,
                        },
                        "recurrence_rule": {
                            "type": "string",
                            "description": (
                                "RFC 5545 RRULE string "
                                "(e.g. 'FREQ=WEEKLY;BYDAY=MO,WE,FR'). "
                                "Pass null to remove recurrence."
                            ),
                        },
                    },
                    "required": ["event_id"],
                },
                risk_level="safe",
            ),
            ToolDefinition(
                name="delete_event",
                description=(
                    "Delete a calendar event by ID. If the event is "
                    "recurring, ALL occurrences are permanently removed."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "UUID of the event to delete.",
                        },
                    },
                    "required": ["event_id"],
                },
                risk_level="medium",
                requires_confirmation=True,
            ),
            ToolDefinition(
                name="get_today_summary",
                description=(
                    "Get a summary of today's calendar events."
                ),
                parameters={
                    "type": "object",
                    "properties": {},
                },
                risk_level="safe",
            ),
        ]

    # ------------------------------------------------------------------
    # Tool dispatch
    # ------------------------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch a tool call to the appropriate handler.

        Args:
            tool_name: Identifier matching a ``ToolDefinition.name``.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A :class:`ToolResult` with the outcome.
        """
        t0 = time.perf_counter()
        handlers: dict[str, Any] = {
            "create_event": self._create_event,
            "list_events": self._list_events,
            "update_event": self._update_event,
            "delete_event": self._delete_event,
            "get_today_summary": self._get_today_summary,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return ToolResult.error(
                f"Unknown tool: {tool_name}",
                execution_time_ms=(time.perf_counter() - t0) * 1000,
            )
        try:
            result = await handler(args)
            elapsed = (time.perf_counter() - t0) * 1000
            return ToolResult.ok(result, execution_time_ms=elapsed)
        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self.logger.error("Tool {} failed: {}", tool_name, exc)
            return ToolResult.error(str(exc), execution_time_ms=elapsed)

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _create_event(self, args: dict[str, Any]) -> str:
        """Create a new calendar event.

        Args:
            args: Must contain title, start, end. Optional: description,
                  reminder_minutes, recurrence_rule.

        Returns:
            A confirmation string with the event ID.
        """
        title = args.get("title", "").strip()
        if not title:
            raise ValueError("title is required and cannot be empty")

        start_dt = self._parse_to_utc(args["start"])
        end_dt = self._parse_to_utc(args["end"])

        if end_dt <= start_dt:
            raise ValueError("end must be after start")

        reminder = args.get("reminder_minutes")
        if reminder is not None and reminder < 1:
            raise ValueError("reminder_minutes must be at least 1")

        rrule_val = args.get("recurrence_rule")
        if rrule_val:
            rrule_err = _validate_rrule(rrule_val)
            if rrule_err:
                raise ValueError(rrule_err)

        event = CalendarEvent(
            title=title,
            description=args.get("description"),
            start_time=start_dt,
            end_time=end_dt,
            reminder_minutes=reminder,
            recurrence_rule=rrule_val,
            created_by="assistant",
        )

        async with self.ctx.db() as session:
            session.add(event)
            await session.commit()
            await session.refresh(event)

        local_start = start_dt.astimezone(self._tz)
        self.logger.info("Created event '{}' at {}", event.title, local_start)
        return (
            f"Event '{event.title}' created "
            f"(id={event.id}, start={local_start.isoformat()})."
        )

    async def _list_events(self, args: dict[str, Any]) -> str:
        """List calendar events in a date range.

        Args:
            args: Optional start_date, end_date, max_results.

        Returns:
            A formatted string listing the matching events.
        """
        now_local = datetime.now(self._tz)
        max_results = min(args.get("max_results", 20), 100)

        if args.get("start_date"):
            range_start = self._parse_to_utc(args["start_date"])
        else:
            range_start = now_local.replace(
                hour=0, minute=0, second=0, microsecond=0,
            ).astimezone(timezone.utc)

        if args.get("end_date"):
            range_end = self._parse_to_utc(args["end_date"])
        else:
            range_end = range_start + timedelta(days=7)

        stmt = (
            select(CalendarEvent)
            .where(
                sa.or_(
                    sa.and_(
                        CalendarEvent.start_time >= range_start,
                        CalendarEvent.start_time < range_end,
                    ),
                    sa.and_(
                        CalendarEvent.recurrence_rule.isnot(None),
                        CalendarEvent.start_time <= range_end,
                    ),
                )
            )
            .order_by(CalendarEvent.start_time)
        )

        async with self.ctx.db() as session:
            results = await session.exec(stmt)
            events = results.all()

        expanded = _expand_recurring(
            list(events), range_start, range_end, self._tz,
        )
        expanded = expanded[:max_results]

        if not expanded:
            return "No events found in the specified range."

        lines: list[str] = []
        for ev in expanded:
            local_start = self._ensure_utc(ev.start_time).astimezone(self._tz)
            local_end = self._ensure_utc(ev.end_time).astimezone(self._tz)
            line = (
                f"- {ev.title} | "
                f"{local_start.strftime('%Y-%m-%d %H:%M')} → "
                f"{local_end.strftime('%H:%M')} | id={ev.id}"
            )
            if ev.description:
                line += f" | desc={ev.description}"
            if ev.reminder_minutes is not None:
                line += f" | reminder={ev.reminder_minutes}min"
            if ev.recurrence_rule:
                line += f" | rrule={ev.recurrence_rule}"
            lines.append(line)

        return f"Found {len(expanded)} event(s):\n" + "\n".join(lines)

    async def _update_event(self, args: dict[str, Any]) -> str:
        """Update an existing calendar event.

        Args:
            args: Must contain event_id. Optional: title, description,
                  start, end, reminder_minutes, recurrence_rule.

        Returns:
            A confirmation string.
        """
        try:
            event_id = uuid.UUID(args["event_id"])
        except ValueError:
            raise ValueError(
                f"Invalid event_id: '{args['event_id']}' "
                "is not a valid UUID"
            )

        async with self.ctx.db() as session:
            event = await session.get(CalendarEvent, event_id)
            if event is None:
                raise ValueError(f"Event {event_id} not found.")

            if "title" in args:
                event.title = args["title"]
            if "description" in args:
                event.description = args["description"]
            if "start" in args:
                event.start_time = self._parse_to_utc(args["start"])
            if "end" in args:
                event.end_time = self._parse_to_utc(args["end"])
            if "reminder_minutes" in args:
                reminder = args["reminder_minutes"]
                if reminder is not None and reminder < 1:
                    raise ValueError("reminder_minutes must be at least 1")
                event.reminder_minutes = reminder
            if "recurrence_rule" in args:
                new_rrule = args["recurrence_rule"]
                if new_rrule:
                    rrule_err = _validate_rrule(new_rrule)
                    if rrule_err:
                        raise ValueError(rrule_err)
                event.recurrence_rule = new_rrule

            end_utc = self._ensure_utc(event.end_time)
            start_utc = self._ensure_utc(event.start_time)
            if end_utc <= start_utc:
                raise ValueError("end must be after start")

            session.add(event)
            await session.commit()

        self.logger.info("Updated event '{}'", event.title)
        return f"Event '{event.title}' (id={event_id}) updated."

    async def _delete_event(self, args: dict[str, Any]) -> str:
        """Delete a calendar event by ID.

        Args:
            args: Must contain event_id.

        Returns:
            A confirmation string.
        """
        try:
            event_id = uuid.UUID(args["event_id"])
        except ValueError:
            raise ValueError(
                f"Invalid event_id: '{args['event_id']}' "
                "is not a valid UUID"
            )

        async with self.ctx.db() as session:
            event = await session.get(CalendarEvent, event_id)
            if event is None:
                raise ValueError(f"Event {event_id} not found.")

            title = event.title
            await session.delete(event)
            await session.commit()

        self.logger.info("Deleted event '{}' ({})", title, event_id)
        return f"Event '{title}' (id={event_id}) deleted."

    async def _get_today_summary(self, _args: dict[str, Any]) -> str:
        """Get a summary of today's events.

        Args:
            _args: Ignored (no parameters).

        Returns:
            A formatted summary of today's events.
        """
        now_local = datetime.now(self._tz)
        day_start = now_local.replace(
            hour=0, minute=0, second=0, microsecond=0,
        ).astimezone(timezone.utc)
        day_end = day_start + timedelta(days=1)

        stmt = (
            select(CalendarEvent)
            .where(
                sa.or_(
                    sa.and_(
                        CalendarEvent.start_time >= day_start,
                        CalendarEvent.start_time < day_end,
                    ),
                    sa.and_(
                        CalendarEvent.recurrence_rule.isnot(None),
                        CalendarEvent.start_time <= day_end,
                    ),
                )
            )
            .order_by(CalendarEvent.start_time)
        )

        async with self.ctx.db() as session:
            results = await session.exec(stmt)
            events = results.all()

        expanded = _expand_recurring(
            list(events), day_start, day_end, self._tz,
        )

        date_str = now_local.strftime("%A %d %B %Y")
        if not expanded:
            return f"No events scheduled for today ({date_str})."

        lines: list[str] = [f"Today ({date_str}) — {len(expanded)} event(s):"]
        for ev in expanded:
            local_start = self._ensure_utc(ev.start_time).astimezone(self._tz)
            local_end = self._ensure_utc(ev.end_time).astimezone(self._tz)
            line = (
                f"- {local_start.strftime('%H:%M')}–"
                f"{local_end.strftime('%H:%M')}: {ev.title} "
                f"(id={ev.id})"
            )
            if ev.description:
                line += f" — {ev.description}"
            if ev.reminder_minutes is not None:
                line += f" [reminder: {ev.reminder_minutes}min]"
            lines.append(line)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Reminder loop
    # ------------------------------------------------------------------

    async def _reminder_loop(self) -> None:
        """Periodically check for upcoming events with reminders.

        Emits an ``OmniaEvent`` via the EventBus when an event with
        ``reminder_minutes`` set is about to start.
        """
        while True:
            try:
                await asyncio.sleep(self._reminder_check_interval_s)
                await self._check_reminders()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error("Reminder loop error: {}", exc)

    async def _check_reminders(self) -> None:
        """Query events with reminders and emit alerts for upcoming ones.

        Only queries events starting within the next 24 hours and skips
        reminders that have already been fired (deduplication).
        Expands RRULE recurrence to check upcoming occurrences.
        """
        now_utc = datetime.now(timezone.utc)
        horizon = now_utc + timedelta(hours=24)

        stmt = (
            select(CalendarEvent)
            .where(CalendarEvent.reminder_minutes.isnot(None))  # type: ignore[union-attr]
            .where(
                sa.or_(
                    sa.and_(
                        CalendarEvent.start_time > now_utc,
                        CalendarEvent.start_time <= horizon,
                    ),
                    sa.and_(
                        CalendarEvent.recurrence_rule.isnot(None),
                        CalendarEvent.start_time <= horizon,
                    ),
                )
            )
        )

        async with self.ctx.db() as session:
            results = await session.exec(stmt)
            events = results.all()

        expanded = _expand_recurring(
            list(events), now_utc, horizon, self._tz,
        )

        for ev in expanded:
            start = self._ensure_utc(ev.start_time)
            if start <= now_utc or start > horizon:
                continue

            dedup_key = (ev.id, start.isoformat())
            if dedup_key in self._fired_reminders:
                continue

            window = timedelta(minutes=ev.reminder_minutes)  # type: ignore[arg-type]
            trigger_at = start - window
            # Fire if the event starts within the current check window
            if trigger_at <= now_utc < trigger_at + timedelta(
                seconds=self._reminder_check_interval_s,
            ):
                self._fired_reminders.add(dedup_key)
                local_start = start.astimezone(self._tz)
                self.logger.info(
                    "Reminder: '{}' starts at {}",
                    ev.title,
                    local_start.isoformat(),
                )
                await self.ctx.event_bus.emit(
                    OmniaEvent.CALENDAR_REMINDER,
                    event_id=str(ev.id),
                    title=ev.title,
                    start_time=local_start.isoformat(),
                    reminder_minutes=ev.reminder_minutes,
                )

        # Prune fired reminders older than 24h to prevent memory leak
        cutoff = now_utc - timedelta(hours=24)
        stale = {
            key for key in self._fired_reminders
            if dt_parser.parse(key[1]) < cutoff
        }
        if stale:
            self._fired_reminders -= stale

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        """Ensure a datetime is timezone-aware (UTC).

        SQLite/aiosqlite may return naive datetimes even when the
        column is declared ``DateTime(timezone=True)``.

        Args:
            dt: A datetime that may or may not carry tzinfo.

        Returns:
            A timezone-aware ``datetime`` in UTC.
        """
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _parse_to_utc(self, value: str) -> datetime:
        """Parse an ISO 8601 string to a UTC-aware datetime.

        If the input has no timezone info, assumes it is in the user's
        configured timezone.

        Args:
            value: An ISO 8601 datetime string.

        Returns:
            A timezone-aware ``datetime`` in UTC.
        """
        dt = dt_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self._tz)
        return dt.astimezone(timezone.utc)
