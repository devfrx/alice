"""Tests for the Fase 8 observable background-task registry."""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.event_bus import AliceEvent, EventBus
from backend.services.background_tasks import BackgroundTaskService


@pytest.fixture()
def bus() -> EventBus:
    return EventBus()


def _collect(bus: EventBus) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    async def _handler(**kwargs: Any) -> None:
        seen.append(kwargs)

    bus.subscribe(AliceEvent.BACKGROUND_TASK_UPDATED, _handler)
    return seen


@pytest.mark.asyncio
async def test_lifecycle_start_update_complete(bus: EventBus) -> None:
    seen = _collect(bus)
    svc = BackgroundTaskService(event_bus=bus)

    task_id = await svc.start(kind="subagent", label="Research", conversation_id="c1")
    await svc.update(task_id, progress=0.5, detail="step 3/6")
    await svc.complete(task_id, detail="done")

    assert [e["status"] for e in seen] == ["running", "running", "completed"]
    assert seen[1]["progress"] == 0.5
    assert seen[2]["progress"] == 1.0
    snap = svc.get(task_id)
    assert snap is not None
    assert snap.status == "completed"


@pytest.mark.asyncio
async def test_fail_records_error_detail(bus: EventBus) -> None:
    seen = _collect(bus)
    svc = BackgroundTaskService(event_bus=bus)
    task_id = await svc.start(kind="autonomous_turn", label="Trigger: t1")
    await svc.fail(task_id, error="boom")
    assert seen[-1]["status"] == "failed"
    assert seen[-1]["detail"] == "boom"


@pytest.mark.asyncio
async def test_update_after_terminal_is_noop(bus: EventBus) -> None:
    seen = _collect(bus)
    svc = BackgroundTaskService(event_bus=bus)
    task_id = await svc.start(kind="subagent", label="x")
    await svc.complete(task_id)
    await svc.update(task_id, progress=0.1)
    await svc.fail(task_id, error="late")
    assert [e["status"] for e in seen] == ["running", "completed"]


@pytest.mark.asyncio
async def test_unknown_task_id_is_noop(bus: EventBus) -> None:
    seen = _collect(bus)
    svc = BackgroundTaskService(event_bus=bus)
    await svc.update("nope", progress=0.5)
    await svc.complete("nope")
    assert seen == []


@pytest.mark.asyncio
async def test_finished_tasks_are_pruned(bus: EventBus) -> None:
    svc = BackgroundTaskService(event_bus=bus, max_finished=2)
    ids = []
    for i in range(3):
        task_id = await svc.start(kind="subagent", label=f"t{i}")
        await svc.complete(task_id)
        ids.append(task_id)
    assert svc.get(ids[0]) is None
    assert svc.get(ids[1]) is not None
    assert svc.get(ids[2]) is not None
