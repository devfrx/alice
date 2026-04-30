"""AL\\CE — LM Studio managed-service adapter.

LM Studio is a user-managed external HTTP endpoint.  The orchestrator
**never** auto-starts it — it only probes ``GET /api/v1/models`` to
report availability.
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.core.service_orchestrator import (
    ManagedService,
    ServiceHealth,
)
from backend.services.lmstudio_service import LMStudioManager


class LMStudioManagedService(ManagedService):
    """Health-only wrapper around :class:`LMStudioManager`.

    Args:
        manager: An already-instantiated :class:`LMStudioManager`.
        health_interval_s: Seconds between health probes (default 5s).
    """

    name = "lmstudio"
    kind = "http_endpoint"
    depends_on: list[str] = []
    restart_policy = "never"

    def __init__(
        self,
        manager: LMStudioManager,
        *,
        health_interval_s: float = 5.0,
    ) -> None:
        self._manager = manager
        self.health_interval_s = health_interval_s

    async def start(self) -> None:
        """No-op: LM Studio is user-launched."""
        return None

    async def stop(self) -> None:
        """No-op: never stop LM Studio from inside AL\\CE."""
        return None

    async def health(self) -> ServiceHealth:
        """Probe ``/api/v1/models`` to determine availability."""
        ok = await self._manager.check_health()
        now = datetime.now(timezone.utc)
        if ok:
            return ServiceHealth(
                status="up",
                detail="reachable",
                last_check=now,
            )
        return ServiceHealth(
            status="down",
            detail="LM Studio not reachable",
            last_check=now,
        )
