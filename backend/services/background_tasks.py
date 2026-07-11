"""AL\\CE — In-memory registry of observable background tasks (Fase 8, spec §8).

Formalises the "observable background task": every state change is published
on the event bus as ``AliceEvent.BACKGROUND_TASK_UPDATED`` and bridged to the
events WebSocket by the surfaces stage, so the UI folds progress into its
``backgroundTasks`` store. Storage is deliberately in-memory — Fase 8 lays
the interface, not a persistent job queue (data is resettable, spec §2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

from loguru import logger

from backend.core.event_bus import AliceEvent, EventBus

TaskStatus = Literal["running", "completed", "failed"]

_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed"})


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class BackgroundTask:
    """Immutable snapshot of one observable background task."""

    task_id: str
    kind: str
    label: str
    status: TaskStatus
    progress: float | None
    detail: str | None
    conversation_id: str | None
    updated_at: str


class BackgroundTaskService:
    """Registry + event emitter for observable background tasks.

    Args:
        event_bus: Bus the per-change ``background_task.updated`` events are
            emitted on (bridged to the events WS in ``stage_surfaces``).
        max_finished: Cap on retained terminal tasks; oldest pruned first.
    """

    def __init__(self, *, event_bus: EventBus, max_finished: int = 50) -> None:
        self._bus = event_bus
        self._tasks: dict[str, BackgroundTask] = {}
        self._finished_order: list[str] = []
        self._max_finished = max_finished

    async def start(
        self, *, kind: str, label: str, conversation_id: str | None = None,
    ) -> str:
        """Register a new running task and return its id."""
        task = BackgroundTask(
            task_id=str(uuid.uuid4()),
            kind=kind,
            label=label,
            status="running",
            progress=None,
            detail=None,
            conversation_id=conversation_id,
            updated_at=_now_iso(),
        )
        self._tasks[task.task_id] = task
        await self._emit(task)
        return task.task_id

    async def update(
        self,
        task_id: str,
        *,
        progress: float | None = None,
        detail: str | None = None,
    ) -> None:
        """Report progress on a running task; unknown/terminal ids are no-ops."""
        task = self._tasks.get(task_id)
        if task is None or task.status in _TERMINAL_STATUSES:
            return
        task = replace(
            task,
            progress=progress if progress is not None else task.progress,
            detail=detail if detail is not None else task.detail,
            updated_at=_now_iso(),
        )
        self._tasks[task_id] = task
        await self._emit(task)

    async def complete(self, task_id: str, *, detail: str | None = None) -> None:
        """Mark a running task as completed (progress snaps to 1.0)."""
        await self._finish(task_id, status="completed", detail=detail)

    async def fail(self, task_id: str, *, error: str) -> None:
        """Mark a running task as failed with a human-readable error."""
        await self._finish(task_id, status="failed", detail=error)

    def get(self, task_id: str) -> BackgroundTask | None:
        """Return the current snapshot for ``task_id`` (or ``None``)."""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[BackgroundTask]:
        """Return every retained task snapshot."""
        return list(self._tasks.values())

    async def _finish(
        self, task_id: str, *, status: TaskStatus, detail: str | None,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None or task.status in _TERMINAL_STATUSES:
            return
        task = replace(
            task,
            status=status,
            progress=1.0 if status == "completed" else task.progress,
            detail=detail if detail is not None else task.detail,
            updated_at=_now_iso(),
        )
        self._tasks[task_id] = task
        self._finished_order.append(task_id)
        while len(self._finished_order) > self._max_finished:
            oldest = self._finished_order.pop(0)
            self._tasks.pop(oldest, None)
        await self._emit(task)

    async def _emit(self, task: BackgroundTask) -> None:
        try:
            await self._bus.emit(
                AliceEvent.BACKGROUND_TASK_UPDATED,
                task_id=task.task_id,
                kind=task.kind,
                label=task.label,
                status=task.status,
                progress=task.progress,
                detail=task.detail,
                conversation_id=task.conversation_id,
                updated_at=task.updated_at,
                origin="agent",
            )
        except Exception as exc:  # pragma: no cover — bus must never break callers
            logger.error("BackgroundTaskService: emit failed: {}", exc)
