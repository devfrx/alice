"""AL\\CE — Calendar REST endpoints."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import sqlalchemy as sa
from dateutil import parser as dt_parser
from dateutil.rrule import rrulestr
from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlmodel import select
from zoneinfo import ZoneInfo

from backend.core.context import AppContext
from backend.plugins.calendar.plugin import CalendarEvent
from backend.plugins.calendar.utils import (
    MAX_OCCURRENCES,
    validate_rrule,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _event_to_dict(event: CalendarEvent, tz: ZoneInfo) -> dict:
    """Serialize a CalendarEvent to a JSON-friendly dict in local tz."""
    local_start = _ensure_utc(event.start_time).astimezone(tz)
    return {
        "id": str(event.id),
        "title": event.title,
        "description": event.description,
        "start_time": local_start.isoformat(),
        "end_time": _ensure_utc(event.end_time).astimezone(tz).isoformat(),
        "recurrence_rule": event.recurrence_rule,
        "reminder_minutes": event.reminder_minutes,
        "created_by": event.created_by,
        "occurrence_date": local_start.date().isoformat() if event.recurrence_rule else None,
    }


def _get_tz(ctx: AppContext) -> ZoneInfo:
    """Resolve the configured calendar timezone."""
    tz_name = getattr(ctx.config.calendar, "timezone", "Europe/Rome")
    return ZoneInfo(tz_name)


# Re-export shared constant under private alias for local use.
_MAX_OCCURRENCES = MAX_OCCURRENCES


def _expand_recurring(
    events: list[CalendarEvent],
    range_start: datetime,
    range_end: datetime,
    tz: ZoneInfo,
) -> list[CalendarEvent]:
    """Expand recurring events into individual occurrences within range."""
    result: list[CalendarEvent] = []
    for ev in events:
        if not ev.recurrence_rule:
            result.append(ev)
            continue

        start = _ensure_utc(ev.start_time)
        end = _ensure_utc(ev.end_time)
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
                    "RRULE for event {} produced {} occurrences, capping to {}",
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

    result.sort(key=lambda e: _ensure_utc(e.start_time))
    return result


@router.get("/events")
async def list_events(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    max_results: int = Query(20, ge=1, le=500),
) -> list[dict]:
    """List calendar events within a date range.

    Args:
        request: FastAPI request.
        start_date: ISO date string (default: today).
        end_date: ISO date string (default: 7 days from start).
        max_results: Maximum events to return.
    """
    ctx: AppContext = request.app.state.context
    tz = _get_tz(ctx)
    now_local = datetime.now(tz)

    start_utc = (
        _parse_to_utc(start_date, tz)
        if start_date
        else datetime.combine(
            now_local.date(), time.min, tzinfo=tz,
        ).astimezone(timezone.utc)
    )
    end_utc = (
        _parse_to_utc(end_date, tz)
        if end_date
        else start_utc + timedelta(days=7)
    )
    # Date-only end_date (e.g. "2026-03-12") → bump to start of next
    # day so the range covers the full calendar day.
    if end_date and "T" not in end_date:
        end_utc += timedelta(days=1)

    stmt = (
        select(CalendarEvent)
        .where(
            sa.or_(
                sa.and_(
                    CalendarEvent.start_time >= start_utc,
                    CalendarEvent.start_time < end_utc,
                ),
                sa.and_(
                    CalendarEvent.recurrence_rule.isnot(None),
                    CalendarEvent.start_time <= end_utc,
                ),
            )
        )
        .order_by(CalendarEvent.start_time)
    )

    async with ctx.db() as session:
        results = await session.exec(stmt)
        events = results.all()

    expanded = _expand_recurring(list(events), start_utc, end_utc, tz)
    expanded = expanded[:max_results]

    logger.debug("GET /calendar/events — {} events in range", len(expanded))
    return [_event_to_dict(e, tz) for e in expanded]


@router.get("/today")
async def today_summary(request: Request) -> dict:
    """Return today's events summary."""
    ctx: AppContext = request.app.state.context
    tz = _get_tz(ctx)
    today = datetime.now(tz).date()
    start_utc = datetime.combine(today, time.min, tzinfo=tz).astimezone(timezone.utc)
    end_utc = start_utc + timedelta(days=1)

    stmt = (
        select(CalendarEvent)
        .where(
            sa.or_(
                sa.and_(
                    CalendarEvent.start_time >= start_utc,
                    CalendarEvent.start_time < end_utc,
                ),
                sa.and_(
                    CalendarEvent.recurrence_rule.isnot(None),
                    CalendarEvent.start_time <= end_utc,
                ),
            )
        )
        .order_by(CalendarEvent.start_time)
    )

    async with ctx.db() as session:
        results = await session.exec(stmt)
        events = results.all()

    expanded = _expand_recurring(list(events), start_utc, end_utc, tz)
    serialized = [_event_to_dict(e, tz) for e in expanded]
    logger.debug("GET /calendar/today — {} events", len(serialized))
    return {
        "date": today.isoformat(),
        "event_count": len(serialized),
        "events": serialized,
    }


