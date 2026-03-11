"""Tests for McpSession — single MCP server connection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import McpServerConfig
from backend.core.plugin_models import ConnectionStatus
from backend.services.mcp_session import McpSession


def _make_config(
    name: str = "test_server",
    transport: str = "stdio",
    command: list[str] | None = None,
    url: str | None = None,
) -> McpServerConfig:
    """Create a test McpServerConfig."""
    if transport == "stdio" and command is None:
        command = ["echo", "hello"]
    if transport == "sse" and url is None:
        url = "http://localhost:3000/sse"
    return McpServerConfig(
        name=name, transport=transport, command=command, url=url,
    )


def _mock_tool(
    name: str = "read_file", description: str = "Read a file",
) -> MagicMock:
    """Create a mock MCP tool object."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
    }
    return tool


def _mock_tools_response(
    tools: list[MagicMock] | None = None,
) -> MagicMock:
    """Create a mock tools/list response."""
    resp = MagicMock()
    resp.tools = tools or [_mock_tool()]
    return resp


def _mock_call_result(text: str = "file content") -> MagicMock:
    """Create a mock tools/call result."""
    result = MagicMock()
    block = MagicMock()
    block.text = text
    result.content = [block]
    return result


class TestMcpSessionInit:
    """Tests for McpSession initialization."""

    def test_initial_state(self) -> None:
        config = _make_config()
        session = McpSession(config)
        assert session.status == ConnectionStatus.DISCONNECTED
        assert session.get_tools() == []
        assert session.server_name == "test_server"


class TestMcpSessionStart:
    """Tests for McpSession.start()."""

    @pytest.mark.asyncio
    async def test_start_stdio_success(self) -> None:
        config = _make_config(
            transport="stdio", command=["echo", "test"],
        )
        session = McpSession(config)

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=_mock_tools_response(
                [_mock_tool("read_file"), _mock_tool("write_file")],
            ),
        )

        mock_read = MagicMock()
        mock_write = MagicMock()

        with (
            patch("mcp.client.stdio.stdio_client") as mock_stdio,
            patch("mcp.ClientSession") as mock_cs_class,
        ):
            # stdio_client returns async context manager
            stdio_cm = AsyncMock()
            stdio_cm.__aenter__ = AsyncMock(
                return_value=(mock_read, mock_write),
            )
            stdio_cm.__aexit__ = AsyncMock(return_value=False)
            mock_stdio.return_value = stdio_cm

            # ClientSession returns async context manager
            session_cm = AsyncMock()
            session_cm.__aenter__ = AsyncMock(
                return_value=mock_session,
            )
            session_cm.__aexit__ = AsyncMock(return_value=False)
            mock_cs_class.return_value = session_cm

            await session.start()

        assert session.status == ConnectionStatus.CONNECTED
        tools = session.get_tools()
        assert len(tools) == 2
        assert tools[0].name == "read_file"
        assert tools[1].name == "write_file"

    @pytest.mark.asyncio
    async def test_start_sse_success(self) -> None:
        config = _make_config(
            transport="sse", url="http://localhost:3000/sse",
        )
        session = McpSession(config)

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=_mock_tools_response([_mock_tool("search")]),
        )

        with (
            patch("mcp.client.sse.sse_client") as mock_sse,
            patch("mcp.ClientSession") as mock_cs_class,
        ):
            sse_cm = AsyncMock()
            sse_cm.__aenter__ = AsyncMock(
                return_value=(MagicMock(), MagicMock()),
            )
            sse_cm.__aexit__ = AsyncMock(return_value=False)
            mock_sse.return_value = sse_cm

            session_cm = AsyncMock()
            session_cm.__aenter__ = AsyncMock(
                return_value=mock_session,
            )
            session_cm.__aexit__ = AsyncMock(return_value=False)
            mock_cs_class.return_value = session_cm

            await session.start()

        assert session.status == ConnectionStatus.CONNECTED
        assert len(session.get_tools()) == 1

    @pytest.mark.asyncio
    async def test_start_failure_sets_error_status(self) -> None:
        config = _make_config(transport="stdio")
        session = McpSession(config)

        with patch("mcp.client.stdio.stdio_client") as mock_stdio:
            mock_stdio.side_effect = ConnectionError("Server not found")

            with pytest.raises(ConnectionError):
                await session.start()

        assert session.status == ConnectionStatus.ERROR
        assert session.get_tools() == []

    @pytest.mark.asyncio
    async def test_start_failure_closes_exit_stack(self) -> None:
        config = _make_config(transport="stdio")
        session = McpSession(config)

        with (
            patch("mcp.client.stdio.stdio_client") as mock_stdio,
            patch("mcp.ClientSession") as mock_cs_class,
        ):
            stdio_cm = AsyncMock()
            stdio_cm.__aenter__ = AsyncMock(
                return_value=(MagicMock(), MagicMock()),
            )
            stdio_cm.__aexit__ = AsyncMock(return_value=False)
            mock_stdio.return_value = stdio_cm

            session_cm = AsyncMock()
            mock_sess = AsyncMock()
            mock_sess.initialize = AsyncMock(
                side_effect=RuntimeError("Init failed"),
            )
            session_cm.__aenter__ = AsyncMock(return_value=mock_sess)
            session_cm.__aexit__ = AsyncMock(return_value=False)
            mock_cs_class.return_value = session_cm

            with pytest.raises(RuntimeError, match="Init failed"):
                await session.start()

        # Exit stack was cleaned up (session is None)
        assert session._exit_stack is None
        assert session.status == ConnectionStatus.ERROR


class TestMcpSessionCallTool:
    """Tests for McpSession.call_tool()."""

    @pytest.mark.asyncio
    async def test_call_tool_success(self) -> None:
        config = _make_config()
        session = McpSession(config)

        # Simulate a connected session
        mock_sess = AsyncMock()
        mock_sess.call_tool = AsyncMock(
            return_value=_mock_call_result("hello world"),
        )
        session._session = mock_sess
        session._status = ConnectionStatus.CONNECTED

        result = await session.call_tool(
            "read_file", {"path": "/tmp/test"},
        )
        assert result == "hello world"
        mock_sess.call_tool.assert_called_once_with(
            "read_file", {"path": "/tmp/test"},
        )

    @pytest.mark.asyncio
    async def test_call_tool_disconnected_raises(self) -> None:
        config = _make_config()
        session = McpSession(config)

        with pytest.raises(RuntimeError, match="not connected"):
            await session.call_tool("read_file", {})


class TestMcpSessionStop:
    """Tests for McpSession.stop()."""

    @pytest.mark.asyncio
    async def test_stop_resets_state(self) -> None:
        config = _make_config()
        session = McpSession(config)

        # Simulate connected state
        session._status = ConnectionStatus.CONNECTED
        session._cached_tools = [MagicMock(name="tool1")]
        mock_stack = AsyncMock()
        session._exit_stack = mock_stack

        await session.stop()

        assert session.status == ConnectionStatus.DISCONNECTED
        assert session.get_tools() == []
        assert session._session is None
        mock_stack.aclose.assert_called_once()
