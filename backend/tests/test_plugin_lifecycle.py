"""Tests for BasePlugin lifecycle (Phase 3.8).

Verifies the full plugin lifecycle: ``__init__`` → ``initialize(ctx)`` →
``on_app_startup()`` → tool execution → ``on_app_shutdown()`` → ``cleanup()``,
plus all hook and configuration methods.
"""

from __future__ import annotations

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)


# ---------------------------------------------------------------------------
# Tracking plugin — records every lifecycle method call in order
# ---------------------------------------------------------------------------


class LifecyclePlugin(BasePlugin):
    """Concrete plugin that records lifecycle method calls in order."""

    plugin_name = "lifecycle_tracker"
    plugin_version = "1.0.0"
    plugin_description = "Records lifecycle method invocations"
    plugin_dependencies: list[str] = []

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    async def initialize(self, ctx: AppContext) -> None:
        """Record initialize and delegate to super."""
        self.calls.append("initialize")
        await super().initialize(ctx)

    async def on_app_startup(self) -> None:
        """Record on_app_startup."""
        self.calls.append("on_app_startup")

    async def on_app_shutdown(self) -> None:
        """Record on_app_shutdown."""
        self.calls.append("on_app_shutdown")

    async def cleanup(self) -> None:
        """Record cleanup and delegate to super."""
        self.calls.append("cleanup")
        await super().cleanup()

    def get_tools(self) -> list[ToolDefinition]:
        """Return a single test tool definition."""
        return [
            ToolDefinition(
                name="lc_action",
                description="A lifecycle test tool",
                parameters={
                    "type": "object",
                    "properties": {"msg": {"type": "string"}},
                },
            ),
        ]

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext,
    ) -> ToolResult:
        """Record execute and return success."""
        self.calls.append(f"execute:{tool_name}")
        return ToolResult.ok(f"result of {tool_name}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx() -> AppContext:
    """Minimal AppContext with real config and fresh EventBus."""
    return AppContext(config=load_config(), event_bus=EventBus())


@pytest.fixture
def plugin() -> LifecyclePlugin:
    """Uninitialised LifecyclePlugin instance."""
    return LifecyclePlugin()


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Verify the complete lifecycle order and state transitions."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_order(
        self, plugin: LifecyclePlugin, ctx: AppContext,
    ) -> None:
        """init → initialize → startup → execute → shutdown → cleanup."""
        await plugin.initialize(ctx)
        await plugin.on_app_startup()

        ec = ExecutionContext(
            session_id="s", conversation_id="c", execution_id="e",
        )
        await plugin.execute_tool("lc_action", {}, ec)

        await plugin.on_app_shutdown()
        await plugin.cleanup()

        assert plugin.calls == [
            "initialize",
            "on_app_startup",
            "execute:lc_action",
            "on_app_shutdown",
            "cleanup",
        ]

    @pytest.mark.asyncio
    async def test_initialize_stores_context(
        self, plugin: LifecyclePlugin, ctx: AppContext,
    ) -> None:
        """After initialize, ctx and is_initialized are set."""
        assert not plugin.is_initialized
        await plugin.initialize(ctx)
        assert plugin.is_initialized
        assert plugin.ctx is ctx

    @pytest.mark.asyncio
    async def test_cleanup_resets_state(
        self, plugin: LifecyclePlugin, ctx: AppContext,
    ) -> None:
        """After cleanup, is_initialized is False."""
        await plugin.initialize(ctx)
        assert plugin.is_initialized
        await plugin.cleanup()
        assert not plugin.is_initialized

    def test_ctx_before_init_raises(self, plugin: LifecyclePlugin) -> None:
        """Accessing ctx before initialize raises RuntimeError."""
        with pytest.raises(RuntimeError, match="not been initialised"):
            _ = plugin.ctx


# ---------------------------------------------------------------------------
# Tool methods
# ---------------------------------------------------------------------------


class TestToolMethods:
    """Verify get_tools and execute_tool behaviour."""

    def test_get_tools_returns_valid_definitions(
        self, plugin: LifecyclePlugin,
    ) -> None:
        """get_tools returns a list of valid ToolDefinition objects."""
        tools = plugin.get_tools()
        assert len(tools) == 1
        td = tools[0]
        assert isinstance(td, ToolDefinition)
        assert td.name == "lc_action"
        assert td.parameters["type"] == "object"

    @pytest.mark.asyncio
    async def test_execute_tool_returns_result(
        self, plugin: LifecyclePlugin, ctx: AppContext,
    ) -> None:
        """execute_tool returns a successful ToolResult."""
        await plugin.initialize(ctx)
        ec = ExecutionContext(
            session_id="s", conversation_id="c", execution_id="e",
        )
        result = await plugin.execute_tool("lc_action", {"msg": "hi"}, ec)
        assert result.success is True
        assert "lc_action" in result.content


# ---------------------------------------------------------------------------
# Dependency and health
# ---------------------------------------------------------------------------


class TestDependencyAndHealth:
    """Default dependency/health behaviour on BasePlugin."""

    def test_check_dependencies_returns_empty(
        self, plugin: LifecyclePlugin,
    ) -> None:
        """Default check_dependencies reports nothing missing."""
        assert plugin.check_dependencies() == []

    @pytest.mark.asyncio
    async def test_get_connection_status_default(
        self, plugin: LifecyclePlugin, ctx: AppContext,
    ) -> None:
        """Default get_connection_status returns UNKNOWN."""
        await plugin.initialize(ctx)
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Hook and config methods
# ---------------------------------------------------------------------------


class TestHooksAndConfig:
    """Default hook and class-method behaviour."""

    @pytest.mark.asyncio
    async def test_cancel_tool_noop(
        self, plugin: LifecyclePlugin, ctx: AppContext,
    ) -> None:
        """cancel_tool is a no-op by default (does not raise)."""
        await plugin.initialize(ctx)
        await plugin.cancel_tool("lc_action", "exec-id")

    @pytest.mark.asyncio
    async def test_pre_execution_hook_returns_true(
        self, plugin: LifecyclePlugin,
    ) -> None:
        """Default pre_execution_hook returns True (allow execution)."""
        result = await plugin.pre_execution_hook("any_tool", {})
        assert result is True

    def test_get_config_schema_returns_dict(self) -> None:
        """get_config_schema returns a JSON Schema dict."""
        schema = LifecyclePlugin.get_config_schema()
        assert isinstance(schema, dict)
        assert schema.get("type") == "object"

    def test_get_db_models_returns_list(self) -> None:
        """get_db_models returns an empty list by default."""
        models = LifecyclePlugin.get_db_models()
        assert isinstance(models, list)
        assert len(models) == 0
