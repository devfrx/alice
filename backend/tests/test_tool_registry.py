"""Comprehensive tests for ToolRegistry (Phase 3.2).

Covers: registration, namespacing, validation, collision detection, lookup,
dynamic availability, execution, result processing, event emission, and
thread safety.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest

from backend.core.event_bus import EventBus, OmniaEvent
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    MAX_TOOL_RESULT_LENGTH,
    ToolDefinition,
    ToolResult,
)
from backend.core.tool_registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers & Mocks
# ---------------------------------------------------------------------------


class MockPlugin(BasePlugin):
    """Concrete test plugin with configurable behaviour."""

    plugin_name = "mock_plugin"
    plugin_version = "1.0.0"
    plugin_description = "Mock test plugin"
    plugin_dependencies: list[str] = []

    def __init__(
        self,
        tools: list | None = None,
        status: ConnectionStatus = ConnectionStatus.CONNECTED,
        execute_fn=None,
        name: str = "mock_plugin",
    ):
        self.plugin_name = name
        super().__init__()
        self._tools = tools or []
        self._status = status
        self._execute_fn = execute_fn

    def get_tools(self) -> list[ToolDefinition]:
        return self._tools

    async def execute_tool(
        self, tool_name: str, args: dict, context: ExecutionContext,
    ) -> ToolResult:
        if self._execute_fn:
            return await self._execute_fn(tool_name, args, context)
        return ToolResult.ok(f"executed {tool_name}")

    async def get_connection_status(self) -> ConnectionStatus:
        return self._status


class MockPluginManager:
    """Lightweight plugin manager mock."""

    def __init__(self, plugins: dict[str, MockPlugin] | None = None):
        self._plugins = plugins or {}

    def get_all_plugins(self) -> dict[str, MockPlugin]:
        return dict(self._plugins)

    def get_plugin(self, name: str) -> MockPlugin | None:
        return self._plugins.get(name)


class FakeToolDefinition:
    """ToolDefinition-like object that bypasses ``__post_init__`` validation.

    Used to test ToolRegistry's own validation layer (invalid names,
    oversized descriptions, bad parameter schemas).
    """

    def __init__(
        self,
        name: str,
        description: str = "A tool",
        parameters: dict[str, Any] | None = None,
        result_type: str = "string",
        supports_cancellation: bool = False,
        timeout_ms: int = 30_000,
        requires_confirmation: bool = False,
        risk_level: str = "safe",
    ):
        self.name = name
        self.description = description
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.result_type = result_type
        self.supports_cancellation = supports_cancellation
        self.timeout_ms = timeout_ms
        self.requires_confirmation = requires_confirmation
        self.risk_level = risk_level


def _make_tool(
    name: str = "test_tool",
    description: str = "A test tool",
    parameters: dict[str, Any] | None = None,
    timeout_ms: int = 30_000,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=description,
        parameters=parameters,
        timeout_ms=timeout_ms,
    )


def _make_context() -> ExecutionContext:
    return ExecutionContext(
        session_id="sess-1",
        conversation_id="conv-1",
        execution_id="exec-1",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_registry(event_bus: EventBus):
    """Factory that builds a ToolRegistry backed by a MockPluginManager."""

    def _factory(plugins: dict[str, MockPlugin] | None = None) -> ToolRegistry:
        pm = MockPluginManager(plugins or {})
        return ToolRegistry(pm, event_bus)

    return _factory


@pytest.fixture
def ctx() -> ExecutionContext:
    return _make_context()


# ---------------------------------------------------------------------------
# Registration & Refresh
# ---------------------------------------------------------------------------


class TestRegistrationAndRefresh:

    @pytest.mark.asyncio
    async def test_refresh_registers_tools_from_plugins(self, make_registry):
        """Two plugins with one tool each → both registered after refresh."""
        p1 = MockPlugin(tools=[_make_tool("tool_a")], name="plugin_a")
        p2 = MockPlugin(tools=[_make_tool("tool_b")], name="plugin_b")
        registry = make_registry({"plugin_a": p1, "plugin_b": p2})
        await registry.refresh()

        tools = registry.get_all_tools()
        names = {t["function"]["name"] for t in tools}
        assert "plugin_a_tool_a" in names
        assert "plugin_b_tool_b" in names
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_refresh_applies_namespacing(self, make_registry):
        """Tool 'get_info' from plugin 'system_info' → 'system_info_get_info'."""
        plugin = MockPlugin(tools=[_make_tool("get_info")], name="system_info")
        registry = make_registry({"system_info": plugin})
        await registry.refresh()

        tools = registry.get_all_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "system_info_get_info"

    @pytest.mark.asyncio
    async def test_refresh_empty_plugins(self, make_registry):
        """No plugins → empty registry."""
        registry = make_registry({})
        await registry.refresh()
        assert registry.get_all_tools() == []

    @pytest.mark.asyncio
    async def test_refresh_plugin_with_no_tools(self, make_registry):
        """Plugin that returns an empty tool list → no tools registered."""
        plugin = MockPlugin(tools=[], name="empty_plugin")
        registry = make_registry({"empty_plugin": plugin})
        await registry.refresh()
        assert registry.get_all_tools() == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:

    @pytest.mark.asyncio
    async def test_invalid_tool_name_skipped(self, make_registry):
        """Tool whose name contains spaces / special chars is skipped (no crash)."""
        fake = FakeToolDefinition(name="bad name!")
        plugin = MockPlugin(tools=[fake], name="test_plugin")
        registry = make_registry({"test_plugin": plugin})
        await registry.refresh()
        assert registry.get_all_tools() == []

    @pytest.mark.asyncio
    async def test_description_too_long_rejected(self, make_registry):
        """Tool with description > 1024 chars is skipped."""
        fake = FakeToolDefinition(name="good_name", description="x" * 1025)
        plugin = MockPlugin(tools=[fake], name="test_plugin")
        registry = make_registry({"test_plugin": plugin})
        await registry.refresh()
        assert registry.get_all_tools() == []

    @pytest.mark.asyncio
    async def test_description_warning_over_512(self, make_registry):
        """Tool with 600-char description is still registered (just warning)."""
        tool = _make_tool("warn_tool", description="x" * 600)
        plugin = MockPlugin(tools=[tool], name="test_plugin")
        registry = make_registry({"test_plugin": plugin})
        await registry.refresh()

        tools = registry.get_all_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "test_plugin_warn_tool"

    @pytest.mark.asyncio
    async def test_invalid_parameters_fallback(self, make_registry):
        """Tool with a non-JSON-Schema parameters dict gets a fallback schema."""
        tool = ToolDefinition(
            name="param_tool",
            description="A tool",
            parameters={"invalid": True},  # missing "type" key
        )
        plugin = MockPlugin(tools=[tool], name="test_plugin")
        registry = make_registry({"test_plugin": plugin})
        await registry.refresh()

        tools = registry.get_all_tools()
        assert len(tools) == 1
        params = tools[0]["function"]["parameters"]
        assert params.get("type") == "object"
        assert "properties" in params


# ---------------------------------------------------------------------------
# Collision Detection
# ---------------------------------------------------------------------------


class TestCollisionDetection:

    @pytest.mark.asyncio
    async def test_collision_raises_error(self, event_bus):
        """Single plugin registering two tools with the same name → collision."""
        # Both tools have name "action" under the same plugin key "alpha"
        # → both produce namespaced name "alpha_action" → collision
        p1 = MockPlugin(
            tools=[_make_tool("action"), _make_tool("action")],
            name="alpha",
        )
        pm = MockPluginManager({"alpha": p1})
        reg = ToolRegistry(pm, event_bus)

        with pytest.raises((ValueError, RuntimeError)):
            await reg.refresh()


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class TestLookup:

    @pytest.mark.asyncio
    async def test_get_all_tools_openai_format(self, make_registry):
        """Each returned tool dict matches the OpenAI function-calling shape."""
        tool = _make_tool("info", description="Gets info", parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        })
        plugin = MockPlugin(tools=[tool], name="system_info")
        registry = make_registry({"system_info": plugin})
        await registry.refresh()

        tools = registry.get_all_tools()
        assert len(tools) == 1
        t = tools[0]
        assert t["type"] == "function"
        assert "function" in t
        fn = t["function"]
        assert fn["name"] == "system_info_info"
        assert fn["description"] == "Gets info"
        assert fn["parameters"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_get_tool_plugin_returns_correct_plugin(self, make_registry):
        """get_tool_plugin returns the owning plugin's name."""
        plugin = MockPlugin(tools=[_make_tool("get_info")], name="system_info")
        registry = make_registry({"system_info": plugin})
        await registry.refresh()

        assert registry.get_tool_plugin("system_info_get_info") == "system_info"

    @pytest.mark.asyncio
    async def test_get_tool_plugin_unknown_returns_none(self, make_registry):
        """get_tool_plugin on an unregistered tool returns None."""
        registry = make_registry({})
        await registry.refresh()
        assert registry.get_tool_plugin("nonexistent_tool") is None


