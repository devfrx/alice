"""Tests for backend.core.plugin_base and backend.core.plugin_manager.

Covers BasePlugin lifecycle, PluginManager startup/shutdown, dependency
resolution (Kahn's algorithm), crash isolation, collision detection,
status reporting, and health checks.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus, OmniaEvent
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.core.plugin_manager import PLUGIN_REGISTRY, PluginManager


# ===================================================================
# Helpers — concrete mock plugins
# ===================================================================


class StubPlugin(BasePlugin):
    """Minimal concrete plugin for testing."""

    plugin_name = "stub"
    plugin_version = "0.1.0"
    plugin_description = "A stub plugin for tests"
    plugin_dependencies: list[str] = []

    def get_tools(self) -> list[ToolDefinition]:
        return [ToolDefinition(name="stub_ping", description="Pong")]

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext
    ) -> ToolResult:
        return ToolResult.ok("pong")


class AlphaPlugin(BasePlugin):
    """Plugin with no dependencies, priority 80."""

    plugin_name = "alpha"
    plugin_version = "1.0.0"
    plugin_description = "Alpha plugin"
    plugin_dependencies: list[str] = []
    plugin_priority = 80

    def get_tools(self) -> list[ToolDefinition]:
        return []

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext
    ) -> ToolResult:
        return ToolResult.ok(None)


class BetaPlugin(BasePlugin):
    """Plugin depending on alpha, priority 50."""

    plugin_name = "beta"
    plugin_version = "1.0.0"
    plugin_description = "Beta plugin"
    plugin_dependencies: list[str] = ["alpha"]
    plugin_priority = 50

    def get_tools(self) -> list[ToolDefinition]:
        return []

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext
    ) -> ToolResult:
        return ToolResult.ok(None)


class GammaPlugin(BasePlugin):
    """Plugin depending on beta (transitive on alpha), priority 30."""

    plugin_name = "gamma"
    plugin_version = "1.0.0"
    plugin_description = "Gamma plugin"
    plugin_dependencies: list[str] = ["beta"]
    plugin_priority = 30

    def get_tools(self) -> list[ToolDefinition]:
        return []

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext
    ) -> ToolResult:
        return ToolResult.ok(None)


class CycleAPlugin(BasePlugin):
    """Cycle test: depends on cycle_b."""

    plugin_name = "cycle_a"
    plugin_version = "1.0.0"
    plugin_description = "Cycle A"
    plugin_dependencies: list[str] = ["cycle_b"]

    def get_tools(self) -> list[ToolDefinition]:
        return []

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext
    ) -> ToolResult:
        return ToolResult.ok(None)


class CycleBPlugin(BasePlugin):
    """Cycle test: depends on cycle_a."""

    plugin_name = "cycle_b"
    plugin_version = "1.0.0"
    plugin_description = "Cycle B"
    plugin_dependencies: list[str] = ["cycle_a"]

    def get_tools(self) -> list[ToolDefinition]:
        return []

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext
    ) -> ToolResult:
        return ToolResult.ok(None)


class CrashingPlugin(BasePlugin):
    """Plugin that raises during initialize()."""

    plugin_name = "crasher"
    plugin_version = "0.0.1"
    plugin_description = "I crash on init"
    plugin_dependencies: list[str] = []

    async def initialize(self, ctx: AppContext) -> None:
        raise RuntimeError("Boom on init")

    def get_tools(self) -> list[ToolDefinition]:
        return []

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext
    ) -> ToolResult:
        return ToolResult.ok(None)


class StatusPlugin(BasePlugin):
    """Plugin that reports a custom connection status."""

    plugin_name = "status_reporter"
    plugin_version = "1.0.0"
    plugin_description = "Reports connected"
    plugin_dependencies: list[str] = []

    def get_tools(self) -> list[ToolDefinition]:
        return []

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext
    ) -> ToolResult:
        return ToolResult.ok(None)

    async def get_connection_status(self) -> ConnectionStatus:
        return ConnectionStatus.CONNECTED


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def ctx() -> AppContext:
    """Minimal AppContext with real config and fresh EventBus."""
    return AppContext(config=load_config(), event_bus=EventBus())


@pytest.fixture
def manager(ctx: AppContext) -> PluginManager:
    return PluginManager(ctx)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure PLUGIN_REGISTRY is empty before/after each test."""
    saved = dict(PLUGIN_REGISTRY)
    PLUGIN_REGISTRY.clear()
    yield
    PLUGIN_REGISTRY.clear()
    PLUGIN_REGISTRY.update(saved)


