"""Tool-selection connection-status resolution: dedupe + bound + cache + parallel.

Regression tests for the per-message hang where ``get_available_tools`` called
``plugin.get_connection_status()`` once *per tool*, sequentially, uncached and
unbounded — so a single down plugin (e.g. continuum probing a dead HTTP
endpoint) stalled every turn for ~80s.

The contract these tests pin:

* status is resolved **once per plugin** per selection call (not once per tool);
* a slow/hanging status probe is **bounded** by a timeout and the plugin is
  treated as unavailable (its tools excluded) instead of blocking the turn;
* probes for distinct plugins run **concurrently** (cost ≈ slowest, not sum);
* statuses are **cached** with a short TTL so back-to-back turns don't re-probe.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core.event_bus import EventBus
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.core.tool_registry import ToolRegistry


class CountingPlugin(BasePlugin):
    """Plugin that counts status probes and can simulate a slow probe."""

    plugin_version = "1.0.0"
    plugin_description = "counts connection-status probes"
    plugin_dependencies: list[str] = []

    def __init__(
        self,
        *,
        name: str,
        tools: list[ToolDefinition],
        status: ConnectionStatus = ConnectionStatus.CONNECTED,
        delay: float = 0.0,
    ) -> None:
        self.plugin_name = name
        super().__init__()
        self._tools = tools
        self._status = status
        self._delay = delay
        self.status_calls = 0

    def get_tools(self) -> list[ToolDefinition]:
        return self._tools

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext,
    ) -> ToolResult:
        return ToolResult.ok(f"executed {tool_name}")

    async def get_connection_status(self) -> ConnectionStatus:
        self.status_calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._status


class _PM:
    """Minimal plugin-manager double."""

    def __init__(self, plugins: dict[str, CountingPlugin]) -> None:
        self._plugins = plugins

    def get_all_plugins(self) -> dict[str, CountingPlugin]:
        return dict(self._plugins)

    def get_plugin(self, name: str) -> CountingPlugin | None:
        return self._plugins.get(name)


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description="t", parameters=None)


@pytest.mark.asyncio
async def test_status_probed_once_per_plugin_not_per_tool(event_bus: EventBus):
    """A plugin exposing N tools is status-probed once, not N times."""
    plugin = CountingPlugin(
        name="continuum",
        tools=[_tool("a"), _tool("b"), _tool("c")],
    )
    reg = ToolRegistry(_PM({"continuum": plugin}), event_bus)
    await reg.refresh()

    await reg.get_available_tools()

    assert plugin.status_calls == 1


@pytest.mark.asyncio
async def test_slow_status_probe_is_bounded_and_plugin_excluded(
    event_bus: EventBus,
):
    """A hanging probe is timed out; the plugin's tools are excluded fast."""
    slow = CountingPlugin(
        name="continuum", tools=[_tool("note")], delay=5.0,
    )
    fast = CountingPlugin(name="weather", tools=[_tool("forecast")])
    reg = ToolRegistry(_PM({"continuum": slow, "weather": fast}), event_bus)
    reg._status_probe_timeout = 0.2

    await reg.refresh()
    loop = asyncio.get_running_loop()
    start = loop.time()
    available = await reg.get_available_tools()
    elapsed = loop.time() - start

    assert elapsed < 2.0  # bounded by the timeout, not the 5s sleep
    names = {t["function"]["name"] for t in available}
    assert "weather_forecast" in names      # healthy plugin still offered
    assert "continuum_note" not in names     # timed-out plugin excluded


@pytest.mark.asyncio
async def test_status_probes_run_concurrently(event_bus: EventBus):
    """Distinct plugins are probed in parallel — total ≈ slowest, not sum."""
    plugins = {
        f"p{i}": CountingPlugin(name=f"p{i}", tools=[_tool("x")], delay=0.4)
        for i in range(4)
    }
    reg = ToolRegistry(_PM(plugins), event_bus)
    reg._status_probe_timeout = 1.0

    await reg.refresh()
    loop = asyncio.get_running_loop()
    start = loop.time()
    await reg.get_available_tools()
    elapsed = loop.time() - start

    # Sequential would be 4 × 0.4 = 1.6s; concurrent ≈ 0.4s.
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_status_cached_across_calls(event_bus: EventBus):
    """Back-to-back selections reuse a cached status (probe runs once)."""
    plugin = CountingPlugin(name="continuum", tools=[_tool("a")])
    reg = ToolRegistry(_PM({"continuum": plugin}), event_bus)
    await reg.refresh()

    await reg.get_available_tools()
    await reg.get_available_tools()

    assert plugin.status_calls == 1


@pytest.mark.asyncio
async def test_clear_status_cache_forces_reprobe(event_bus: EventBus):
    """clear_status_cache() drops cached statuses so the next call re-probes.

    The vector-store repair flow calls this after re-wiring services, so a
    plugin whose backing service just changed (e.g. memory after Qdrant is
    repaired) is re-evaluated instead of serving a stale cached status.
    """
    plugin = CountingPlugin(name="continuum", tools=[_tool("a")])
    reg = ToolRegistry(_PM({"continuum": plugin}), event_bus)
    await reg.refresh()

    await reg.get_available_tools()
    assert plugin.status_calls == 1

    reg.clear_status_cache()
    await reg.get_available_tools()
    assert plugin.status_calls == 2
