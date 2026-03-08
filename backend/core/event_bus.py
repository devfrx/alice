"""O.M.N.I.A. — Async event bus for inter-component communication."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from enum import StrEnum
from typing import Any, Callable, Coroutine

from loguru import logger

# ---------------------------------------------------------------------------
# Circuit breaker defaults
# ---------------------------------------------------------------------------

CIRCUIT_BREAKER_THRESHOLD: int = 5
"""Consecutive failures before a handler is temporarily disabled."""

CIRCUIT_BREAKER_COOLDOWN_S: float = 60.0
"""Seconds a tripped handler stays disabled before retrying."""

# ---------------------------------------------------------------------------
# Well-known event names
# ---------------------------------------------------------------------------


class OmniaEvent(StrEnum):
    """Enumeration of well-known event names used by the bus."""

    LLM_RESPONSE = "llm.response"
    STT_RESULT = "stt.result"
    TTS_START = "tts.start"
    PLUGIN_LOADED = "plugin.loaded"
    PLUGIN_FAILED = "plugin.failed"
    PLUGIN_STATUS_CHANGED = "plugin.status_changed"
    TOOL_CALLED = "tool.called"
    TOOL_EXECUTION_START = "tool.execution_start"
    TOOL_EXECUTION_SUCCEEDED = "tool.execution_succeeded"
    TOOL_EXECUTION_FAILED = "tool.execution_failed"
    # -- Voice (Phase 4) --
    STT_STARTED = "stt.started"
    STT_STOPPED = "stt.stopped"
    STT_ERROR = "stt.error"
    TTS_DONE = "tts.done"
    TTS_ERROR = "tts.error"
    VOICE_SESSION_START = "voice.session_start"
    VOICE_SESSION_END = "voice.session_end"
    VRAM_WARNING = "vram.warning"
    VRAM_CRITICAL = "vram.critical"
    # -- PC Automation (Phase 5) --
    PC_SCREENSHOT_TAKEN = "pc_automation.screenshot_taken"
    PC_COMMAND_EXECUTED = "pc_automation.command_executed"
    PC_APP_OPENED = "pc_automation.app_opened"
    PC_APP_CLOSED = "pc_automation.app_closed"
    TOOL_CONFIRMATION_LOGGED = "tool.confirmation_logged"
    # -- Notifications (Phase 7.5) --
    TIMER_FIRED = "timer.fired"
    ERROR = "error"
    # -- Calendar --
    CALENDAR_REMINDER = "calendar.reminder"

# Type alias for async handlers
AsyncHandler = Callable[..., Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """A lightweight async event bus with circuit-breaker protection.

    Handlers are async callables. When an event is emitted every registered
    handler for that event is called concurrently via ``asyncio.gather``.

    If a handler fails *threshold* consecutive times it is disabled for
    *cooldown* seconds to prevent log flooding.
    """

    def __init__(
        self,
        circuit_breaker_threshold: int = CIRCUIT_BREAKER_THRESHOLD,
        circuit_breaker_cooldown: float = CIRCUIT_BREAKER_COOLDOWN_S,
    ) -> None:
        self._handlers: dict[str, list[AsyncHandler]] = defaultdict(list)
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown
        # Circuit breaker state
        self._handler_failures: dict[AsyncHandler, int] = {}
        self._disabled_handlers: dict[AsyncHandler, float] = {}

    # -- public API ---------------------------------------------------------

    def subscribe(
        self, event_name: str | OmniaEvent, handler: AsyncHandler,
    ) -> None:
        """Register *handler* for *event_name*.

        Args:
            event_name: The event to listen for (str or ``OmniaEvent``).
            handler: An async callable to invoke when the event fires.
        """
        self._handlers[event_name].append(handler)
        logger.debug(
            "Subscribed {} to '{}'", handler.__qualname__, event_name
        )

    def unsubscribe(
        self, event_name: str | OmniaEvent, handler: AsyncHandler,
    ) -> None:
        """Remove *handler* from *event_name*.

        Args:
            event_name: The event to stop listening for.
            handler: The handler previously registered via ``subscribe``.
        """
        try:
            self._handlers[event_name].remove(handler)
            logger.debug(
                "Unsubscribed {} from '{}'",
                handler.__qualname__,
                event_name,
            )
        except ValueError:
            logger.warning(
                "Handler {} was not subscribed to '{}'",
                handler.__qualname__,
                event_name,
            )

    def once(
        self, event_name: str | OmniaEvent, handler: AsyncHandler,
    ) -> None:
        """Register *handler* so it fires exactly once then auto-unsubscribes.

        Args:
            event_name: The event to listen for.
            handler: An async callable invoked a single time.
        """
        fired = False

        async def _wrapper(**kwargs: Any) -> None:
            nonlocal fired
            if fired:
                return
            fired = True
            self.unsubscribe(event_name, _wrapper)
            await handler(**kwargs)

        # Preserve qualname for logging
        _wrapper.__qualname__ = f"{handler.__qualname__}[once]"
        self.subscribe(event_name, _wrapper)

    async def emit(
        self, event_name: str | OmniaEvent, **kwargs: Any,
    ) -> None:
        """Fire *event_name*, calling all registered handlers concurrently.

        Handlers disabled by the circuit breaker are skipped until their
        cooldown expires.

        Args:
            event_name: The event to fire.
            **kwargs: Keyword arguments forwarded to every handler.
        """
        handlers = list(self._handlers.get(event_name, []))
        if not handlers:
            logger.debug("Event '{}' fired — no handlers", event_name)
            return

        now = time.monotonic()
        active: list[AsyncHandler] = []
        for h in handlers:
            disabled_until = self._disabled_handlers.get(h)
            if disabled_until is not None:
                if now >= disabled_until:
                    # Cooldown expired — re-enable
                    del self._disabled_handlers[h]
                    self._handler_failures.pop(h, None)
                    active.append(h)
                else:
                    continue  # still disabled
            else:
                active.append(h)

        if not active:
            return

        logger.debug(
            "Event '{}' fired — {} handler(s)",
            event_name,
            len(active),
        )

        results = await asyncio.gather(
            *(h(**kwargs) for h in active),
            return_exceptions=True,
        )

        for handler, result in zip(active, results):
            if isinstance(result, BaseException):
                logger.error(
                    "Handler error on '{}': {}",
                    event_name,
                    result,
                )
                count = self._handler_failures.get(handler, 0) + 1
                self._handler_failures[handler] = count
                if count >= self._cb_threshold:
                    self._disabled_handlers[handler] = (
                        now + self._cb_cooldown
                    )
                    logger.warning(
                        "Circuit breaker tripped for {} on '{}': "
                        "{} consecutive failures — disabled for {}s",
                        handler.__qualname__,
                        event_name,
                        count,
                        self._cb_cooldown,
                    )
            else:
                # Success resets failure counter
                self._handler_failures.pop(handler, None)
