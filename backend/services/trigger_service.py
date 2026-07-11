"""AL\\CE — TriggerService: autonomous-turn trigger sources (Fase 8, spec §8).

Starts autonomous turns from (a) simple time schedules, (b) event-bus events
and (c) manual/programmatic fire (the future hotword path). An autonomous
turn IS a normal turn — the injected ``turn_runner`` goes through the
standard assembly/executor/permission pipeline of the conversation the
trigger belongs to (spec §4.5: no privileged path).

Fase 8 lays the interface: rich cron/RRULE schedules, trigger persistence
and a registration surface (tools/REST) arrive after the risanamento.

Anti-echo invariant (spec §7/§8): bus events whose ``origin`` kwarg equals
``"agent"`` never fire an event trigger — the agent must not trigger itself.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from loguru import logger

from backend.core.event_bus import AliceEvent, EventBus


class TurnRunner(Protocol):
    """Callable running one autonomous turn (injected by the composition root)."""

    async def __call__(
        self, *, conversation_id: str | None, prompt: str, origin: str,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class TriggerSpec:
    """Declarative description of one trigger.

    Attributes:
        trigger_id: Unique id (used for unregister / manual fire).
        kind: ``schedule`` (interval loop), ``event`` (bus subscription) or
            ``manual`` (fired programmatically — the future hotword path).
        conversation_id: Conversation the autonomous turn belongs to
            (``None`` starts a fresh conversation per fire).
        prompt: User-role content of the autonomous turn.
        event_name: Bus event to subscribe to (required for ``event``).
        interval_s: Seconds between fires (required for ``schedule``).
        ignore_agent_origin: Drop bus events carrying ``origin == "agent"``
            (anti-echo default, spec §8).
    """

    trigger_id: str
    kind: Literal["schedule", "event", "manual"]
    conversation_id: str | None
    prompt: str
    event_name: str | None = None
    interval_s: float | None = None
    ignore_agent_origin: bool = True


class TriggerService:
    """Registry + activation of autonomous-turn triggers.

    Args:
        event_bus: Bus used both to subscribe event triggers and to emit
            ``trigger.fired`` observability events.
        turn_runner: The headless turn runner (``None`` disables firing —
            triggers register but never run, e.g. in unit tests).
        background_tasks: Optional ``BackgroundTaskService`` (duck-typed);
            every fire becomes an observable ``autonomous_turn`` task.
        attention: Optional ``AttentionService`` (duck-typed); completions
            are surfaced through the central initiative decision point.
        enabled: Master switch (``triggers.enabled``).
        max_concurrent_turns: Autonomous turns allowed at once; extra fires
            are skipped with a warning (no queueing in Fase 8).
    """

    def __init__(
        self,
        *,
        event_bus: EventBus,
        turn_runner: TurnRunner | None,
        background_tasks: Any = None,
        attention: Any = None,
        enabled: bool = True,
        max_concurrent_turns: int = 1,
    ) -> None:
        self._bus = event_bus
        self._turn_runner = turn_runner
        self._background_tasks = background_tasks
        self._attention = attention
        self._enabled = enabled
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent_turns))
        self._triggers: dict[str, TriggerSpec] = {}
        self._schedule_tasks: dict[str, asyncio.Task[None]] = {}
        self._event_handlers: dict[str, Any] = {}
        self._started = False

    # -- Registry ---------------------------------------------------------

    def register(self, spec: TriggerSpec) -> None:
        """Register ``spec``; sources activate immediately when started."""
        if spec.trigger_id in self._triggers:
            raise ValueError(f"Trigger '{spec.trigger_id}' already registered")
        if spec.kind == "schedule" and not (spec.interval_s and spec.interval_s > 0):
            raise ValueError("schedule triggers require a positive interval_s")
        if spec.kind == "event" and not spec.event_name:
            raise ValueError("event triggers require event_name")
        self._triggers[spec.trigger_id] = spec
        if self._started:
            self._activate(spec)
        logger.info("Trigger registered: {} ({})", spec.trigger_id, spec.kind)

    def unregister(self, trigger_id: str) -> None:
        """Remove a trigger and deactivate its source (idempotent)."""
        spec = self._triggers.pop(trigger_id, None)
        if spec is None:
            return
        task = self._schedule_tasks.pop(trigger_id, None)
        if task is not None:
            task.cancel()
        handler = self._event_handlers.pop(trigger_id, None)
        if handler is not None and spec.event_name:
            self._bus.unsubscribe(spec.event_name, handler)

    def list_triggers(self) -> list[TriggerSpec]:
        """Return every registered trigger spec."""
        return list(self._triggers.values())

    # -- Lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Activate all registered triggers (idempotent)."""
        if self._started:
            return
        self._started = True
        for spec in self._triggers.values():
            self._activate(spec)

    async def shutdown(self) -> None:
        """Cancel schedule loops and unsubscribe event handlers."""
        self._started = False
        tasks = list(self._schedule_tasks.values())
        self._schedule_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for trigger_id, handler in list(self._event_handlers.items()):
            spec = self._triggers.get(trigger_id)
            if spec is not None and spec.event_name:
                self._bus.unsubscribe(spec.event_name, handler)
        self._event_handlers.clear()

    # -- Firing -----------------------------------------------------------

    async def fire(self, trigger_id: str) -> None:
        """Fire a registered trigger programmatically (manual/hotword seam)."""
        spec = self._triggers.get(trigger_id)
        if spec is None:
            raise KeyError(trigger_id)
        await self._fire(spec)

    def _activate(self, spec: TriggerSpec) -> None:
        if spec.kind == "schedule":
            task = asyncio.create_task(
                self._schedule_loop(spec), name=f"trigger-{spec.trigger_id}",
            )
            self._schedule_tasks[spec.trigger_id] = task
        elif spec.kind == "event":

            async def _on_event(**kwargs: Any) -> None:
                if spec.ignore_agent_origin and kwargs.get("origin") == "agent":
                    logger.debug(
                        "Trigger '{}': ignored agent-origin event", spec.trigger_id,
                    )
                    return
                await self._fire(spec)

            self._event_handlers[spec.trigger_id] = _on_event
            assert spec.event_name is not None  # validated in register()
            self._bus.subscribe(spec.event_name, _on_event)

    async def _schedule_loop(self, spec: TriggerSpec) -> None:
        interval = spec.interval_s or 0.0
        while True:
            await asyncio.sleep(interval)
            await self._fire(spec)

    async def _fire(self, spec: TriggerSpec) -> None:
        if not self._enabled:
            logger.debug("Trigger '{}' skipped: triggers disabled", spec.trigger_id)
            return
        if self._turn_runner is None:
            logger.warning(
                "Trigger '{}' skipped: no turn runner wired", spec.trigger_id,
            )
            return
        if self._semaphore.locked():
            logger.warning(
                "Trigger '{}' skipped: autonomous turn already running",
                spec.trigger_id,
            )
            return
        async with self._semaphore:
            await self._bus.emit(
                AliceEvent.TRIGGER_FIRED,
                trigger_id=spec.trigger_id,
                kind=spec.kind,
                origin="system",
            )
            task_id: str | None = None
            if self._background_tasks is not None:
                task_id = await self._background_tasks.start(
                    kind="autonomous_turn",
                    label=f"Trigger: {spec.trigger_id}",
                    conversation_id=spec.conversation_id,
                )
            try:
                await self._turn_runner(
                    conversation_id=spec.conversation_id,
                    prompt=spec.prompt,
                    origin="system",
                )
            except Exception as exc:
                logger.exception(
                    "Trigger '{}': autonomous turn failed", spec.trigger_id,
                )
                if self._background_tasks is not None and task_id is not None:
                    await self._background_tasks.fail(task_id, error=str(exc))
                return
            if self._background_tasks is not None and task_id is not None:
                await self._background_tasks.complete(task_id)
            if self._attention is not None:
                await self._attention.request_attention(
                    source=f"trigger:{spec.trigger_id}",
                    message=(
                        f"Autonomous turn for trigger '{spec.trigger_id}' completed"
                    ),
                    conversation_id=spec.conversation_id,
                )