# ===================================================================
# BasePlugin lifecycle
# ===================================================================


class TestBasePluginLifecycle:
    """Init, ctx access, cleanup, _ensure_initialized guard."""

    @pytest.mark.asyncio
    async def test_initialize_sets_initialized(self, ctx: AppContext) -> None:
        p = StubPlugin()
        assert p.is_initialized is False
        await p.initialize(ctx)
        assert p.is_initialized is True

    @pytest.mark.asyncio
    async def test_ctx_accessible_after_init(self, ctx: AppContext) -> None:
        p = StubPlugin()
        await p.initialize(ctx)
        assert p.ctx is ctx

    def test_ctx_raises_before_init(self) -> None:
        p = StubPlugin()
        with pytest.raises(RuntimeError, match="not been initialised"):
            _ = p.ctx

    @pytest.mark.asyncio
    async def test_cleanup_resets_initialized(self, ctx: AppContext) -> None:
        p = StubPlugin()
        await p.initialize(ctx)
        await p.cleanup()
        assert p.is_initialized is False

    @pytest.mark.asyncio
    async def test_get_tools_returns_list(self, ctx: AppContext) -> None:
        p = StubPlugin()
        await p.initialize(ctx)
        tools = p.get_tools()
        assert isinstance(tools, list)
        assert len(tools) == 1
        assert tools[0].name == "stub_ping"

    @pytest.mark.asyncio
    async def test_execute_tool(self, ctx: AppContext) -> None:
        p = StubPlugin()
        await p.initialize(ctx)
        ec = ExecutionContext(session_id="s", conversation_id="c", execution_id="e")
        result = await p.execute_tool("stub_ping", {}, ec)
        assert result.success is True
        assert result.content == "pong"

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, ctx: AppContext) -> None:
        """init → startup → tool_call → shutdown → cleanup."""
        p = StubPlugin()
        await p.initialize(ctx)
        await p.on_app_startup()
        ec = ExecutionContext(session_id="s", conversation_id="c", execution_id="e")
        result = await p.execute_tool("stub_ping", {}, ec)
        assert result.success is True
        await p.on_app_shutdown()
        await p.cleanup()
        assert p.is_initialized is False

    def test_logger_bound(self) -> None:
        p = StubPlugin()
        assert p.logger is not None

    @pytest.mark.asyncio
    async def test_default_connection_status(self, ctx: AppContext) -> None:
        p = StubPlugin()
        await p.initialize(ctx)
        status = await p.get_connection_status()
        assert status == ConnectionStatus.UNKNOWN

    def test_check_dependencies_default_empty(self) -> None:
        p = StubPlugin()
        assert p.check_dependencies() == []

    @pytest.mark.asyncio
    async def test_pre_execution_hook_default_true(self) -> None:
        p = StubPlugin()
        assert await p.pre_execution_hook("any", {}) is True


# ===================================================================
# PluginManager — dependency resolution
# ===================================================================