# ---------------------------------------------------------------------------
# Dynamic Availability
# ---------------------------------------------------------------------------


class TestDynamicAvailability:

    @pytest.mark.asyncio
    async def test_available_tools_excludes_error_plugins(self, make_registry):
        """Plugin in ERROR → its tools excluded from get_available_tools()."""
        plugin = MockPlugin(
            tools=[_make_tool("action")],
            name="broken",
            status=ConnectionStatus.ERROR,
        )
        registry = make_registry({"broken": plugin})
        await registry.refresh()

        assert len(registry.get_all_tools()) == 1  # registered
        available = await registry.get_available_tools()
        assert len(available) == 0  # but not available

    @pytest.mark.asyncio
    async def test_available_tools_includes_connected(self, make_registry):
        """Plugin CONNECTED → its tools are available."""
        plugin = MockPlugin(
            tools=[_make_tool("action")],
            name="healthy",
            status=ConnectionStatus.CONNECTED,
        )
        registry = make_registry({"healthy": plugin})
        await registry.refresh()

        available = await registry.get_available_tools()
        assert len(available) == 1

    @pytest.mark.asyncio
    async def test_available_tools_includes_unknown(self, make_registry):
        """Plugin UNKNOWN → its tools are still available."""
        plugin = MockPlugin(
            tools=[_make_tool("action")],
            name="new_plugin",
            status=ConnectionStatus.UNKNOWN,
        )
        registry = make_registry({"new_plugin": plugin})
        await registry.refresh()

        available = await registry.get_available_tools()
        assert len(available) == 1


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestExecution:

    @pytest.mark.asyncio
    async def test_execute_tool_success(self, make_registry, ctx):
        """Happy path: returns ToolResult with success=True."""
        plugin = MockPlugin(tools=[_make_tool("action")], name="plug")
        registry = make_registry({"plug": plugin})
        await registry.refresh()

        result = await registry.execute_tool("plug_action", {}, ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self, make_registry, ctx):
        """Unknown tool → ToolResult with success=False and error_message."""
        registry = make_registry({})
        await registry.refresh()

        result = await registry.execute_tool("nonexistent_tool", {}, ctx)
        assert result.success is False
        assert result.error_message is not None
        assert "nonexistent_tool" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_tool_timeout(self, make_registry, ctx):
        """Plugin that sleeps longer than timeout_ms → ToolResult.error."""

        async def slow_fn(tool_name, args, context):
            await asyncio.sleep(10)
            return ToolResult.ok("done")

        tool = _make_tool("slow", timeout_ms=100)  # 100 ms timeout
        plugin = MockPlugin(tools=[tool], name="plug", execute_fn=slow_fn)
        registry = make_registry({"plug": plugin})
        await registry.refresh()

        result = await registry.execute_tool("plug_slow", {}, ctx)
        assert result.success is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_execute_tool_plugin_raises(self, make_registry, ctx):
        """Plugin.execute_tool raises RuntimeError → caught, ToolResult.error."""

        async def exploding_fn(tool_name, args, context):
            raise RuntimeError("plugin internal failure")

        tool = _make_tool("boom")
        plugin = MockPlugin(tools=[tool], name="plug", execute_fn=exploding_fn)
        registry = make_registry({"plug": plugin})
        await registry.refresh()

        result = await registry.execute_tool("plug_boom", {}, ctx)
        assert result.success is False
        assert result.error_message is not None


