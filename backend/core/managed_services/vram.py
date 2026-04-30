"""AL\\CE — VRAM monitor managed-service adapter."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.core.service_orchestrator import (
    ManagedService,
    ServiceHealth,
)
from backend.services.vram_monitor import VRAMMonitor


class VRAMManagedService(ManagedService):
    """Wraps :class:`VRAMMonitor` for orchestrator lifecycle management.

    The VRAM monitor is auxiliary — failures should be ``degraded``
    (system keeps running) rather than ``down``.

    Args:
        monitor: The VRAM monitor instance.
        health_interval_s: Seconds between health probes.
    """

    name = "vram"
    kind = "internal"
    depends_on: list[str] = []
    restart_policy = "never"

    def __init__(
        self,
        monitor: VRAMMonitor,
        *,
        health_interval_s: float = 10.0,
    ) -> None:
        self._monitor = monitor
        self.health_interval_s = health_interval_s

    async def start(self) -> None:
        await self._monitor.start()

    async def stop(self) -> None:
        await self._monitor.stop()

    async def health(self) -> ServiceHealth:
        ok = await self._monitor.health_check()
        now = datetime.now(timezone.utc)
        usage = self._monitor.last_usage
        if ok:
            detail = "no recent reading"
            if usage is not None:
                detail = f"{usage.used_mb}/{usage.total_mb} MB used"
            return ServiceHealth(
                status="up", detail=detail, last_check=now,
            )
        return ServiceHealth(
            status="degraded",
            detail="GPU monitoring unavailable",
            last_check=now,
        )
