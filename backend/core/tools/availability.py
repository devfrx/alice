"""AL\\CE — Tool availability: what is reachable.

Per-plugin connection-status probing with a bounded timeout and a short
TTL cache, so tool selection never blocks a turn on a slow or dead
plugin (e.g. continuum probing an unreachable endpoint).
"""

from __future__ import annotations

import asyncio
import time

from loguru import logger

from backend.core.plugin_manager import PluginManager
from backend.core.plugin_models import ConnectionStatus


class AvailabilityProbe:
    """Resolves and caches per-plugin connection status.

    Args:
        plugin_manager: The plugin manager supplying loaded plugins.
    """

    def __init__(self, plugin_manager: PluginManager) -> None:
        self._plugin_manager = plugin_manager
        self._logger = logger.bind(component="AvailabilityProbe")

        # Per-plugin connection-status cache: name -> (monotonic_ts, status).
        # Tool selection resolves each plugin's status ONCE per call, bounded
        # by a timeout and reused within a short TTL, so a slow/down plugin
        # (e.g. continuum probing a dead endpoint) cannot stall a turn.
        self._status_cache: dict[str, tuple[float, ConnectionStatus]] = {}
        self._status_cache_ttl: float = 30.0
        self._status_probe_timeout: float = 3.0

    def clear_status_cache(self) -> None:
        """Drop all cached plugin connection statuses (force a fresh probe).

        Called after the knowledge stack is re-wired so plugins whose backing
        service just changed (e.g. ``memory`` after a Qdrant repair) are
        re-evaluated instead of serving a stale cached status.
        """
        self._status_cache.clear()

    async def resolve_plugin_statuses(
        self, plugin_names: set[str],
    ) -> dict[str, ConnectionStatus]:
        """Resolve each plugin's connection status once — bounded and cached.

        Within a call each plugin is probed at most once (deduped across its
        many tools); probes for distinct plugins run concurrently and are each
        capped by :attr:`_status_probe_timeout`, so a hanging health check
        (e.g. an HTTP probe to a service that is down) cannot stall the turn.
        Results are cached for :attr:`_status_cache_ttl` seconds so
        back-to-back turns reuse them instead of re-probing.

        Args:
            plugin_names: Owning-plugin names to resolve a status for.

        Returns:
            Mapping of plugin name to its (possibly cached) status.
        """
        now = time.monotonic()
        statuses: dict[str, ConnectionStatus] = {}
        stale: list[str] = []
        for name in plugin_names:
            cached = self._status_cache.get(name)
            if cached is not None and (now - cached[0]) < self._status_cache_ttl:
                statuses[name] = cached[1]
            else:
                stale.append(name)

        if stale:
            probed = await asyncio.gather(
                *(self._probe_plugin_status(name) for name in stale)
            )
            probe_ts = time.monotonic()
            for name, status in zip(stale, probed, strict=True):
                self._status_cache[name] = (probe_ts, status)
                statuses[name] = status

        return statuses

    async def _probe_plugin_status(self, plugin_name: str) -> ConnectionStatus:
        """Probe one plugin's status, bounded by :attr:`_status_probe_timeout`.

        Returns ``DISCONNECTED`` on a missing plugin, a timeout, or any error
        so callers treat the plugin as unavailable instead of blocking.
        """
        plugin = self._plugin_manager.get_plugin(plugin_name)
        if plugin is None:
            return ConnectionStatus.DISCONNECTED
        try:
            return await asyncio.wait_for(
                plugin.get_connection_status(),
                timeout=self._status_probe_timeout,
            )
        except TimeoutError:
            self._logger.warning(
                "Connection-status probe for plugin '{}' timed out after "
                "{:.1f}s — treating it as disconnected",
                plugin_name, self._status_probe_timeout,
            )
            return ConnectionStatus.DISCONNECTED
        except Exception as exc:  # noqa: BLE001 — never block selection
            self._logger.debug(
                "Connection-status probe for plugin '{}' failed: {}",
                plugin_name, exc,
            )
            return ConnectionStatus.DISCONNECTED
