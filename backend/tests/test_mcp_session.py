"""Tests for McpSession — single MCP server connection."""

from __future__ import annotations

from pathlib import Path
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
            patch("shutil.which", return_value="/usr/bin/echo"),
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

        with (
            patch("shutil.which", return_value="/usr/bin/echo"),
            patch("mcp.client.stdio.stdio_client") as mock_stdio,
        ):
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
            patch("shutil.which", return_value="/usr/bin/echo"),
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

        # Session task completed with error; exit stack was cleaned up
        # internally by the task's AsyncExitStack context manager.
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


class TestMcpSessionRoots:
    """Tests for the workspace-scope → MCP roots bridge."""

    def test_static_root_dirs_extracts_existing_dirs(
        self, tmp_path: Path,
    ) -> None:
        """Only command tokens that resolve to existing directories count."""
        real_dir = tmp_path / "allowed"
        real_dir.mkdir()
        a_file = tmp_path / "file.txt"
        a_file.write_text("x")
        missing = tmp_path / "missing"

        config = _make_config(
            command=[
                "npx",
                "-y",
                "@modelcontextprotocol/server-filesystem",
                str(real_dir),
                str(a_file),
                str(missing),
            ],
        )
        session = McpSession(config)

        assert session._static_root_dirs() == [real_dir.resolve()]

    def test_static_root_dirs_expands_home(self) -> None:
        """``~`` (the default filesystem-server CLI dir) expands to home."""
        config = _make_config(command=["npx", "~"])
        session = McpSession(config)

        assert session._static_root_dirs() == [Path.home().resolve()]

    @pytest.mark.asyncio
    async def test_list_roots_callback_returns_union(
        self, tmp_path: Path,
    ) -> None:
        """Callback returns static CLI dirs ∪ provider dirs, deduplicated
        and deterministically ordered, as a ListRootsResult."""
        import mcp.types

        static_dir = tmp_path / "static"
        static_dir.mkdir()
        scoped_dir = tmp_path / "scoped"
        scoped_dir.mkdir()

        config = _make_config(command=["npx", str(static_dir)])
        session = McpSession(
            config,
            roots_provider=lambda: [scoped_dir.resolve(), static_dir.resolve()],
        )

        result = await session._list_roots(None)

        assert isinstance(result, mcp.types.ListRootsResult)
        expected = sorted(
            {static_dir.resolve(), scoped_dir.resolve()}, key=str,
        )
        assert [str(r.uri) for r in result.roots] == [
            p.as_uri() for p in expected
        ]

    @pytest.mark.asyncio
    async def test_list_roots_callback_provider_error_falls_back(
        self, tmp_path: Path,
    ) -> None:
        """A raising provider must not propagate: static dirs only."""
        import mcp.types

        static_dir = tmp_path / "static"
        static_dir.mkdir()

        def _boom() -> list[Path]:
            raise RuntimeError("provider exploded")

        config = _make_config(command=["npx", str(static_dir)])
        session = McpSession(config, roots_provider=_boom)

        result = await session._list_roots(None)

        assert isinstance(result, mcp.types.ListRootsResult)
        assert [str(r.uri) for r in result.roots] == [
            static_dir.resolve().as_uri()
        ]

    @pytest.mark.asyncio
    async def test_start_passes_list_roots_callback_with_provider(
        self,
    ) -> None:
        """With a roots_provider the ClientSession gets the roots callback
        (which makes the SDK declare the roots capability at initialize)."""
        config = _make_config(command=["echo", "test"])
        session = McpSession(config, roots_provider=lambda: [])

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=_mock_tools_response(),
        )

        with (
            patch("shutil.which", return_value="/usr/bin/echo"),
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
            session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            session_cm.__aexit__ = AsyncMock(return_value=False)
            mock_cs_class.return_value = session_cm

            await session.start()

            kwargs = mock_cs_class.call_args.kwargs
            assert kwargs["list_roots_callback"] == session._list_roots

        await session.stop()

    @pytest.mark.asyncio
    async def test_start_without_provider_passes_no_callback(self) -> None:
        """Without a roots_provider the SDK default is kept (None) so the
        roots capability is NOT declared and CLI dirs stay authoritative."""
        config = _make_config(command=["echo", "test"])
        session = McpSession(config)

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=_mock_tools_response(),
        )

        with (
            patch("shutil.which", return_value="/usr/bin/echo"),
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
            session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            session_cm.__aexit__ = AsyncMock(return_value=False)
            mock_cs_class.return_value = session_cm

            await session.start()

            kwargs = mock_cs_class.call_args.kwargs
            assert kwargs.get("list_roots_callback") is None

        await session.stop()

    @pytest.mark.asyncio
    async def test_notify_roots_changed_noop_without_provider(self) -> None:
        config = _make_config()
        session = McpSession(config)

        mock_sess = AsyncMock()
        session._session = mock_sess
        session._status = ConnectionStatus.CONNECTED

        await session.notify_roots_changed()

        mock_sess.send_roots_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_notify_roots_changed_noop_when_disconnected(self) -> None:
        config = _make_config()
        session = McpSession(config, roots_provider=lambda: [])

        # No connected session at all — must be a silent no-op.
        await session.notify_roots_changed()

    @pytest.mark.asyncio
    async def test_notify_roots_changed_sends_notification(self) -> None:
        config = _make_config()
        session = McpSession(config, roots_provider=lambda: [])

        mock_sess = AsyncMock()
        session._session = mock_sess
        session._status = ConnectionStatus.CONNECTED

        await session.notify_roots_changed()

        mock_sess.send_roots_list_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notify_roots_changed_swallows_errors(self) -> None:
        config = _make_config()
        session = McpSession(config, roots_provider=lambda: [])

        mock_sess = AsyncMock()
        mock_sess.send_roots_list_changed = AsyncMock(
            side_effect=RuntimeError("socket gone"),
        )
        session._session = mock_sess
        session._status = ConnectionStatus.CONNECTED

        # Best-effort: never propagates.
        await session.notify_roots_changed()


class TestMcpSessionStop:
    """Tests for McpSession.stop()."""

    @pytest.mark.asyncio
    async def test_stop_resets_state(self) -> None:
        config = _make_config()
        session = McpSession(config)

        # Simulate connected state (no background task running).
        session._status = ConnectionStatus.CONNECTED
        session._cached_tools = [MagicMock(name="tool1")]

        await session.stop()

        assert session.status == ConnectionStatus.DISCONNECTED
        assert session.get_tools() == []
        assert session._session is None
