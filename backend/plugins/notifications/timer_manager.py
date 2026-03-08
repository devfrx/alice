"""O.M.N.I.A. — Timer management for the notifications plugin.

Manages persistent timers backed by SQLite. Each timer is an
``asyncio.Task`` that sleeps until ``fires_at`` and then invokes a
callback.  Timers survive application restarts via the
``active_timers`` table.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import Field, SQLModel, select

from backend.core.event_bus import EventBus, OmniaEvent

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

AsyncCallback = Callable[[str, str], Coroutine[Any, Any, None]]
"""Signature: ``async def callback(timer_id: str, label: str) -> None``."""

# ---------------------------------------------------------------------------
# DB model
# ---------------------------------------------------------------------------


class ActiveTimer(SQLModel, table=True):
    """Persistent record of a scheduled timer."""

    __tablename__ = "active_timers"

    id: str = Field(primary_key=True)
    label: str = Field(max_length=256)
    fires_at: datetime = Field(
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    status: str = Field(default="pending", max_length=20)


# ---------------------------------------------------------------------------
# TimerManager
# ---------------------------------------------------------------------------


class TimerManager:
    """Create, cancel, and restore asyncio-backed timers with DB persistence.

    Args:
        db_factory: An ``async_sessionmaker`` for database access.
        event_bus: The application ``EventBus`` to emit timer events.
    """

    def __init__(
        self,
        db_factory: async_sessionmaker,
        event_bus: EventBus,
    ) -> None:
        self._db_factory = db_factory
        self._event_bus = event_bus
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._logger = logger.bind(component="TimerManager")
        self.lock = asyncio.Lock()

    # -- public API ---------------------------------------------------------

    async def create_timer(
        self,
        timer_id: str,
        label: str,
        duration_s: int,
        callback: AsyncCallback,
    ) -> datetime:
        """Schedule a new timer.

        Args:
            timer_id: Unique identifier (UUID string).
            label: Human-readable description.
            duration_s: Seconds until the timer fires.
            callback: Async callable invoked when the timer fires.

        Returns:
            The UTC datetime when the timer will fire.
        """
        fires_at = datetime.now(timezone.utc) + timedelta(seconds=duration_s)

        # Persist to DB
        async with self._db_factory() as session:
            timer_row = ActiveTimer(
                id=timer_id,
                label=label,
                fires_at=fires_at,
                status="pending",
            )
            session.add(timer_row)
            await session.commit()

        # Create background task
        task = asyncio.create_task(
            self._run_timer(timer_id, label, duration_s, callback),
            name=f"timer-{timer_id}",
        )
        self._timers[timer_id] = task
        self._logger.info(
            "Timer '{}' ({}) scheduled — fires at {}",
            label, timer_id, fires_at.isoformat(),
        )
        return fires_at

    async def cancel_timer(self, timer_id: str) -> bool:
        """Cancel a pending timer.

        Args:
            timer_id: The timer to cancel.

        Returns:
            ``True`` if the timer was found and cancelled, ``False`` otherwise.
        """
        task = self._timers.pop(timer_id, None)
        if task is None:
            return False

        task.cancel()
        await self._update_status(timer_id, "cancelled")
        self._logger.info("Timer '{}' cancelled", timer_id)
        return True

    async def list_active(self) -> list[dict[str, Any]]:
        """Return all pending timers from the database.

        Returns:
            A list of dicts with id, label, fires_at, and created_at.
        """
        async with self._db_factory() as session:
            stmt = select(ActiveTimer).where(ActiveTimer.status == "pending")
            results = await session.exec(stmt)
            return [
                {
                    "id": t.id,
                    "label": t.label,
                    "fires_at": t.fires_at.isoformat(),
                    "created_at": t.created_at.isoformat(),
                }
                for t in results.all()
            ]

    async def restore_timers(self, callback: AsyncCallback) -> int:
        """Reload pending timers from the database after a restart.

        Timers whose ``fires_at`` is in the past are fired immediately.

        Args:
            callback: Async callable to invoke when each timer fires.

        Returns:
            The number of timers restored.
        """
        async with self._db_factory() as session:
            stmt = select(ActiveTimer).where(ActiveTimer.status == "pending")
            results = await session.exec(stmt)
            rows = results.all()

        now = datetime.now(timezone.utc)
        restored = 0

        for row in rows:
            remaining_s = (row.fires_at - now).total_seconds()
            if remaining_s <= 0:
                # Already past — fire immediately
                task = asyncio.create_task(
                    self._fire_timer(row.id, row.label, callback),
                    name=f"timer-restore-{row.id}",
                )
                self._timers[row.id] = task
            else:
                task = asyncio.create_task(
                    self._run_timer(
                        row.id, row.label, remaining_s, callback,
                    ),
                    name=f"timer-{row.id}",
                )
                self._timers[row.id] = task
            restored += 1

        self._logger.info("Restored {} timer(s) from DB", restored)
        return restored

    async def shutdown(self) -> None:
        """Cancel all running timer tasks (graceful shutdown)."""
        tasks = []
        for tid, task in list(self._timers.items()):
            task.cancel()
            tasks.append(task)
            self._logger.debug("Cancelled timer task '{}'", tid)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._timers.clear()

    # -- internal -----------------------------------------------------------

    async def _run_timer(
        self,
        timer_id: str,
        label: str,
        delay_s: float,
        callback: AsyncCallback,
    ) -> None:
        """Sleep for *delay_s* seconds then fire the timer."""
        try:
            await asyncio.sleep(delay_s)
            await self._fire_timer(timer_id, label, callback)
        except asyncio.CancelledError:
            await self._update_status(timer_id, "cancelled")
            self._logger.debug("Timer task '{}' cancelled", timer_id)

    async def _fire_timer(
        self,
        timer_id: str,
        label: str,
        callback: AsyncCallback,
    ) -> None:
        """Execute the callback, update DB status, emit event."""
        self._timers.pop(timer_id, None)
        try:
            await callback(timer_id, label)
        except Exception as exc:
            self._logger.error(
                "Timer '{}' callback error: {}", timer_id, exc,
            )

        await self._update_status(timer_id, "fired")
        await self._event_bus.emit(
            OmniaEvent.TIMER_FIRED,
            timer_id=timer_id,
            label=label,
        )
        self._logger.info("Timer '{}' ({}) fired", label, timer_id)

    async def _update_status(self, timer_id: str, status: str) -> None:
        """Update the timer status in the database."""
        async with self._db_factory() as session:
            stmt = select(ActiveTimer).where(ActiveTimer.id == timer_id)
            result = await session.exec(stmt)
            row = result.one_or_none()
            if row:
                row.status = status
                session.add(row)
                await session.commit()
