"""O.M.N.I.A. — Calendar REST endpoints."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import sqlalchemy as sa
from dateutil import parser as dt_parser
from dateutil.rrule import rrulestr
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
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
    max_results: int = 20,
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
async def upcoming_events(request: Request, limit: int = 5) -> list[dict]:
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
    """
    dt = dt_parser.parse(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


@router.post("/events")
async def create_event(request: Request) -> dict:
    """Create a new calendar event.

    Body JSON: title, start_time, end_time,
    optional description, reminder_minutes, recurrence_rule.
    """
    ctx: AppContext = request.app.state.context
    tz = _get_tz(ctx)
    body = await request.json()

    title = body.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    raw_start = body.get("start_time")
    raw_end = body.get("end_time")
    if not raw_start or not raw_end:
        raise HTTPException(
            status_code=400, detail="start_time and end_time are required",
        )

    start_utc = _parse_to_utc(raw_start, tz)
    end_utc = _parse_to_utc(raw_end, tz)
    if end_utc <= start_utc:
        raise HTTPException(
            status_code=400, detail="end_time must be after start_time",
        )

    reminder_minutes = body.get("reminder_minutes")
    if reminder_minutes is not None:
        if not isinstance(reminder_minutes, int) or reminder_minutes < 1:
            raise HTTPException(
                status_code=400,
                detail="reminder_minutes must be a positive integer",
            )

    rrule = body.get("recurrence_rule")
    if rrule:
        rrule_err = validate_rrule(rrule)
        if rrule_err:
            raise HTTPException(status_code=400, detail=rrule_err)

    event = CalendarEvent(
        title=title,
        description=body.get("description"),
        start_time=start_utc,
        end_time=end_utc,
        reminder_minutes=body.get("reminder_minutes"),
        recurrence_rule=rrule,
        created_by="user",
    )

    async with ctx.db() as session:
        session.add(event)
        await session.commit()
        await session.refresh(event)

    logger.info("POST /calendar/events — created '{}'", event.title)
    return _event_to_dict(event, tz)


@router.put("/events/{event_id}")
async def update_event(request: Request, event_id: str) -> dict:
    """Update an existing calendar event by UUID."""
    import uuid as _uuid  # noqa: N812 — local alias

    ctx: AppContext = request.app.state.context
    tz = _get_tz(ctx)
    body = await request.json()

    try:
        eid = _uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event ID")

    async with ctx.db() as session:
        event = await session.get(CalendarEvent, eid)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        if "title" in body:
            event.title = body["title"]
        if "description" in body:
            event.description = body["description"]
        if "start_time" in body:
            event.start_time = _parse_to_utc(body["start_time"], tz)
        if "end_time" in body:
            event.end_time = _parse_to_utc(body["end_time"], tz)
        if "reminder_minutes" in body:
            rm = body["reminder_minutes"]
            if rm is not None:
                if not isinstance(rm, int) or rm < 1:
                    raise HTTPException(
                        status_code=400,
                        detail="reminder_minutes must be a positive integer",
                    )
            event.reminder_minutes = rm
        if "recurrence_rule" in body:
            new_rrule = body["recurrence_rule"]
            if new_rrule:
                rrule_err = validate_rrule(new_rrule)
                if rrule_err:
                    raise HTTPException(status_code=400, detail=rrule_err)
            event.recurrence_rule = new_rrule

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
    return _event_to_dict(event, tz)


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
    return {"deleted": True, "id": event_id}
