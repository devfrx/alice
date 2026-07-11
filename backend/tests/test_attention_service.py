"""Tests for the Fase 8 AttentionService (initiative decision point)."""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.event_bus import AliceEvent, EventBus
from backend.services.attention_service import AttentionDecision, AttentionService


def _collect(bus: EventBus) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    async def _handler(**kwargs: Any) -> None:
        seen.append(kwargs)

    bus.subscribe(AliceEvent.ATTENTION_RAISED, _handler)
    return seen


@pytest.mark.asyncio
async def test_disabled_drops_everything() -> None:
    bus = EventBus()
    seen = _collect(bus)
    svc = AttentionService(event_bus=bus, enabled=False, cooldown_s=0.0)
    decision = await svc.request_attention(source="test", message="hi")
    assert decision is AttentionDecision.DROP
    assert seen == []


@pytest.mark.asyncio
async def test_notify_emits_attention_raised() -> None:
    bus = EventBus()
    seen = _collect(bus)
    svc = AttentionService(event_bus=bus, enabled=True, cooldown_s=0.0)
    decision = await svc.request_attention(
        source="trigger:t1", message="done", conversation_id="c1",
    )
    assert decision is AttentionDecision.NOTIFY
    assert seen == [
        {
            "source": "trigger:t1",
            "message": "done",
            "priority": "normal",
            "conversation_id": "c1",
        },
    ]


@pytest.mark.asyncio
async def test_cooldown_drops_non_urgent_but_not_urgent() -> None:
    bus = EventBus()
    seen = _collect(bus)
    svc = AttentionService(event_bus=bus, enabled=True, cooldown_s=3600.0)
    first = await svc.request_attention(source="a", message="1")
    second = await svc.request_attention(source="a", message="2")
    urgent = await svc.request_attention(source="a", message="3", priority="urgent")
    assert first is AttentionDecision.NOTIFY
    assert second is AttentionDecision.DROP
    assert urgent is AttentionDecision.NOTIFY
    assert [e["message"] for e in seen] == ["1", "3"]