# ---------------------------------------------------------------------------
# Result Processing
# ---------------------------------------------------------------------------


class TestResultProcessing:

    @pytest.mark.asyncio
    async def test_result_truncation_long_content(self, make_registry, ctx):
        """Content of 5000 chars → truncated to ≤ MAX_TOOL_RESULT_LENGTH, truncated=True."""
        long_content = "a" * 5000

        async def long_fn(tool_name, args, context):
            return ToolResult.ok(long_content)

        tool = _make_tool("big")
        plugin = MockPlugin(tools=[tool], name="plug", execute_fn=long_fn)
        registry = make_registry({"plug": plugin})
        await registry.refresh()

        result = await registry.execute_tool("plug_big", {}, ctx)
        assert result.success is True
        assert result.truncated is True
        assert len(result.content) <= MAX_TOOL_RESULT_LENGTH

    @pytest.mark.asyncio
    async def test_result_no_truncation_short_content(self, make_registry, ctx):
        """Content of 100 chars → unchanged, truncated=False."""
        short_content = "b" * 100

        async def short_fn(tool_name, args, context):
            return ToolResult.ok(short_content)

        tool = _make_tool("small")
        plugin = MockPlugin(tools=[tool], name="plug", execute_fn=short_fn)
        registry = make_registry({"plug": plugin})
        await registry.refresh()

        result = await registry.execute_tool("plug_small", {}, ctx)
        assert result.success is True
        assert result.truncated is False
        assert result.content == short_content

    @pytest.mark.asyncio
    async def test_result_sanitization_strips_windows_paths(
        self, make_registry, ctx,
    ):
        """Windows-style paths like 'C:\\Users\\john\\...' are redacted."""
        raw = r"Error in C:\Users\john\project\file.py at line 42"

        async def path_fn(tool_name, args, context):
            return ToolResult.ok(raw)

        tool = _make_tool("winpath")
        plugin = MockPlugin(tools=[tool], name="plug", execute_fn=path_fn)
        registry = make_registry({"plug": plugin})
        await registry.refresh()

        result = await registry.execute_tool("plug_winpath", {}, ctx)
        assert result.success is True
        assert r"C:\Users\john" not in (result.content or "")

    @pytest.mark.asyncio
    async def test_result_sanitization_strips_unix_paths(
        self, make_registry, ctx,
    ):
        """Unix-style paths like '/home/john/project/file.py' are redacted."""
        raw = "Error in /home/john/project/file.py at line 42"

        async def path_fn(tool_name, args, context):
            return ToolResult.ok(raw)

        tool = _make_tool("unixpath")
        plugin = MockPlugin(tools=[tool], name="plug", execute_fn=path_fn)
        registry = make_registry({"plug": plugin})
        await registry.refresh()

        result = await registry.execute_tool("plug_unixpath", {}, ctx)
        assert result.success is True
        assert "/home/john" not in (result.content or "")

    @pytest.mark.asyncio
    async def test_result_sanitization_strips_tracebacks(
        self, make_registry, ctx,
    ):
        """Python tracebacks are cleaned from the result content."""
        raw = (
            "Traceback (most recent call last):\n"
            '  File "/app/plugin.py", line 10, in run\n'
            "    do_work()\n"
            "RuntimeError: something broke\n"
            "Useful output after traceback"
        )

        async def tb_fn(tool_name, args, context):
            return ToolResult.ok(raw)

        tool = _make_tool("tbtest")
        plugin = MockPlugin(tools=[tool], name="plug", execute_fn=tb_fn)
        registry = make_registry({"plug": plugin})
        await registry.refresh()

        result = await registry.execute_tool("plug_tbtest", {}, ctx)
        assert result.success is True
        assert "Traceback (most recent call last)" not in (result.content or "")