class TestResolveLoadOrder:
    """_resolve_load_order (Kahn's algorithm) edge cases."""

    def test_no_deps(self, manager: PluginManager) -> None:
        reg = PLUGIN_REGISTRY
        reg["alpha"] = AlphaPlugin
        order = manager._resolve_load_order(["alpha"])
        assert order == ["alpha"]

    def test_simple_chain(self, manager: PluginManager) -> None:
        """beta → alpha  ⇒  alpha loaded first."""
        reg = PLUGIN_REGISTRY
        reg["alpha"] = AlphaPlugin
        reg["beta"] = BetaPlugin
        order = manager._resolve_load_order(["alpha", "beta"])
        assert order.index("alpha") < order.index("beta")

    def test_transitive_chain(self, manager: PluginManager) -> None:
        """gamma → beta → alpha  ⇒  alpha first, gamma last."""
        reg = PLUGIN_REGISTRY
        reg["alpha"] = AlphaPlugin
        reg["beta"] = BetaPlugin
        reg["gamma"] = GammaPlugin
        order = manager._resolve_load_order(["alpha", "beta", "gamma"])
        assert order.index("alpha") < order.index("beta")
        assert order.index("beta") < order.index("gamma")

    def test_priority_ordering_among_independents(
        self, manager: PluginManager
    ) -> None:
        """When two plugins have no deps, higher priority goes first."""
        reg = PLUGIN_REGISTRY
        reg["alpha"] = AlphaPlugin  # priority 80
        reg["gamma"] = GammaPlugin  # priority 30, but no dep here

        # Create a version of gamma with no deps for this test
        class IndependentGamma(GammaPlugin):
            plugin_dependencies: list[str] = []
            plugin_priority = 30

        reg["gamma"] = IndependentGamma
        order = manager._resolve_load_order(["alpha", "gamma"])
        assert order[0] == "alpha"  # higher priority first

    def test_cycle_detection(self, manager: PluginManager) -> None:
        reg = PLUGIN_REGISTRY
        reg["cycle_a"] = CycleAPlugin
        reg["cycle_b"] = CycleBPlugin
        with pytest.raises(ValueError, match="cycle"):
            manager._resolve_load_order(["cycle_a", "cycle_b"])

    def test_empty_list(self, manager: PluginManager) -> None:
        order = manager._resolve_load_order([])
        assert order == []

    def test_missing_external_dep_ignored(self, manager: PluginManager) -> None:
        """Plugin depending on an unregistered plugin still loads."""
        reg = PLUGIN_REGISTRY
        reg["beta"] = BetaPlugin  # depends on alpha, but alpha not in list
        order = manager._resolve_load_order(["beta"])
        assert order == ["beta"]


# ===================================================================
# PluginManager — startup / shutdown
# ===================================================================


