"""AL\\CE — Centralized service lifecycle orchestrator.

The :class:`ServiceOrchestrator` owns the lifecycle of every managed
service (LM Studio probe, STT, TTS, VRAM monitor, TRELLIS external
process, …).  Responsibilities:

* Topological start/stop ordering based on declared ``depends_on``.
* Periodic health polling (one task per service, configurable interval).
* Restart with exponential backoff.
* Emission of ``service.status`` events on the shared :class:`EventBus`
  whenever a service's status transitions to a new value.

The orchestrator never imports concrete service classes — it operates
exclusively through the :class:`ManagedService` Protocol so concrete
adapters live in ``backend.core.managed_services``.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol, runtime_checkable

from loguru import logger

from backend.core.event_bus import AliceEvent, EventBus

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

ServiceStatus = Literal["up", "degraded", "down", "starting"]
ServiceKind = Literal["external_process", "http_endpoint", "internal"]
RestartPolicy = Literal["always", "on-failure", "never"]


@dataclass
class ServiceHealth:
    """Snapshot of a service's most recently observed health.

    Attributes:
        status: Current high-level status.
        detail: Optional free-form detail message (error text, version, …).
        last_check: Timestamp of the last health probe.
    """

    status: ServiceStatus
    detail: str | None
    last_check: datetime

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "status": self.status,
            "detail": self.detail,
            "last_check": self.last_check.isoformat(),
        }


@runtime_checkable
class ManagedService(Protocol):
    """Protocol every orchestrator-managed service must implement.

    Attributes:
        name: Unique identifier (e.g. ``"stt"``, ``"lmstudio"``).
        kind: Service category for the UI / metrics.
        depends_on: Names of services that must be started first.
        restart_policy: Auto-restart behaviour when health drops.
        health_interval_s: Seconds between health polls.
    """

    name: str
    kind: ServiceKind
    depends_on: list[str]
    restart_policy: RestartPolicy
    health_interval_s: float

    async def start(self) -> None:
        """Start the underlying service (idempotent)."""
        ...

    async def stop(self) -> None:
        """Stop the underlying service (idempotent)."""
        ...

    async def health(self) -> ServiceHealth:
        """Return a fresh health snapshot."""
        ...


# ---------------------------------------------------------------------------
# Internal record per registered service
# ---------------------------------------------------------------------------


@dataclass
class _Entry:
    """Per-service runtime state held by the orchestrator."""

    service: ManagedService
    last_health: ServiceHealth
    poll_task: asyncio.Task[None] | None = None
    restart_task: asyncio.Task[None] | None = None
    started: bool = False
    backoff_attempts: int = 0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


# Backoff schedule (seconds) for restart attempts.
_BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)

# Hard-stop timeout for ``stop()`` calls; wrappers must self-force-kill.
_STOP_TIMEOUT_S: float = 10.0


class ServiceOrchestrator:
    """Central registry + lifecycle manager for all managed services.

    Args:
        event_bus: Shared event bus used to emit ``service.status`` events.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self._stopped: bool = False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, service: ManagedService) -> None:
        """Add *service* to the registry.

        Must be called before :meth:`start_all`.

        Raises:
            ValueError: If a service with the same ``name`` is already
                registered.
        """
        if service.name in self._entries:
            raise ValueError(f"Service '{service.name}' already registered")
        self._entries[service.name] = _Entry(
            service=service,
            last_health=ServiceHealth(
                status="down",
                detail="not started",
                last_check=datetime.now(timezone.utc),
            ),
        )
        logger.debug(
            "Orchestrator: registered '{}' (kind={}, deps={})",
            service.name, service.kind, service.depends_on,
        )

    def services(self) -> list[ManagedService]:
        """Return all registered services in registration order."""
        return [e.service for e in self._entries.values()]

    def get(self, name: str) -> ManagedService | None:
        """Return the registered service named *name* or ``None``."""
        entry = self._entries.get(name)
        return entry.service if entry else None

    async def attach_started(self, service: ManagedService) -> None:
        """Register *service* as already-running and begin health polling.

        Used by the FastAPI lifespan when concrete services are
        constructed and started outside the orchestrator (legacy path).
        Performs an immediate health probe and spawns the poll task so
        the snapshot is non-empty as soon as the API comes up.

        Raises:
            ValueError: If a service with the same ``name`` is already
                registered.
        """
        self.register(service)
        entry = self._entries[service.name]
        entry.started = True
        await self._probe(service.name)
        if entry.poll_task is None or entry.poll_task.done():
            entry.poll_task = asyncio.create_task(
                self._poll_loop(service.name),
                name=f"orch-poll-{service.name}",
            )

    # ------------------------------------------------------------------
    # Topological ordering
    # ------------------------------------------------------------------

    def _topological_order(self) -> list[str]:
        """Return service names in dependency order (deps first).

        Raises:
            ValueError: If a cycle is detected or a dependency is missing.
        """
        in_degree: dict[str, int] = {n: 0 for n in self._entries}
        graph: dict[str, list[str]] = defaultdict(list)
        for name, entry in self._entries.items():
            for dep in entry.service.depends_on:
                if dep not in self._entries:
                    raise ValueError(
                        f"Service '{name}' depends on unknown '{dep}'"
                    )
                graph[dep].append(name)
                in_degree[name] += 1

        queue: deque[str] = deque(
            n for n, d in in_degree.items() if d == 0
        )
        order: list[str] = []
        while queue:
            n = queue.popleft()
            order.append(n)
            for nxt in graph[n]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(self._entries):
            cyclic = [n for n, d in in_degree.items() if d > 0]
            raise ValueError(
                f"Service dependency cycle detected involving: {cyclic}"
            )
        return order

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_all(self) -> None:
        """Start every registered service in topological order.

        Failures are logged but do not abort the remaining startup so
        the system can come up partially degraded.
        """
        self._stopped = False
        order = self._topological_order()
        logger.info("Orchestrator: starting services in order {}", order)
        for name in order:
            await self._start_one(name)

    async def stop_all(self) -> None:
        """Stop every registered service in reverse topological order.

        Cancels poll tasks first so health probes do not race with shutdown.
        """
        self._stopped = True
        # Cancel all poll/restart tasks first.
        for entry in self._entries.values():
            for task in (entry.poll_task, entry.restart_task):
                if task is not None and not task.done():
                    task.cancel()
        # Await cancellations so logs stay clean.
        for entry in self._entries.values():
            for task in (entry.poll_task, entry.restart_task):
                if task is None:
                    continue
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            entry.poll_task = None
            entry.restart_task = None

        order = list(reversed(self._topological_order()))
        logger.info("Orchestrator: stopping services in order {}", order)
        for name in order:
            await self._stop_one(name)

    async def shutdown_polling(self) -> None:
        """Cancel all background poll/restart tasks without stopping services.

        Used by the FastAPI lifespan when concrete services are stopped
        through the legacy direct path; the orchestrator only owns the
        async tasks it spawned.
        """
        self._stopped = True
        for entry in self._entries.values():
            for task in (entry.poll_task, entry.restart_task):
                if task is not None and not task.done():
                    task.cancel()
        for entry in self._entries.values():
            for task in (entry.poll_task, entry.restart_task):
                if task is None:
                    continue
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            entry.poll_task = None
            entry.restart_task = None

    async def restart(self, name: str) -> None:
        """Restart the named service with exponential backoff.

        Schedules the restart in a background task and returns immediately
        so REST callers can answer ``202 Accepted``.

        Raises:
            KeyError: If *name* is not registered.
        """
        if name not in self._entries:
            raise KeyError(name)
        entry = self._entries[name]
        if entry.restart_task is not None and not entry.restart_task.done():
            logger.warning(
                "Orchestrator: restart for '{}' already in progress", name,
            )
            return
        if entry.started and entry.last_health.status == "starting":
            logger.info(
                "Orchestrator: '{}' restart ignored because it is already starting",
                name,
            )
            return
        entry.restart_task = asyncio.create_task(
            self._restart_with_backoff(name),
            name=f"orch-restart-{name}",
        )

    async def stop(self, name: str) -> None:
        """Stop the named service immediately.

        Args:
            name: Registered service name.

        Raises:
            KeyError: If *name* is not registered.
        """
        if name not in self._entries:
            raise KeyError(name)
        entry = self._entries[name]
        if entry.restart_task is not None and not entry.restart_task.done():
            entry.restart_task.cancel()
            try:
                await entry.restart_task
            except (asyncio.CancelledError, Exception):
                pass
            entry.restart_task = None
        entry.backoff_attempts = 0
        await self._stop_one(name)

    # ------------------------------------------------------------------
    # Health & status
    # ------------------------------------------------------------------

    def snapshot(self) -> list[dict]:
        """Return a list of dicts describing every registered service."""
        return [
            {
                "name": e.service.name,
                "kind": e.service.kind,
                "depends_on": list(e.service.depends_on),
                "restart_policy": e.service.restart_policy,
                "status": e.last_health.status,
                "detail": e.last_health.detail,
                "last_check": e.last_health.last_check.isoformat(),
                "backoff_attempts": e.backoff_attempts,
            }
            for e in self._entries.values()
        ]

    def health_of(self, name: str) -> ServiceHealth | None:
        """Return the cached health for *name* or ``None``."""
        entry = self._entries.get(name)
        return entry.last_health if entry else None

    # ------------------------------------------------------------------
    # Internal — single-service operations
    # ------------------------------------------------------------------

    async def _start_one(self, name: str) -> None:
        entry = self._entries[name]
        await self._set_status(
            name, "starting", detail=None, force_emit=True,
        )
        try:
            await entry.service.start()
            entry.started = True
            entry.backoff_attempts = 0
        except Exception as exc:
            logger.error(
                "Orchestrator: '{}' start failed: {}", name, exc,
            )
            await self._set_status(name, "down", detail=str(exc))
            # Schedule auto-restart if policy allows.
            if entry.service.restart_policy == "always":
                await self.restart(name)
            return

        # Probe immediately so the snapshot reflects reality.
        await self._probe(name)
        # Spawn the periodic health poll.
        if entry.poll_task is None or entry.poll_task.done():
            entry.poll_task = asyncio.create_task(
                self._poll_loop(name),
                name=f"orch-poll-{name}",
            )

    async def _stop_one(self, name: str) -> None:
        entry = self._entries[name]
        if not entry.started:
            return
        try:
            await asyncio.wait_for(
                entry.service.stop(), timeout=_STOP_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Orchestrator: '{}' stop() exceeded {}s — wrapper must "
                "have force-killed by now", name, _STOP_TIMEOUT_S,
            )
        except Exception as exc:
            logger.error("Orchestrator: '{}' stop failed: {}", name, exc)
        entry.started = False
        await self._set_status(name, "down", detail="stopped")

    async def _restart_with_backoff(self, name: str) -> None:
        entry = self._entries[name]
        # Stop first (best-effort).
        try:
            await self._stop_one(name)
        except Exception:
            pass

        for attempt, delay in enumerate(_BACKOFF_SCHEDULE, start=1):
            if self._stopped:
                return
            entry.backoff_attempts = attempt
            logger.info(
                "Orchestrator: restart attempt {}/{} for '{}' in {}s",
                attempt, len(_BACKOFF_SCHEDULE), name, delay,
            )
            await asyncio.sleep(delay)
            try:
                await entry.service.start()
                entry.started = True
                entry.backoff_attempts = 0
                await self._probe(name)
                if entry.poll_task is None or entry.poll_task.done():
                    entry.poll_task = asyncio.create_task(
                        self._poll_loop(name),
                        name=f"orch-poll-{name}",
                    )
                return
            except Exception as exc:
                logger.warning(
                    "Orchestrator: restart {}/{} for '{}' failed: {}",
                    attempt, len(_BACKOFF_SCHEDULE), name, exc,
                )
                await self._set_status(name, "down", detail=str(exc))
        logger.error(
            "Orchestrator: '{}' exhausted {} restart attempts",
            name, len(_BACKOFF_SCHEDULE),
        )

    async def _poll_loop(self, name: str) -> None:
        """Background task that polls a single service's health."""
        entry = self._entries[name]
        interval = max(0.5, float(entry.service.health_interval_s))
        try:
            while not self._stopped:
                await asyncio.sleep(interval)
                if self._stopped:
                    return
                await self._probe(name)
                # On-failure auto-restart trigger.
                if (
                    entry.last_health.status == "down"
                    and entry.service.restart_policy in ("always", "on-failure")
                    and entry.started
                    and (entry.restart_task is None or entry.restart_task.done())
                ):
                    logger.info(
                        "Orchestrator: '{}' down — scheduling auto-restart",
                        name,
                    )
                    await self.restart(name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # defensive: never let the loop die silently
            logger.exception(
                "Orchestrator: poll loop for '{}' crashed: {}", name, exc,
            )

    async def _probe(self, name: str) -> None:
        """Run a single health probe and update cached status."""
        entry = self._entries[name]
        try:
            health = await entry.service.health()
        except Exception as exc:
            logger.warning(
                "Orchestrator: health() raised for '{}': {}", name, exc,
            )
            health = ServiceHealth(
                status="down",
                detail=f"health probe error: {exc}",
                last_check=datetime.now(timezone.utc),
            )
        await self._apply_health(name, health)

    async def _apply_health(self, name: str, health: ServiceHealth) -> None:
        """Store *health* and emit an event when the status changed."""
        entry = self._entries[name]
        prev = entry.last_health
        entry.last_health = health
        if prev.status != health.status or prev.detail != health.detail:
            await self._emit_status(name, health)

    async def _set_status(
        self,
        name: str,
        status: ServiceStatus,
        *,
        detail: str | None,
        force_emit: bool = False,
    ) -> None:
        """Helper used by start/stop paths to set a synthetic status."""
        entry = self._entries[name]
        health = ServiceHealth(
            status=status,
            detail=detail,
            last_check=datetime.now(timezone.utc),
        )
        prev = entry.last_health
        entry.last_health = health
        if force_emit or prev.status != status or prev.detail != detail:
            await self._emit_status(name, health)

    async def _emit_status(self, name: str, health: ServiceHealth) -> None:
        """Publish a ``service.status`` event on the bus."""
        payload = {
            "type": "service.status",
            "service": name,
            "status": health.status,
            "detail": health.detail,
            "timestamp": health.last_check.isoformat(),
        }
        try:
            await self._event_bus.emit(AliceEvent.SERVICE_STATUS, **payload)
        except Exception as exc:
            logger.warning(
                "Orchestrator: failed to emit status for '{}': {}", name, exc,
            )
