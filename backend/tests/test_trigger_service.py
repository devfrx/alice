"""Tests for the Fase 8 TriggerService (autonomous-turn trigger sources)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.core.event_bus import AliceEvent, EventBus
from backend.services.trigger_service import TriggerService, TriggerSpec


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raise_error = False

    async def __call__(
        self, *, conversation_id: str | None, prompt: str, origin: str,
    ) -> Any:
        self.calls.append(
            {"conversation_id": conversation_id, "prompt": prompt, "origin": origin},
        )
        if self.raise_error:
            raise RuntimeError("turn failed")
        return None


class FakeBackgroundTasks:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def start(self, *, kind: str, label: str, conversation_id: str | None = None) -> str:
        self.events.append(("start", kind))
        return "bt-1"

    async def complete(self, task_id: str, *, detail: str | None = None) -> None:
        self.events.append(("complete", task_id))

    async def fail(self, task_id: str, *, error: str) -> None:
        self.events.append(("fail", error))


class FakeAttention:
    def __init__(self) -> None:
        self.requests: list[str] = []

    async def request_attention(self, *, source: str, message: str, **kwargs: Any) -> Any:
        self.requests.append(source)


def _service(
    bus: EventBus,
    runner: FakeRunner,
    *,
    enabled: bool = True,
    bts: FakeBackgroundTasks | None = None,
    attention: FakeAttention | None = None,
) -> TriggerService:
    return TriggerService(
        event_bus=bus,
        turn_runner=runner,
        background_tasks=bts,
        attention=attention,
        enabled=enabled,
        max_concurrent_turns=1,
    )


@pytest.mark.asyncio
async def test_manual_fire_runs_turn_and_reports() -> None:
    bus = EventBus()
    runner = FakeRunner()
    bts = FakeBackgroundTasks()
    attention = FakeAttention()
    svc = _service(bus, runner, bts=bts, attention=attention)
    svc.register(
        TriggerSpec(
            trigger_id="t1", kind="manual", conversation_id="c1", prompt="go",
        ),
    )
    await svc.start()
    await svc.fire("t1")
    assert runner.calls == [
        {"conversation_id": "c1", "prompt": "go", "origin": "system"},
    ]
    assert ("start", "autonomous_turn") in bts.events
    assert ("complete", "bt-1") in bts.events
    assert attention.requests == ["trigger:t1"]
    await svc.shutdown()


@pytest.mark.asyncio
async def test_failed_turn_fails_the_background_task() -> None:
    bus = EventBus()
    runner = FakeRunner()
    runner.raise_error = True
    bts = FakeBackgroundTasks()
    attention = FakeAttention()
    svc = _service(bus, runner, bts=bts, attention=attention)
    svc.register(
        TriggerSpec(trigger_id="t1", kind="manual", conversation_id=None, prompt="go"),
    )
    await svc.start()
    await svc.fire("t1")
    assert ("fail", "turn failed") in bts.events
    assert attention.requests == []
    await svc.shutdown()


@pytest.mark.asyncio
async def test_event_trigger_fires_but_ignores_agent_origin() -> None:
    bus = EventBus()
    runner = FakeRunner()
    svc = _service(bus, runner)
    svc.register(
        TriggerSpec(
            trigger_id="t-mail",
            kind="event",
            conversation_id="c1",
            prompt="summarise the new email",
            event_name="email.received",
        ),
    )
    await svc.start()
    await bus.emit("email.received", folder="INBOX", origin="agent")
    assert runner.calls == []
    await bus.emit("email.received", folder="INBOX")
    assert len(runner.calls) == 1
    await svc.shutdown()


@pytest.mark.asyncio
async def test_schedule_trigger_fires_on_interval() -> None:
    bus = EventBus()
    runner = FakeRunner()
    svc = _service(bus, runner)
    svc.register(
        TriggerSpec(
            trigger_id="t-tick",
            kind="schedule",
            conversation_id="c1",
            prompt="tick",
            interval_s=0.05,
        ),
    )
    await svc.start()
    await asyncio.sleep(0.2)
    await svc.shutdown()
    assert len(runner.calls) >= 1


@pytest.mark.asyncio
async def test_disabled_service_never_fires() -> None:
    bus = EventBus()
    runner = FakeRunner()
    svc = _service(bus, runner, enabled=False)
    svc.register(
        TriggerSpec(trigger_id="t1", kind="manual", conversation_id=None, prompt="go"),
    )
    await svc.start()
    await svc.fire("t1")
    assert runner.calls == []
    await svc.shutdown()


@pytest.mark.asyncio
async def test_register_validation_and_duplicates() -> None:
    bus = EventBus()
    svc = _service(bus, FakeRunner())
    with pytest.raises(ValueError):
        svc.register(
            TriggerSpec(trigger_id="bad", kind="schedule", conversation_id=None, prompt="x"),
        )
    with pytest.raises(ValueError):
        svc.register(
            TriggerSpec(trigger_id="bad", kind="event", conversation_id=None, prompt="x"),
        )
    svc.register(
        TriggerSpec(trigger_id="ok", kind="manual", conversation_id=None, prompt="x"),
    )
    with pytest.raises(ValueError):
        svc.register(
            TriggerSpec(trigger_id="ok", kind="manual", conversation_id=None, prompt="y"),
        )
    with pytest.raises(KeyError):
        await svc.fire("missing")


@pytest.mark.asyncio
async def test_fire_emits_trigger_fired_on_bus() -> None:
    bus = EventBus()
    seen: list[dict[str, Any]] = []

    async def _handler(**kwargs: Any) -> None:
        seen.append(kwargs)

    bus.subscribe(AliceEvent.TRIGGER_FIRED, _handler)
    svc = _service(bus, FakeRunner())
    svc.register(
        TriggerSpec(trigger_id="t1", kind="manual", conversation_id=None, prompt="go"),
    )
    await svc.start()
    await svc.fire("t1")
    assert seen and seen[0]["trigger_id"] == "t1"
    await svc.shutdown()


@pytest.mark.asyncio
async def test_schedule_loop_survives_failing_collaborator() -> None:
    """A raising background_tasks.start must not kill the schedule loop (F3)."""

    class _FailingBackgroundTasks:
        async def start(self, **kwargs: Any) -> str:
            raise RuntimeError("bts down")

        async def complete(self, task_id: str, **kwargs: Any) -> None:
            pass

        async def fail(self, task_id: str, **kwargs: Any) -> None:
            pass

    bus = EventBus()
    fired: list[dict[str, Any]] = []

    async def _handler(**kwargs: Any) -> None:
        fired.append(kwargs)

    bus.subscribe(AliceEvent.TRIGGER_FIRED, _handler)
    svc = _service(bus, FakeRunner(), bts=_FailingBackgroundTasks())
    svc.register(
        TriggerSpec(
            trigger_id="t-tick",
            kind="schedule",
            conversation_id=None,
            prompt="tick",
            interval_s=0.05,
        ),
    )
    await svc.start()
    await asyncio.sleep(0.25)
    await svc.shutdown()
    # The first fire raised inside start(); the loop must have kept ticking.
    assert len(fired) >= 2


@pytest.mark.asyncio
async def test_register_rejects_trigger_fired_event() -> None:
    """Listening to trigger.fired would self-echo (F4)."""
    svc = _service(EventBus(), FakeRunner())
    with pytest.raises(ValueError):
        svc.register(
            TriggerSpec(
                trigger_id="echo",
                kind="event",
                conversation_id=None,
                prompt="x",
                event_name="trigger.fired",
            ),
        )