class TestPluginManagerStartup:
    """Startup sequence: loading, events, ordering."""

    @pytest.mark.asyncio
    async def test_startup_loads_plugins(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["stub"] = StubPlugin
        ctx.config.plugins.enabled = ["stub"]
        await manager.startup()
        assert "stub" in manager.get_loaded_plugin_names()

    @pytest.mark.asyncio
    async def test_startup_emits_plugin_loaded_event(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["stub"] = StubPlugin
        ctx.config.plugins.enabled = ["stub"]
        events: list[str] = []

        async def _on_loaded(**kw: object) -> None:
            events.append(kw["plugin_name"])

        ctx.event_bus.subscribe(OmniaEvent.PLUGIN_LOADED, _on_loaded)
        await manager.startup()
        assert "stub" in events

    @pytest.mark.asyncio
    async def test_startup_skips_unknown_plugins(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        ctx.config.plugins.enabled = ["nonexistent"]
        await manager.startup()
        assert manager.get_loaded_plugin_names() == []

    @pytest.mark.asyncio
    async def test_startup_respects_load_order(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["alpha"] = AlphaPlugin
        PLUGIN_REGISTRY["beta"] = BetaPlugin
        ctx.config.plugins.enabled = ["beta", "alpha"]
        await manager.startup()
        names = manager.get_loaded_plugin_names()
        assert "alpha" in names
        assert "beta" in names
        # Internally, alpha should have been loaded before beta
        assert manager._load_order.index("alpha") < manager._load_order.index("beta")


class TestPluginManagerShutdown:
    """Shutdown: reverse order, cleanup called."""

    @pytest.mark.asyncio
    async def test_shutdown_clears_plugins(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["stub"] = StubPlugin
        ctx.config.plugins.enabled = ["stub"]
        await manager.startup()
        assert len(manager.get_all_plugins()) == 1
        await manager.shutdown()
        assert len(manager.get_all_plugins()) == 0

    @pytest.mark.asyncio
    async def test_shutdown_calls_cleanup(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["stub"] = StubPlugin
        ctx.config.plugins.enabled = ["stub"]
        await manager.startup()
        plugin = manager.get_plugin("stub")
        assert plugin is not None
        assert plugin.is_initialized is True
        await manager.shutdown()
        # After shutdown, the original plugin instance was cleaned up
        assert plugin.is_initialized is False

    @pytest.mark.asyncio
    async def test_shutdown_reverse_order(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        """Verify shutdown iterates in reverse load order."""
        shutdown_order: list[str] = []

        class TrackAlpha(AlphaPlugin):
            async def cleanup(self) -> None:
                shutdown_order.append("alpha")
                await super().cleanup()

        class TrackBeta(BetaPlugin):
            async def cleanup(self) -> None:
                shutdown_order.append("beta")
                await super().cleanup()

        PLUGIN_REGISTRY["alpha"] = TrackAlpha
        PLUGIN_REGISTRY["beta"] = TrackBeta
        ctx.config.plugins.enabled = ["alpha", "beta"]
        await manager.startup()
        await manager.shutdown()
        # alpha loaded first → cleaned up last
        assert shutdown_order == ["beta", "alpha"]


# ===================================================================
# Crash isolation
# ===================================================================


class TestCrashIsolation:
    """A failing plugin must not prevent others from loading."""

    @pytest.mark.asyncio
    async def test_crashing_plugin_does_not_block_others(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["crasher"] = CrashingPlugin
        PLUGIN_REGISTRY["stub"] = StubPlugin
        ctx.config.plugins.enabled = ["crasher", "stub"]
        await manager.startup()
        names = manager.get_loaded_plugin_names()
        assert "crasher" not in names
        assert "stub" in names

    @pytest.mark.asyncio
    async def test_crashing_plugin_emits_failed_event(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["crasher"] = CrashingPlugin
        ctx.config.plugins.enabled = ["crasher"]
        failures: list[str] = []

        async def _on_failed(**kw: object) -> None:
            failures.append(kw["plugin_name"])

        ctx.event_bus.subscribe(OmniaEvent.PLUGIN_FAILED, _on_failed)
        await manager.startup()
        assert "crasher" in failures


# ===================================================================
# Collision detection
# ===================================================================


class TestCollisionDetection:
    """Two plugins with the same registry key — last write wins."""

    @pytest.mark.asyncio
    async def test_same_registry_key_last_wins(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        class StubV1(StubPlugin):
            plugin_version = "1.0.0"

        class StubV2(StubPlugin):
            plugin_version = "2.0.0"

        PLUGIN_REGISTRY["stub"] = StubV1
        PLUGIN_REGISTRY["stub"] = StubV2  # overwrites
        ctx.config.plugins.enabled = ["stub"]
        await manager.startup()
        p = manager.get_plugin("stub")
        assert p is not None
        assert p.plugin_version == "2.0.0"


# ===================================================================
# Accessors & status
# ===================================================================


class TestAccessorsAndStatus:
    """get_plugin, get_all_plugins, get_all_status, health_check."""

    @pytest.mark.asyncio
    async def test_get_plugin_returns_none_for_missing(
        self, manager: PluginManager
    ) -> None:
        assert manager.get_plugin("nope") is None

    @pytest.mark.asyncio
    async def test_get_all_plugins_returns_copy(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["stub"] = StubPlugin
        ctx.config.plugins.enabled = ["stub"]
        await manager.startup()
        all_plugins = manager.get_all_plugins()
        assert isinstance(all_plugins, dict)
        assert "stub" in all_plugins
        # Modifying copy doesn't affect internal state
        all_plugins.pop("stub")
        assert "stub" in manager.get_loaded_plugin_names()

    @pytest.mark.asyncio
    async def test_get_all_status(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["status_reporter"] = StatusPlugin
        ctx.config.plugins.enabled = ["status_reporter"]
        await manager.startup()
        statuses = await manager.get_all_status()
        assert statuses["status_reporter"] == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_get_all_status_default_unknown(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["stub"] = StubPlugin
        ctx.config.plugins.enabled = ["stub"]
        await manager.startup()
        statuses = await manager.get_all_status()
        assert statuses["stub"] == ConnectionStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_health_check_true_with_plugins(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["stub"] = StubPlugin
        ctx.config.plugins.enabled = ["stub"]
        await manager.startup()
        assert await manager.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_false_when_empty(
        self, manager: PluginManager
    ) -> None:
        assert await manager.health_check() is False

    @pytest.mark.asyncio
    async def test_get_loaded_plugin_names_empty(
        self, manager: PluginManager
    ) -> None:
        assert manager.get_loaded_plugin_names() == []


# ===================================================================
# Reload
# ===================================================================


class TestReloadPlugin:
    """Hot-reload via importlib."""

    @pytest.mark.asyncio
    async def test_reload_nonexistent_returns_false(
        self, manager: PluginManager
    ) -> None:
        result = await manager.reload_plugin("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_reload_existing_plugin(
        self, ctx: AppContext, manager: PluginManager
    ) -> None:
        PLUGIN_REGISTRY["stub"] = StubPlugin
        ctx.config.plugins.enabled = ["stub"]
        await manager.startup()

        # Patch importlib.reload and sys.modules so reload succeeds
        with (
            patch("backend.core.plugin_manager.sys") as mock_sys,
            patch("backend.core.plugin_manager.importlib") as mock_importlib,
        ):
            mock_sys.modules.get.return_value = None
            PLUGIN_REGISTRY["stub"] = StubPlugin
            result = await manager.reload_plugin("stub")
            assert result is True
            assert manager.get_plugin("stub") is not None


# ===================================================================
# check_health — status change detection and event emission
# ===================================================================


class TestCheckHealth:
    """check_health() detects status changes and emits events."""

    @pytest.mark.asyncio
    async def test_check_health_detects_status_change(
        self, ctx: AppContext, manager: PluginManager,
    ) -> None:
        """When a plugin's status changes, check_health returns the new value."""
        PLUGIN_REGISTRY["status_reporter"] = StatusPlugin
        ctx.config.plugins.enabled = ["status_reporter"]
        await manager.startup()

        statuses = await manager.check_health()
        assert statuses["status_reporter"] == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_check_health_emits_event_on_change(
        self, ctx: AppContext, manager: PluginManager,
    ) -> None:
        """On status change, PLUGIN_STATUS_CHANGED is emitted."""
        PLUGIN_REGISTRY["status_reporter"] = StatusPlugin
        ctx.config.plugins.enabled = ["status_reporter"]
        await manager.startup()

        events: list[dict] = []

        async def _on_status(**kw: object) -> None:
            events.append(dict(kw))

        ctx.event_bus.subscribe(OmniaEvent.PLUGIN_STATUS_CHANGED, _on_status)

        # First check_health → status goes from None (unknown) to CONNECTED
        await manager.check_health()
        assert len(events) == 1
        assert events[0]["plugin_name"] == "status_reporter"
        assert events[0]["new_status"] == ConnectionStatus.CONNECTED

        # Second check_health → no change → no new event
        events.clear()
        await manager.check_health()
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_check_health_notifies_dependents(
        self, ctx: AppContext, manager: PluginManager,
    ) -> None:
        """When a dependency plugin changes status, dependents are notified."""
        notified: list[tuple[str, ConnectionStatus]] = []

        class DepTrackingBeta(BetaPlugin):
            async def on_dependency_status_change(
                self, plugin_name: str, status: ConnectionStatus,
            ) -> None:
                notified.append((plugin_name, status))

        PLUGIN_REGISTRY["alpha"] = StatusPlugin  # alpha → CONNECTED
        # Override plugin_name for StatusPlugin to match alpha
        StatusPlugin.plugin_name = "alpha"
        PLUGIN_REGISTRY["beta"] = DepTrackingBeta
        ctx.config.plugins.enabled = ["alpha", "beta"]
        await manager.startup()

        await manager.check_health()

        # beta depends on alpha; alpha changed from None → CONNECTED
        assert any(pn == "alpha" for pn, _ in notified)

        # Restore original plugin_name
        StatusPlugin.plugin_name = "status_reporter"
