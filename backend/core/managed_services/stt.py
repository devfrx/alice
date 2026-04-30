"""AL\\CE — STT managed-service adapter."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.core.service_orchestrator import (
    ManagedService,
    ServiceHealth,
)
from backend.services.stt_service import STTService


class STTManagedService(ManagedService):
    """Wraps :class:`STTService` for orchestrator lifecycle management.

    Args:
        service: The STT service instance.
        health_interval_s: Seconds between health probes.
    """

    # Restart policy is "never" because the only way STT can fail is
    # when the optional ``faster-whisper`` extra is not installed — which
    # is a *permanent* failure that auto-restart cannot fix.  When the
    # engine becomes unavailable we surface ``degraded`` from health() so
    # the orchestrator stops looping.
    name = "stt"
    kind = "internal"
    depends_on: list[str] = []
    restart_policy = "never"

    def __init__(
        self,
        service: STTService,
        *,
        health_interval_s: float = 5.0,
    ) -> None:
        self._service = service
        self.health_interval_s = health_interval_s

    async def start(self) -> None:
        await self._service.start()

    async def stop(self) -> None:
        await self._service.stop()

    async def health(self) -> ServiceHealth:
        ok = await self._service.health_check()
        now = datetime.now(timezone.utc)
        if ok:
            return ServiceHealth(
                status="up",
                detail=f"engine={self._service.engine}, "
                       f"model={self._service.model_name}",
                last_check=now,
            )
        return ServiceHealth(
            status="degraded",
            detail=(
                "engine not loaded — install voice extras "
                "(faster-whisper) or download an STT model"
            ),
            last_check=now,
        )
