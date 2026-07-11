"""Kernel-owned tools (Fase 7, spec §7): registration, availability, dispatch.

``app_command`` is owned by the kernel, not a plugin: the catalog stores it
under the pseudo-owner ``kernel``, the availability probe treats that owner
as always connected, and the executor dispatches to the registered handler.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.config import LLMConfig
from backend.core.event_bus import EventBus
from backend.core.plugin_models import (
    KERNEL_TOOL_OWNER,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.core.tool_registry import ToolRegistry


class _NoPlugins:
    """Plugin-manager stand-in with no plugins loaded."""

    def get_all_plugins(self) -> dict[str, Any]:
        return {}

    def get_plugin(self, name: str) -> Any | None:
        return None


def _make_registry() -> ToolRegistry:
    return ToolRegistry(
        plugin_manager=_NoPlugins(),
        event_bus=EventBus(),
        qdrant_service=None,
        embedding_client=None,
        llm_config=LLMConfig(),
    )


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="s1", conversation_id="c1", execution_id="e1",
    )


def _tool(name: str = "app_command") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Kernel tool under test",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        capabilities=("ui_command",),
        always_offered=True,
    )


@pytest.mark.asyncio
async def test_kernel_tool_is_registered_and_available() -> None:
    registry = _make_registry()

    async def handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok({"echo": args})

    await registry.register_kernel_tool(_tool(), handler)
    assert registry.get_tool_definition("app_command") is not None
    assert registry.get_tool_plugin("app_command") == KERNEL_TOOL_OWNER
    available = await registry.get_available_tools()
    assert any(t["function"]["name"] == "app_command" for t in available)


@pytest.mark.asyncio
async def test_kernel_tool_dispatches_to_handler() -> None:
    registry = _make_registry()
    calls: list[dict[str, Any]] = []

    async def handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        calls.append(args)
        return ToolResult.ok({"ran": args["name"]})

    await registry.register_kernel_tool(_tool(), handler)
    result = await registry.execute_tool("app_command", {"name": "view.switch"}, _ctx())
    assert result.success is True
    assert calls == [{"name": "view.switch"}]


@pytest.mark.asyncio
async def test_kernel_tool_survives_refresh() -> None:
    registry = _make_registry()

    async def handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok(None)

    await registry.register_kernel_tool(_tool(), handler)
    await registry.refresh()
    assert registry.get_tool_definition("app_command") is not None
    assert registry.get_tool_plugin("app_command") == KERNEL_TOOL_OWNER


@pytest.mark.asyncio
async def test_kernel_tool_reregistration_replaces() -> None:
    registry = _make_registry()

    async def handler_a(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok("a")

    async def handler_b(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok("b")

    await registry.register_kernel_tool(_tool(), handler_a)
    await registry.register_kernel_tool(_tool(), handler_b)
    result = await registry.execute_tool("app_command", {"name": "x"}, _ctx())
    assert result.content == "b"
    # No duplicate OpenAI cache entry after re-registration.
    names = [t["function"]["name"] for t in registry.get_all_tools()]
    assert names.count("app_command") == 1


@pytest.mark.asyncio
async def test_kernel_tool_args_are_schema_validated() -> None:
    registry = _make_registry()

    async def handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok(None)

    await registry.register_kernel_tool(_tool(), handler)
    result = await registry.execute_tool("app_command", {}, _ctx())
    assert result.success is False
    assert "validation failed" in (result.error_message or "")


class _ColliderPlugin:
    """Stub plugin whose namespaced tool name collides with a kernel tool.

    Plugin ``app`` exposing tool ``command`` namespaces to ``app_command``.
    """

    def get_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(name="command", description="Colliding plugin tool"),
        ]


class _ColliderPluginManager:
    def get_all_plugins(self) -> dict[str, Any]:
        return {"app": _ColliderPlugin()}

    def get_plugin(self, name: str) -> Any | None:
        return _ColliderPlugin() if name == "app" else None


@pytest.mark.asyncio
async def test_kernel_tool_wins_plugin_collision_on_refresh() -> None:
    """A plugin landing on a kernel tool's name is skipped (kernel wins)."""
    registry = ToolRegistry(
        plugin_manager=_ColliderPluginManager(),
        event_bus=EventBus(),
        qdrant_service=None,
        embedding_client=None,
        llm_config=LLMConfig(),
    )

    async def handler(args: dict[str, Any], context: ExecutionContext) -> ToolResult:
        return ToolResult.ok("kernel")

    await registry.register_kernel_tool(_tool(), handler)
    await registry.refresh()
    assert registry.get_tool_plugin("app_command") == KERNEL_TOOL_OWNER
    result = await registry.execute_tool("app_command", {"name": "x"}, _ctx())
    assert result.content == "kernel"
