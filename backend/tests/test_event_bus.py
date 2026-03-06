"""Tests for backend.core.event_bus."""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.core.event_bus import EventBus


async def test_subscribe_and_emit(event_bus: EventBus) -> None:
    received: list[dict] = []

    async def handler(**kwargs):
        received.append(kwargs)

    event_bus.subscribe("test.event", handler)
    await event_bus.emit("test.event", data="hello")

    assert len(received) == 1
    assert received[0]["data"] == "hello"


async def test_emit_calls_multiple_handlers(event_bus: EventBus) -> None:
    calls: list[str] = []

    async def handler_a(**kwargs):
        calls.append("a")

    async def handler_b(**kwargs):
        calls.append("b")

    event_bus.subscribe("multi", handler_a)
    event_bus.subscribe("multi", handler_b)
    await event_bus.emit("multi")

    assert sorted(calls) == ["a", "b"]


async def test_unsubscribe_removes_handler(event_bus: EventBus) -> None:
    calls: list[int] = []

    async def handler(**kwargs):
        calls.append(1)

    event_bus.subscribe("unsub.test", handler)
    await event_bus.emit("unsub.test")
    assert len(calls) == 1

    event_bus.unsubscribe("unsub.test", handler)
    await event_bus.emit("unsub.test")
    assert len(calls) == 1  # no new call


async def test_once_fires_only_once(event_bus: EventBus) -> None:
    calls: list[int] = []

    async def handler(**kwargs):
        calls.append(1)

    event_bus.once("once.event", handler)

    await event_bus.emit("once.event")
    await event_bus.emit("once.event")

    assert len(calls) == 1


async def test_emit_no_handlers_does_not_error(event_bus: EventBus) -> None:
    # Should complete without raising
    await event_bus.emit("no.handlers.here")


async def test_handler_exception_is_caught(event_bus: EventBus) -> None:
    """A handler that raises should not crash emit; error is logged."""

    async def bad_handler(**kwargs):
        raise ValueError("boom")

    async def good_handler(**kwargs):
        pass

    event_bus.subscribe("error.event", bad_handler)
    event_bus.subscribe("error.event", good_handler)

    # Should not raise even though bad_handler explodes
    await event_bus.emit("error.event")


async def test_emit_passes_kwargs(event_bus: EventBus) -> None:
    received: list[dict] = []

    async def handler(**kwargs):
        received.append(kwargs)

    event_bus.subscribe("kwargs.test", handler)
    await event_bus.emit("kwargs.test", x=1, y="two", z=[3])

    assert received[0] == {"x": 1, "y": "two", "z": [3]}


async def test_unsubscribe_nonexistent_handler(event_bus: EventBus) -> None:
    """Unsubscribing a handler that was never subscribed emits a warning, no crash."""

    async def handler(**kwargs):
        pass

    # Should not raise
    event_bus.unsubscribe("nope", handler)


# ---------------------------------------------------------------------------
# Circuit breaker tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Verify circuit-breaker logic in the EventBus."""

    @pytest.mark.asyncio
    async def test_handler_disabled_after_threshold(self) -> None:
        """A handler failing N consecutive times is disabled."""
        bus = EventBus(circuit_breaker_threshold=2, circuit_breaker_cooldown=60.0)
        calls: list[int] = []

        async def bad_handler(**kwargs):
            calls.append(1)
            raise ValueError("boom")

        bus.subscribe("ev", bad_handler)

        # Emit twice to reach threshold
        await bus.emit("ev")
        await bus.emit("ev")
        assert len(calls) == 2

        # Third emit — handler should be disabled
        await bus.emit("ev")
        assert len(calls) == 2  # no new call

    @pytest.mark.asyncio
    async def test_disabled_handler_re_enabled_after_cooldown(self) -> None:
        """After cooldown expires, the handler is re-enabled."""
        bus = EventBus(circuit_breaker_threshold=2, circuit_breaker_cooldown=0.1)
        calls: list[int] = []

        async def flaky_handler(**kwargs):
            calls.append(1)
            raise RuntimeError("fail")

        bus.subscribe("ev", flaky_handler)

        # Trip the circuit breaker
        await bus.emit("ev")
        await bus.emit("ev")
        assert len(calls) == 2

        # Wait for cooldown
        await asyncio.sleep(0.15)

        # Handler should be re-enabled
        await bus.emit("ev")
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_success_resets_failure_counter(self) -> None:
        """A successful execution resets the consecutive failure count."""
        bus = EventBus(circuit_breaker_threshold=3, circuit_breaker_cooldown=60.0)
        should_fail = True
        calls: list[str] = []

        async def toggling_handler(**kwargs):
            calls.append("called")
            if should_fail:
                raise RuntimeError("fail")

        bus.subscribe("ev", toggling_handler)

        # Fail twice (below threshold of 3)
        await bus.emit("ev")
        await bus.emit("ev")
        assert len(calls) == 2

        # Succeed once — resets counter
        should_fail = False
        await bus.emit("ev")
        assert len(calls) == 3

        # Fail twice more — still below threshold (counter was reset)
        should_fail = True
        await bus.emit("ev")
        await bus.emit("ev")
        assert len(calls) == 5  # all calls executed, not disabled yet

    @pytest.mark.asyncio
    async def test_circuit_breaker_doesnt_affect_others(self) -> None:
        """Disabling one handler does not affect other handlers on the same event."""
        bus = EventBus(circuit_breaker_threshold=2, circuit_breaker_cooldown=60.0)
        bad_calls: list[int] = []
        good_calls: list[int] = []

        async def bad_handler(**kwargs):
            bad_calls.append(1)
            raise ValueError("boom")

        async def good_handler(**kwargs):
            good_calls.append(1)

        bus.subscribe("ev", bad_handler)
        bus.subscribe("ev", good_handler)

        # Trip bad handler's circuit breaker
        await bus.emit("ev")
        await bus.emit("ev")
        assert len(bad_calls) == 2
        assert len(good_calls) == 2

        # bad_handler is now disabled; good_handler still works
        await bus.emit("ev")
        assert len(bad_calls) == 2  # no new call
        assert len(good_calls) == 3  # still called

    @pytest.mark.asyncio
    async def test_once_handler_with_circuit_breaker(self) -> None:
        """A once() handler that fails is tracked but auto-unsubscribes."""
        bus = EventBus(circuit_breaker_threshold=2, circuit_breaker_cooldown=60.0)
        calls: list[int] = []

        async def failing_once(**kwargs):
            calls.append(1)
            raise RuntimeError("once fail")

        bus.once("ev", failing_once)

        # First emit — once wrapper fires, handler fails, wrapper unsubscribes
        await bus.emit("ev")
        assert len(calls) == 1

        # Second emit — handler already unsubscribed, not called
        await bus.emit("ev")
        assert len(calls) == 1
