"""AL\\CE — AttentionService: single decision point for agent→user initiative.

Every proactive surface (trigger completions, background alerts, the future
"Jarvis speaks first" behaviours) must ask this service before reaching the
user (spec §8). Fase 8 lays the interface and a minimal policy — the rich
prioritisation arrives after the risanamento. Central and disableable by
design: ``attention.enabled: false`` silences ALL agent-initiated attention.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Literal

from loguru import logger

from backend.core.event_bus import AliceEvent, EventBus

AttentionPriority = Literal["low", "normal", "urgent"]


class AttentionDecision(StrEnum):
    """What the service decided to do with an attention request.

    ``INTERRUPT`` and ``QUEUE`` are part of the vocabulary (spec §8) but the
    v1 policy never returns them — reserved for the rich implementation.
    """

    INTERRUPT = "interrupt"
    NOTIFY = "notify"
    QUEUE = "queue"
    DROP = "drop"


class AttentionService:
    """Minimal v1 policy: disabled → DROP, cooldown → DROP, else NOTIFY.

    Args:
        event_bus: Bus the ``attention.raised`` events are emitted on
            (bridged to the events WS in ``stage_surfaces``).
        enabled: Master switch (``attention.enabled``); off means the
            assistant never takes initiative towards the user.
        cooldown_s: Minimum seconds between two non-urgent notifications
            (anti-spam). ``urgent`` requests bypass the cooldown.
    """

    def __init__(
        self, *, event_bus: EventBus, enabled: bool, cooldown_s: float,
    ) -> None:
        self._bus = event_bus
        self._enabled = enabled
        self._cooldown_s = cooldown_s
        self._last_notify_monotonic: float | None = None

    async def request_attention(
        self,
        *,
        source: str,
        message: str,
        conversation_id: str | None = None,
        priority: AttentionPriority = "normal",
    ) -> AttentionDecision:
        """Decide whether/how to surface ``message`` to the user.

        Returns the decision; on ``NOTIFY`` an ``attention.raised`` event is
        emitted (bridged to the events WS → UI toast).
        """
        if not self._enabled:
            logger.debug("Attention: dropped (disabled): {} — {}", source, message)
            return AttentionDecision.DROP

        now = time.monotonic()
        in_cooldown = (
            self._last_notify_monotonic is not None
            and (now - self._last_notify_monotonic) < self._cooldown_s
        )
        if in_cooldown and priority != "urgent":
            logger.debug("Attention: dropped (cooldown): {} — {}", source, message)
            return AttentionDecision.DROP

        self._last_notify_monotonic = now
        await self._bus.emit(
            AliceEvent.ATTENTION_RAISED,
            source=source,
            message=message,
            priority=priority,
            conversation_id=conversation_id,
        )
        return AttentionDecision.NOTIFY