# ---------------------------------------------------------------------------
# Event Emission
# ---------------------------------------------------------------------------


class TestEventEmission:

    @pytest.mark.asyncio
    async def test_events_emitted_on_success(self, event_bus):
        """TOOL_EXECUTION_START and TOOL_EXECUTION_SUCCEEDED emitted on happy path."""
        events_received: list[str] = []

        async def on_start(**kwargs):
            events_received.append("start")

        async def on_succeeded(**kwargs):
            events_received.append("succeeded")

        event_bus.subscribe(OmniaEvent.TOOL_EXECUTION_START, on_start)
        event_bus.subscribe(OmniaEvent.TOOL_EXECUTION_SUCCEEDED, on_succeeded)

        plugin = MockPlugin(tools=[_make_tool("action")], name="plug")
        pm = MockPluginManager({"plug": plugin})
        registry = ToolRegistry(pm, event_bus)
        await registry.refresh()

        await registry.execute_tool("plug_action", {}, _make_context())

        assert "start" in events_received
        assert "succeeded" in events_received

    @pytest.mark.asyncio
    async def test_events_emitted_on_failure(self, event_bus):
        """TOOL_EXECUTION_START and TOOL_EXECUTION_FAILED emitted on error."""
        events_received: list[str] = []

        async def on_start(**kwargs):
            events_received.append("start")

        async def on_failed(**kwargs):
            events_received.append("failed")

        event_bus.subscribe(OmniaEvent.TOOL_EXECUTION_START, on_start)
        event_bus.subscribe(OmniaEvent.TOOL_EXECUTION_FAILED, on_failed)

        async def broken_fn(tool_name, args, context):
            raise RuntimeError("boom")

        tool = _make_tool("broken")
        plugin = MockPlugin(tools=[tool], name="plug", execute_fn=broken_fn)
        pm = MockPluginManager({"plug": plugin})
        registry = ToolRegistry(pm, event_bus)
        await registry.refresh()

        await registry.execute_tool("plug_broken", {}, _make_context())

        assert "start" in events_received
        assert "failed" in events_received


# ---------------------------------------------------------------------------
# Thread Safety
# ---------------------------------------------------------------------------


class TestThreadSafety:

    @pytest.mark.asyncio
    async def test_concurrent_refresh_safe(self, make_registry):
        """10 concurrent refresh() calls do not corrupt the registry."""
        tools = [_make_tool(f"tool_{i}") for i in range(5)]
        plugin = MockPlugin(tools=tools, name="multi")
        registry = make_registry({"multi": plugin})

        await asyncio.gather(*(registry.refresh() for _ in range(10)))

        result = registry.get_all_tools()
        names = [t["function"]["name"] for t in result]
        # After concurrent refreshes, the registry should still have
        # exactly the 5 tools (no duplicates, no missing entries).
        assert len(names) == 5
        assert len(set(names)) == 5
        for i in range(5):
            assert f"multi_tool_{i}" in names
