"""AL\\CE — TTS managed-service adapter."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.core.service_orchestrator import (
    ManagedService,
    ServiceHealth,
)
from backend.services.tts_service import TTSService


class TTSManagedService(ManagedService):
    """Wraps :class:`TTSService` for orchestrator lifecycle management.

    Args:
        service: The TTS service instance.
        health_interval_s: Seconds between health probes.
    """

    # Restart policy is "never" because the only way TTS can fail is
    # when the optional ``piper`` (or XTTS / Kokoro) extra is not
    # installed — a permanent failure that restart cannot fix.  When the
    # engine is unavailable we surface ``degraded`` from health().
    name = "tts"
    kind = "internal"
    depends_on: list[str] = []
    restart_policy = "never"

    def __init__(
        self,
        service: TTSService,
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
                       f"voice={self._service.voice_name}",
                last_check=now,
            )
        return ServiceHealth(
            status="degraded",
            detail=(
                "engine not loaded — install voice extras "
                "(piper-tts) or download a TTS voice"
            ),
            last_check=now,
        )
