"""Command Bridge service (Fase 7, spec §7): manifest, anti-escalation, RPC."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.api.ws_schema import validate_events_server
from backend.core.plugin_models import ExecutionContext
from backend.services.command_bridge import (
    CommandBridgeService,
    CommandSpec,
    build_app_command_definition,
)


class FakeWSManager:
    """Records broadcast frames; connection_count is settable."""

    def __init__(self, connections: int = 1) -> None:
        self.sent: list[dict[str, Any]] = []
        self.connections = connections

    @property
    def connection_count(self) -> int:
        return self.connections

    async def broadcast(self, event: dict[str, Any]) -> None:
        self.sent.append(event)


class FakeToolRegistry:
    """Records kernel-tool registrations."""

    def __init__(self) -> None:
        self.registered: list[Any] = []

    async def register_kernel_tool(self, tool_def: Any, handler: Any) -> None:
        self.registered.append(tool_def)


def _bridge(
    ws: FakeWSManager | None = None,
    registry: FakeToolRegistry | None = None,
    *,
    enabled: bool = True,
    timeout: float = 0.2,
    disabled: list[str] | None = None,
) -> CommandBridgeService:
    return CommandBridgeService(
        ws_manager=ws,
        tool_registry=registry,
        enabled=enabled,
        rpc_timeout_s=timeout,
        disabled_commands=disabled or [],
    )


def _entry(name: str, capability: str = "navigation") -> dict[str, Any]:
    return {
        "name": name,
        "description": f"desc {name}",
        "capability": capability,
        "args_schema": {"type": "object", "properties": {}},
    }


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="s1", conversation_id="c1", execution_id="e1",
    )


@pytest.mark.asyncio
async def test_manifest_rejects_guardrail_domains() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry())
    await bridge.set_manifest([
        _entry("view.switch"),
        _entry("permission.set_mode", "mutate"),
        _entry("scope.set_folder", "mutate"),
        _entry("guardrails.disable", "destructive"),
    ])
    assert bridge.capability_of("view.switch") == "navigation"
    assert bridge.capability_of("permission.set_mode") is None
    assert bridge.capability_of("scope.set_folder") is None
    assert bridge.capability_of("guardrails.disable") is None


@pytest.mark.asyncio
async def test_manifest_rejects_malformed_and_disguised_names() -> None:
    """Name grammar + NFKC normalization close the unicode/case trick space."""
    bridge = _bridge(FakeWSManager(), FakeToolRegistry())
    await bridge.set_manifest([
        _entry("Permission.set", "mutate"),  # uppercase → invalid grammar
        _entry(" permission.set", "mutate"),  # strips to a guardrail domain
        _entry("ｐermission.set", "mutate"),  # fullwidth p, NFKC-folds to guardrail
        _entry("view", "navigation"),  # no dot → invalid grammar
        _entry("", "navigation"),  # empty name
    ])
    assert bridge.capability_of("Permission.set") is None
    assert bridge.capability_of("permission.set") is None
    assert bridge.capability_of("view") is None
    assert bridge.capability_of("") is None


@pytest.mark.asyncio
async def test_manifest_drops_disabled_commands_and_reregisters_tool() -> None:
    registry = FakeToolRegistry()
    bridge = _bridge(FakeWSManager(), registry, disabled=["conversation.new"])
    await bridge.set_manifest([_entry("view.switch"), _entry("conversation.new", "mutate")])
    assert bridge.capability_of("conversation.new") is None
    assert len(registry.registered) == 1
    params = registry.registered[0].parameters
    assert params["properties"]["name"]["enum"] == ["view.switch"]


@pytest.mark.asyncio
async def test_call_unknown_command_is_clean_error() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry())
    await bridge.set_manifest([_entry("view.switch")])
    outcome = await bridge.call_command("nope", {}, conversation_id="c1")
    assert outcome["ok"] is False
    assert "Unknown command" in outcome["error"]


@pytest.mark.asyncio
async def test_call_without_ui_is_clean_error() -> None:
    ws = FakeWSManager(connections=0)
    bridge = _bridge(ws, FakeToolRegistry())
    await bridge.set_manifest([_entry("view.switch")])
    outcome = await bridge.call_command("view.switch", {}, conversation_id="c1")
    assert outcome["ok"] is False
    assert "UI not available" in outcome["error"]
    assert ws.sent == []


@pytest.mark.asyncio
async def test_call_roundtrip_resolves_on_command_result() -> None:
    ws = FakeWSManager()
    bridge = _bridge(ws, FakeToolRegistry())
    await bridge.set_manifest([_entry("view.switch")])

    async def respond() -> None:
        while not ws.sent:
            await asyncio.sleep(0.01)
        frame = ws.sent[0]
        assert frame["type"] == "command.request"
        assert frame["origin"] == "agent"
        assert frame["name"] == "view.switch"
        # The bridge builds the frame as a raw dict (layering): pin it to the
        # ws_schema contract so drift fails HERE, not as a prod warning.
        validate_events_server(frame)
        bridge.resolve(frame["correlation_id"], {"ok": True, "result": {"view": "board"}})

    task = asyncio.create_task(respond())
    outcome = await bridge.call_command(
        "view.switch", {"view": "board"}, conversation_id="c1",
    )
    await task
    assert outcome == {"ok": True, "result": {"view": "board"}}
    assert bridge._pending == {}


@pytest.mark.asyncio
async def test_roundtrip_error_payload_maps_to_clean_error() -> None:
    ws = FakeWSManager()
    bridge = _bridge(ws, FakeToolRegistry())
    await bridge.set_manifest([_entry("view.switch")])

    async def respond() -> None:
        while not ws.sent:
            await asyncio.sleep(0.01)
        bridge.resolve(ws.sent[0]["correlation_id"], {"ok": False, "error": "boom"})

    task = asyncio.create_task(respond())
    outcome = await bridge.call_command("view.switch", {}, conversation_id="c1")
    await task
    assert outcome == {"ok": False, "error": "boom"}
    assert bridge._pending == {}


@pytest.mark.asyncio
async def test_call_times_out_cleanly() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry(), timeout=0.05)
    await bridge.set_manifest([_entry("view.switch")])
    outcome = await bridge.call_command("view.switch", {}, conversation_id="c1")
    assert outcome["ok"] is False
    assert "did not respond" in outcome["error"]
    assert bridge._pending == {}


@pytest.mark.asyncio
async def test_disabled_bridge_refuses() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry(), enabled=False)
    await bridge.set_manifest([_entry("view.switch")])
    outcome = await bridge.call_command("view.switch", {}, conversation_id="c1")
    assert outcome["ok"] is False
    assert "disabled" in outcome["error"]


@pytest.mark.asyncio
async def test_disabled_bridge_ignores_manifest_and_never_registers_tool() -> None:
    """The master switch removes the whole surface: no ingestion, no tool.

    Without this, every FE connect would re-register an always-offered
    app_command whose every call errors (final phase review, Important 1).
    """
    registry = FakeToolRegistry()
    bridge = _bridge(FakeWSManager(), registry, enabled=False)
    await bridge.set_manifest([_entry("view.switch")])
    assert registry.registered == []
    assert bridge.capability_of("view.switch") is None


@pytest.mark.asyncio
async def test_execute_app_command_maps_to_tool_result() -> None:
    ws = FakeWSManager()
    bridge = _bridge(ws, FakeToolRegistry())
    await bridge.set_manifest([_entry("view.switch")])

    async def respond() -> None:
        while not ws.sent:
            await asyncio.sleep(0.01)
        bridge.resolve(ws.sent[0]["correlation_id"], {"ok": True, "result": None})

    task = asyncio.create_task(respond())
    result = await bridge.execute_app_command(
        {"name": "view.switch", "args": {"view": "board"}}, _ctx(),
    )
    await task
    assert result.success is True

    failure = await bridge.execute_app_command({"name": "nope"}, _ctx())
    assert failure.success is False
    assert "Unknown command" in (failure.error_message or "")


def test_resolve_unknown_correlation_is_noop() -> None:
    bridge = _bridge(FakeWSManager(), FakeToolRegistry())
    bridge.resolve("ghost", {"ok": True})  # must not raise


def test_build_app_command_definition_bakes_manifest() -> None:
    specs = [
        CommandSpec(
            name="view.switch", description="Switch view",
            capability="navigation", args_schema={"type": "object"},
        ),
    ]
    tool = build_app_command_definition(specs)
    assert tool.name == "app_command"
    assert tool.capabilities == ("ui_command",)
    assert tool.always_offered is True
    assert tool.parameters["properties"]["name"]["enum"] == ["view.switch"]
    assert "view.switch" in (tool.usage_guidance or "")

    empty = build_app_command_definition([])
    assert "enum" not in empty.parameters["properties"]["name"]


@pytest.mark.asyncio
async def test_app_command_through_real_executor_enforces_manifest_enum() -> None:
    """Integration seam: real ToolRegistry executor × real bridge (Q7a).

    The manifest-baked enum must reject an off-manifest name inside the
    REAL executor's JSON-Schema validation, and the happy path must flow
    executor → kernel handler → RPC roundtrip → ToolResult.
    """
    from backend.core.config import LLMConfig
    from backend.core.event_bus import EventBus
    from backend.core.tool_registry import ToolRegistry

    class _NoPlugins:
        def get_all_plugins(self) -> dict[str, Any]:
            return {}

        def get_plugin(self, name: str) -> Any | None:
            return None

    registry = ToolRegistry(
        plugin_manager=_NoPlugins(),
        event_bus=EventBus(),
        qdrant_service=None,
        embedding_client=None,
        llm_config=LLMConfig(),
    )
    ws = FakeWSManager()
    bridge = CommandBridgeService(
        ws_manager=ws,
        tool_registry=registry,
        enabled=True,
        rpc_timeout_s=0.2,
        disabled_commands=[],
    )
    await bridge.set_manifest([_entry("view.switch")])

    off_manifest = await registry.execute_tool(
        "app_command", {"name": "not.in.manifest"}, _ctx(),
    )
    assert off_manifest.success is False
    assert "validation failed" in (off_manifest.error_message or "")

    async def respond() -> None:
        while not ws.sent:
            await asyncio.sleep(0.01)
        bridge.resolve(ws.sent[0]["correlation_id"], {"ok": True, "result": None})

    task = asyncio.create_task(respond())
    happy = await registry.execute_tool(
        "app_command", {"name": "view.switch", "args": {}}, _ctx(),
    )
    await task
    assert happy.success is True
