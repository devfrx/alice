"""Tests for McpClientPlugin — MCP tool aggregation and dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import McpConfig, McpServerConfig, OmniaConfig
from backend.core.context import AppContext
from backend.core.event_bus import EventBus, OmniaEvent
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.mcp_client.plugin import McpClientPlugin


def _make_context(
    servers: list[McpServerConfig] | None = None,
) -> AppContext:
    """Create a minimal AppContext with MCP config."""
    config = MagicMock(spec=OmniaConfig)
    config.mcp = McpConfig(servers=servers or [])
    ctx = AppContext(config=config, event_bus=EventBus())
    return ctx


def _make_server_config(
    name: str = "test",
    transport: str = "stdio",
    enabled: bool = True,
) -> McpServerConfig:
    return McpServerConfig(
        name=name,
        transport=transport,
        command=["echo", "test"] if transport == "stdio" else None,
        url="http://localhost:3000/sse" if transport == "sse" else None,
        enabled=enabled,
    )


def _make_mock_session(
    server_name: str = "test",
    status: ConnectionStatus = ConnectionStatus.CONNECTED,
    tools: list[ToolDefinition] | None = None,
) -> MagicMock:
    """Create a mock McpSession."""
    session = MagicMock()
    session.server_name = server_name
    session.status = status
    session.get_tools.return_value = tools or [
        ToolDefinition(
            name="read_file",
            description="Read a file",
            parameters={"type": "object", "properties": {}},
        ),
    ]
    session.start = AsyncMock()
    session.stop = AsyncMock()
    session.call_tool = AsyncMock(return_value="file content")
    return session


def _make_exec_context() -> ExecutionContext:
    return ExecutionContext(
        session_id="test-session",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


class TestMcpClientPluginInitialize:
    """Tests for McpClientPlugin.initialize()."""

    @pytest.mark.asyncio
    async def test_initialize_starts_all_enabled(self) -> None:
        servers = [
            _make_server_config("server_a"),
            _make_server_config("server_b"),
            _make_server_config("server_c", enabled=False),
        ]
        ctx = _make_context(servers)
        plugin = McpClientPlugin()

        with patch(
            "backend.plugins.mcp_client.plugin.McpSession",
        ) as MockSession:
            mock_instances = [
                _make_mock_session("server_a"),
                _make_mock_session("server_b"),
            ]
            MockSession.side_effect = mock_instances

            await plugin.initialize(ctx)

        assert len(plugin._sessions) == 2
        assert "server_a" in plugin._sessions
        assert "server_b" in plugin._sessions
        assert "server_c" not in plugin._sessions

    @pytest.mark.asyncio
    async def test_initialize_isolates_session_failure(self) -> None:
        servers = [
            _make_server_config("good_server"),
            _make_server_config("bad_server"),
        ]
        ctx = _make_context(servers)
        plugin = McpClientPlugin()

        good_session = _make_mock_session("good_server")
        bad_session = _make_mock_session("bad_server")
        bad_session.start = AsyncMock(
            side_effect=ConnectionError("Failed"),
        )

        with patch(
            "backend.plugins.mcp_client.plugin.McpSession",
        ) as MockSession:
            MockSession.side_effect = [good_session, bad_session]
            await plugin.initialize(ctx)

        assert len(plugin._sessions) == 1
        assert "good_server" in plugin._sessions
        assert "bad_server" not in plugin._sessions

    @pytest.mark.asyncio
    async def test_initialize_emits_events(self) -> None:
        servers = [
            _make_server_config("ok_server"),
            _make_server_config("fail_server"),
        ]
        ctx = _make_context(servers)
        plugin = McpClientPlugin()

        events_received: list[tuple[str, dict]] = []

        original_emit = ctx.event_bus.emit

        async def patched_emit(event_name, **kwargs):
            events_received.append((str(event_name), kwargs))
            await original_emit(event_name, **kwargs)

        ctx.event_bus.emit = patched_emit

        ok_session = _make_mock_session("ok_server")
        fail_session = _make_mock_session("fail_server")
        fail_session.start = AsyncMock(
            side_effect=RuntimeError("Connection refused"),
        )

        with patch(
            "backend.plugins.mcp_client.plugin.McpSession",
        ) as MockSession:
            MockSession.side_effect = [ok_session, fail_session]
            await plugin.initialize(ctx)

        event_types = [e[0] for e in events_received]
        assert OmniaEvent.MCP_SERVER_CONNECTED in event_types
        assert OmniaEvent.MCP_SERVER_DISCONNECTED in event_types


class TestMcpClientPluginGetTools:
    """Tests for McpClientPlugin.get_tools()."""

    def test_get_tools_aggregates_from_connected(self) -> None:
        plugin = McpClientPlugin()
        plugin._sessions = {
            "fs": _make_mock_session(
                "fs",
                tools=[
                    ToolDefinition(
                        name="read",
                        description="Read",
                        parameters={},
                    ),
                    ToolDefinition(
                        name="write",
                        description="Write",
                        parameters={},
                    ),
                ],
            ),
            "git": _make_mock_session(
                "git",
                tools=[
                    ToolDefinition(
                        name="log",
                        description="Log",
                        parameters={},
                    ),
                ],
            ),
        }

        tools = plugin.get_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert names == {"mcp_fs_read", "mcp_fs_write", "mcp_git_log"}

    def test_get_tools_skips_disconnected(self) -> None:
        plugin = McpClientPlugin()
        plugin._sessions = {
            "online": _make_mock_session(
                "online", status=ConnectionStatus.CONNECTED,
            ),
            "offline": _make_mock_session(
                "offline", status=ConnectionStatus.ERROR,
            ),
        }

        tools = plugin.get_tools()
        names = {t.name for t in tools}
        assert all(n.startswith("mcp_online_") for n in names)
        assert not any(n.startswith("mcp_offline_") for n in names)


class TestMcpClientPluginExecuteTool:
    """Tests for McpClientPlugin.execute_tool()."""

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_correct_session(self) -> None:
        plugin = McpClientPlugin()
        fs_session = _make_mock_session("filesystem")
        fs_session.call_tool = AsyncMock(
            return_value="content of file",
        )
        plugin._sessions = {"filesystem": fs_session}

        result = await plugin.execute_tool(
            "mcp_filesystem_read_file",
            {"path": "/test.txt"},
            _make_exec_context(),
        )

        assert result.success is True
        assert result.content == "content of file"
        fs_session.call_tool.assert_called_once_with(
            "read_file", {"path": "/test.txt"},
        )

    @pytest.mark.asyncio
    async def test_execute_unknown_returns_failure(self) -> None:
        plugin = McpClientPlugin()
        plugin._sessions = {}

        result = await plugin.execute_tool(
            "mcp_unknown_tool", {}, _make_exec_context(),
        )

        assert result.success is False
        assert "not found" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_execute_session_error(self) -> None:
        plugin = McpClientPlugin()
        session = _make_mock_session("test")
        session.call_tool = AsyncMock(
            side_effect=RuntimeError("Connection lost"),
        )
        plugin._sessions = {"test": session}

        result = await plugin.execute_tool(
            "mcp_test_some_tool", {}, _make_exec_context(),
        )

        assert result.success is False
        assert "failed" in (result.error_message or "").lower()


class TestMcpClientPluginConnectionStatus:
    """Tests for McpClientPlugin.get_connection_status()."""

    @pytest.mark.asyncio
    async def test_all_connected(self) -> None:
        plugin = McpClientPlugin()
        plugin._sessions = {
            "a": _make_mock_session(
                "a", status=ConnectionStatus.CONNECTED,
            ),
            "b": _make_mock_session(
                "b", status=ConnectionStatus.CONNECTED,
            ),
        }
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_partial_connected(self) -> None:
        plugin = McpClientPlugin()
        plugin._sessions = {
            "a": _make_mock_session(
                "a", status=ConnectionStatus.CONNECTED,
            ),
            "b": _make_mock_session(
                "b", status=ConnectionStatus.ERROR,
            ),
        }
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_none_connected(self) -> None:
        plugin = McpClientPlugin()
        plugin._sessions = {
            "a": _make_mock_session(
                "a", status=ConnectionStatus.ERROR,
            ),
        }
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.ERROR

    @pytest.mark.asyncio
    async def test_no_servers(self) -> None:
        plugin = McpClientPlugin()
        plugin._sessions = {}
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.CONNECTED


class TestMcpClientPluginCleanup:
    """Tests for McpClientPlugin.cleanup()."""

    @pytest.mark.asyncio
    async def test_cleanup_stops_all_sessions(self) -> None:
        plugin = McpClientPlugin()
        session_a = _make_mock_session("a")
        session_b = _make_mock_session("b")
        plugin._sessions = {"a": session_a, "b": session_b}

        # Need to set _initialized for cleanup
        plugin._initialized = True

        await plugin.cleanup()

        session_a.stop.assert_called_once()
        session_b.stop.assert_called_once()
        assert len(plugin._sessions) == 0
