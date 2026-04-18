"""AL\\CE — VRAM monitoring service with budget tracking and alerts."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from backend.core.event_bus import AliceEvent

if TYPE_CHECKING:
    from backend.core.event_bus import EventBus

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VRAM_WARNING_THRESHOLD_MB: int = 14_000   # 14 GB
VRAM_CRITICAL_THRESHOLD_MB: int = 15_000  # 15 GB
DEFAULT_POLL_INTERVAL_S: float = 30.0

# ---------------------------------------------------------------------------
# pynvml — optional dependency
# ---------------------------------------------------------------------------

try:
    import pynvml as _pynvml

    _HAS_PYNVML = True
except ImportError:  # pragma: no cover
    _pynvml = None  # type: ignore[assignment]
    _HAS_PYNVML = False


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VRAMUsage:
    """Snapshot of GPU VRAM state."""

    total_mb: int
    used_mb: int
    free_mb: int
    utilization_percent: float
    per_component: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class VRAMMonitor:
    """Monitors GPU VRAM via *pynvml* or *nvidia-smi* and emits alerts.

    Lifecycle:
        ``start()``  → initialise backend + begin polling
        ``stop()``   → cancel polling + cleanup

    Budget tracking lets each component declare its estimated VRAM so that
    ``VRAMUsage.per_component`` is always available for dashboards.
    """

    def __init__(
        self,
        event_bus: EventBus,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL_S,
        warning_mb: int = VRAM_WARNING_THRESHOLD_MB,
        critical_mb: int = VRAM_CRITICAL_THRESHOLD_MB,
    ) -> None:
        self._event_bus = event_bus
        self._poll_interval = poll_interval
        self._warning_mb = warning_mb
        self._critical_mb = critical_mb

        self._poll_task: asyncio.Task[None] | None = None
        self._budget: dict[str, int] = {}
        self._available: bool = False
        self._use_pynvml: bool = False
        self._last_usage: VRAMUsage | None = None
        self._pynvml_handle: object | None = None
        self._warned: bool = False
        self._critical_warned: bool = False

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Initialise the GPU backend and begin background polling."""
        self._available = await asyncio.to_thread(self._init_backend)
        if not self._available:
            logger.warning("No GPU monitoring backend available — "
                           "VRAM monitor disabled")
            return
        logger.info("VRAM monitor started (backend={})",
                     "pynvml" if self._use_pynvml else "nvidia-smi")
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name="vram-poll",
        )

    async def stop(self) -> None:
        """Cancel polling and release pynvml resources."""
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        if self._use_pynvml:
            await asyncio.to_thread(self._shutdown_pynvml)
        logger.info("VRAM monitor stopped")

    async def health_check(self) -> bool:
        """Return *True* if GPU monitoring is operational."""
        return self._available

    # -- budget -------------------------------------------------------------

    def register_component(self, name: str, estimated_mb: int) -> None:
        """Declare *estimated_mb* of VRAM budget for *name*."""
        self._budget[name] = estimated_mb
        logger.debug("VRAM budget registered: {} → {} MB", name, estimated_mb)

    def unregister_component(self, name: str) -> None:
        """Remove *name* from VRAM budget tracking."""
        self._budget.pop(name, None)
        logger.debug("VRAM budget unregistered: {}", name)

    # -- query --------------------------------------------------------------

    async def get_usage(self) -> VRAMUsage:
        """Read current VRAM and return a ``VRAMUsage`` snapshot."""
        if not self._available:
            return VRAMUsage(
                total_mb=0,
                used_mb=0,
                free_mb=0,
                utilization_percent=0.0,
                per_component=dict(self._budget),
            )
        total, used = await asyncio.to_thread(self._read_vram)
        free = total - used
        pct = (used / total * 100.0) if total > 0 else 0.0
        usage = VRAMUsage(
            total_mb=total,
            used_mb=used,
            free_mb=free,
            utilization_percent=round(pct, 1),
            per_component=dict(self._budget),
        )
        self._last_usage = usage
        return usage

    @property
    def last_usage(self) -> VRAMUsage | None:
        """Most recent cached ``VRAMUsage`` (``None`` before first poll)."""
        return self._last_usage

    # -- internal: polling --------------------------------------------------

    async def _poll_loop(self) -> None:
        """Periodically sample VRAM and emit threshold events.

        Uses adaptive polling: normal interval when GPU consumers are
        registered, double interval when idle (no registered components).
        """
        while True:
            try:
                # Adaptive interval: poll less when nothing uses the GPU
                interval = self._poll_interval
                if not self._budget:
                    interval = self._poll_interval * 2

                usage = await self.get_usage()
                if usage.used_mb >= self._critical_mb:
                    if not self._critical_warned:
                        logger.warning("VRAM critical: {} MB used", usage.used_mb)
                        await self._event_bus.emit(
                            AliceEvent.VRAM_CRITICAL, usage=usage,
                        )
                        self._critical_warned = True
                        self._warned = True
                elif usage.used_mb >= self._warning_mb:
                    self._critical_warned = False
                    if not self._warned:
                        logger.warning("VRAM warning: {} MB used", usage.used_mb)
                        await self._event_bus.emit(
                            AliceEvent.VRAM_WARNING, usage=usage,
                        )
                        self._warned = True
                else:
                    self._warned = False
                    self._critical_warned = False
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.opt(exception=True).error("VRAM poll error")
            await asyncio.sleep(interval)

    # -- internal: backends -------------------------------------------------

    def _init_backend(self) -> bool:
        """Try pynvml first, then nvidia-smi. Return *True* on success."""
        if _HAS_PYNVML:
            try:
                _pynvml.nvmlInit()  # type: ignore[union-attr]
                self._pynvml_handle = (
                    _pynvml.nvmlDeviceGetHandleByIndex(0)  # type: ignore[union-attr]
                )
                self._use_pynvml = True
                return True
            except Exception:
                logger.debug("pynvml init failed, trying nvidia-smi")
        # Fallback: nvidia-smi
        try:
            self._read_vram_nvidia_smi()
            return True
        except Exception:
            return False

    def _read_vram(self) -> tuple[int, int]:
        """Route to the active backend (blocking)."""
        if self._use_pynvml:
            return self._read_vram_pynvml()
        return self._read_vram_nvidia_smi()

    def _read_vram_pynvml(self) -> tuple[int, int]:
        """Return *(total_mb, used_mb)* via pynvml (blocking)."""
        info = _pynvml.nvmlDeviceGetMemoryInfo(  # type: ignore[union-attr]
            self._pynvml_handle,
        )
        return int(info.total // (1024 * 1024)), int(info.used // (1024 * 1024))

    def _read_vram_nvidia_smi(self) -> tuple[int, int]:
        """Return *(total_mb, used_mb)* via nvidia-smi subprocess (blocking)."""
        result = subprocess.run(
            [
                "nvidia-smi",
                "--id=0",
                "--query-gpu=memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        line = result.stdout.strip().splitlines()[0]
        total_s, used_s = line.split(",")
        return int(total_s.strip()), int(used_s.strip())

    def _shutdown_pynvml(self) -> None:
        """Release pynvml resources (blocking)."""
        try:
            _pynvml.nvmlShutdown()  # type: ignore[union-attr]
        except Exception:
            logger.opt(exception=True).debug("pynvml shutdown error")

