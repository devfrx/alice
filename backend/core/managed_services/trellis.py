"""AL\\CE — TRELLIS external-process managed-service adapter.

TRELLIS runs as a sibling Python microservice in its own venv (see
``scripts/start-trellis.ps1``).  This wrapper is **health-only** by
default: AL\\CE does not auto-spawn the process — when the service URL
is unreachable we report ``down`` cleanly and let the user start it
themselves.  The class also supports a launcher path so future code can
opt in to subprocess management.
"""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

import httpx
from loguru import logger

from backend.core.service_orchestrator import (
    ManagedService,
    ServiceHealth,
)


class TrellisManagedService(ManagedService):
    """Health-only wrapper around the TRELLIS HTTP microservice.

    Args:
        name: Logical name (``"trellis"`` or ``"trellis2"``).
        service_url: Base URL of the TRELLIS HTTP server.
        launcher: Optional path to a launcher script.  When provided and
            executable, ``start()`` will spawn it; otherwise ``start()``
            is a no-op and the service is treated as user-managed.
        cwd: Working directory for the launcher.
        health_interval_s: Seconds between health probes.
        startup_grace_s: Seconds to wait after launch before the first
            probe is allowed to mark the service as ``down``.
    """

    kind = "external_process"
    depends_on: list[str] = []
    restart_policy = "never"

    def __init__(
        self,
        *,
        name: str = "trellis",
        service_url: str,
        launcher: Path | None = None,
        cwd: Path | None = None,
        health_interval_s: float = 10.0,
        startup_grace_s: float = 30.0,
    ) -> None:
        self.name = name
        self._service_url = service_url.rstrip("/")
        self._launcher = launcher
        self._cwd = cwd
        self.health_interval_s = health_interval_s
        self._startup_grace_s = startup_grace_s
        self._proc: asyncio.subprocess.Process | None = None
        self._started_at: float | None = None

    async def start(self) -> None:
        """Spawn the launcher subprocess if available; otherwise no-op."""
        if self._launcher is None or not Path(self._launcher).exists():
            logger.debug(
                "TRELLIS '{}' launcher not configured/found — skipping spawn "
                "(user-managed mode)", self.name,
            )
            return
        if self._proc is not None and self._proc.returncode is None:
            return  # already running

        # On Windows, .ps1 scripts cannot be exec()ed directly — wrap them
        # with ``powershell.exe -ExecutionPolicy Bypass -File <path>`` so
        # the same launcher works whether AL\\CE was invoked from a venv
        # or from the packaged installer.
        launcher_str = str(self._launcher)
        if os.name == "nt" and launcher_str.lower().endswith(".ps1"):
            argv = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-File", launcher_str,
            ]
        elif launcher_str.lower().endswith((".cmd", ".bat")):
            argv = ["cmd.exe", "/c", launcher_str]
        else:
            argv = [launcher_str]

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self._cwd) if self._cwd else None,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._started_at = asyncio.get_event_loop().time()
            logger.info(
                "TRELLIS '{}' spawned (pid={})", self.name, self._proc.pid,
            )
        except Exception as exc:
            logger.warning(
                "TRELLIS '{}' failed to spawn launcher: {}", self.name, exc,
            )
            self._proc = None

    async def stop(self) -> None:
        """Terminate the spawned process gracefully then force-kill.

        Always returns within ~8s so the orchestrator's 10s stop timeout
        will not trip.
        """
        proc = self._proc
        if proc is None or proc.returncode is not None:
            self._proc = None
            return
        try:
            # Try graceful termination first.
            if os.name == "nt":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "TRELLIS '{}' did not exit on SIGTERM — killing",
                    self.name,
                )
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    logger.error(
                        "TRELLIS '{}' did not respond to SIGKILL", self.name,
                    )
        finally:
            self._proc = None
            self._started_at = None

    async def health(self) -> ServiceHealth:
        """Probe ``GET /health`` (or root) on the TRELLIS service."""
        now = datetime.now(timezone.utc)
        # Honour startup grace so a freshly spawned process isn't
        # immediately reported as ``down``.
        if (
            self._started_at is not None
            and asyncio.get_event_loop().time() - self._started_at
            < self._startup_grace_s
        ):
            return ServiceHealth(
                status="starting",
                detail="warm-up",
                last_check=now,
            )
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._service_url}/health")
            if resp.status_code < 500:
                return ServiceHealth(
                    status="up",
                    detail=f"reachable ({resp.status_code})",
                    last_check=now,
                )
            return ServiceHealth(
                status="degraded",
                detail=f"HTTP {resp.status_code}",
                last_check=now,
            )
        except httpx.HTTPError as exc:
            return ServiceHealth(
                status="down",
                detail=f"unreachable: {exc.__class__.__name__}",
                last_check=now,
            )