@router.get("/upcoming")
async def upcoming_events(request: Request, limit: int = Query(5, ge=1, le=100)) -> list[dict]:
    """Return the next N upcoming events from now.

    Args:
        request: FastAPI request.
        limit: Maximum number of events to return.
    """
    ctx: AppContext = request.app.state.context
    tz = _get_tz(ctx)
    now_utc = datetime.now(timezone.utc)
    horizon = now_utc + timedelta(days=90)

    stmt = (
        select(CalendarEvent)
        .where(
            sa.or_(
                sa.and_(
                    CalendarEvent.start_time >= now_utc,
                    CalendarEvent.start_time < horizon,
                ),
                sa.and_(
                    CalendarEvent.recurrence_rule.isnot(None),
                    CalendarEvent.start_time <= horizon,
                ),
            )
        )
        .order_by(CalendarEvent.start_time)
    )

    async with ctx.db() as session:
        results = await session.exec(stmt)
        events = results.all()

    expanded = _expand_recurring(list(events), now_utc, horizon, tz)
    expanded = expanded[:limit]

    logger.debug("GET /calendar/upcoming — {} events", len(expanded))
    return [_event_to_dict(e, tz) for e in expanded]


def _parse_to_utc(value: str, tz: ZoneInfo) -> datetime:
    """Parse an ISO 8601 string to a UTC-aware datetime.

    If the input has no timezone info, assumes it is in the given tz.

    Raises:
        HTTPException 400: When *value* is not a parseable date/time.
    """
    try:
        dt = dt_parser.parse(value)
    except (ValueError, TypeError, OverflowError, dt_parser.ParserError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid datetime format: {value!r} ({exc})",
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateEventRequest(BaseModel):
    """Body for POST /calendar/events."""

    title: str = Field(..., min_length=1, max_length=500)
    start_time: str
    end_time: str
    description: str | None = None
    reminder_minutes: int | None = Field(None, ge=1)
    recurrence_rule: str | None = None


class UpdateEventRequest(BaseModel):
    """Body for PUT /calendar/events/{event_id}."""

    title: str | None = Field(None, min_length=1, max_length=500)
    start_time: str | None = None
    end_time: str | None = None
    description: str | None = None
    reminder_minutes: int | None = Field(None, ge=1)
    recurrence_rule: str | None = None


@router.post("/events", status_code=201)
async def create_event(
    body: CreateEventRequest, request: Request,
) -> dict:
    """Create a new calendar event."""
    ctx: AppContext = request.app.state.context
    tz = _get_tz(ctx)

    start_utc = _parse_to_utc(body.start_time, tz)
    end_utc = _parse_to_utc(body.end_time, tz)
    if end_utc <= start_utc:
        raise HTTPException(
            status_code=400, detail="end_time must be after start_time",
        )

    if body.recurrence_rule:
        rrule_err = validate_rrule(body.recurrence_rule)
        if rrule_err:
            raise HTTPException(status_code=400, detail=rrule_err)

    event = CalendarEvent(
        title=body.title,
        description=body.description,
        start_time=start_utc,
        end_time=end_utc,
        reminder_minutes=body.reminder_minutes,
        recurrence_rule=body.recurrence_rule,
        created_by="user",
    )

    async with ctx.db() as session:
        session.add(event)
        await session.commit()
        await session.refresh(event)

    logger.info("POST /calendar/events — created '{}'", event.title)
    result = _event_to_dict(event, tz)
    if ctx.ws_connection_manager:
        await ctx.ws_connection_manager.broadcast({
            "type": "calendar_changed",
            "action": "created",
            "event_id": str(event.id),
        })
    return result


@router.put("/events/{event_id}")
async def update_event(
    body: UpdateEventRequest, request: Request, event_id: str,
) -> dict:
    """Update an existing calendar event by UUID."""
    import uuid as _uuid

    ctx: AppContext = request.app.state.context
    tz = _get_tz(ctx)

    try:
        eid = _uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event ID")

    async with ctx.db() as session:
        event = await session.get(CalendarEvent, eid)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        if body.title is not None:
            event.title = body.title
        if body.description is not None:
            event.description = body.description
        if body.start_time is not None:
            event.start_time = _parse_to_utc(body.start_time, tz)
        if body.end_time is not None:
            event.end_time = _parse_to_utc(body.end_time, tz)
        if body.reminder_minutes is not None:
            event.reminder_minutes = body.reminder_minutes
        if body.recurrence_rule is not None:
            if body.recurrence_rule:
                rrule_err = validate_rrule(body.recurrence_rule)
                if rrule_err:
                    raise HTTPException(
                        status_code=400, detail=rrule_err,
                    )
            event.recurrence_rule = body.recurrence_rule

        end = _ensure_utc(event.end_time)
        start = _ensure_utc(event.start_time)
        if end <= start:
            raise HTTPException(
                status_code=400,
                detail="end_time must be after start_time",
            )

        session.add(event)
        await session.commit()
        await session.refresh(event)

    logger.info("PUT /calendar/events/{} — updated", event_id)
    result = _event_to_dict(event, tz)
    if ctx.ws_connection_manager:
        await ctx.ws_connection_manager.broadcast({
            "type": "calendar_changed",
            "action": "updated",
            "event_id": event_id,
        })
    return result


@router.delete("/events/{event_id}")
async def delete_event(request: Request, event_id: str) -> dict:
    """Delete a calendar event by UUID."""
    import uuid as _uuid

    ctx: AppContext = request.app.state.context

    try:
        eid = _uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event ID")

    async with ctx.db() as session:
        event = await session.get(CalendarEvent, eid)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        await session.delete(event)
        await session.commit()

    logger.info("DELETE /calendar/events/{}", event_id)
    if ctx.ws_connection_manager:
        await ctx.ws_connection_manager.broadcast({
            "type": "calendar_changed",
            "action": "deleted",
            "event_id": event_id,
        })
    return {"deleted": True, "id": event_id}
