"""O.M.N.I.A. — Single MCP server session manager."""

from __future__ import annotations

import contextlib
import os
from typing import Any

from loguru import logger

from backend.core.config import McpServerConfig
from backend.core.plugin_models import ConnectionStatus, ToolDefinition


class McpSession:
    """Manages the lifecycle of a single MCP server connection.

    Uses the official ``mcp`` SDK for transport abstraction (stdio/SSE).
    The tool list is cached after ``start()`` to allow synchronous
    ``get_tools()``.

    Args:
        config: The server configuration (name, transport, command/url, env).
    """

    def __init__(self, config: McpServerConfig) -> None:
        self._config = config
        self._status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self._cached_tools: list[ToolDefinition] = []
        self._session: Any = None  # mcp.ClientSession (lazy import)
        self._exit_stack: contextlib.AsyncExitStack | None = None

    async def start(self) -> None:
        """Connect, initialize handshake, and cache the tool list.

        Raises:
            RuntimeError: If connection or initialization fails.
        """
        import mcp
        import mcp.client.stdio
        import mcp.client.sse

        stack = contextlib.AsyncExitStack()
        try:
            if self._config.transport == "stdio":
                if not self._config.command:
                    raise RuntimeError(
                        f"MCP server '{self._config.name}': "
                        "stdio transport requires 'command'"
                    )
                # Verify the executable exists before spawning to get a
                # clear error instead of a silent "Connection closed".
                import shutil
                exe = self._config.command[0]
                if not shutil.which(exe):
                    raise RuntimeError(
                        f"MCP server '{self._config.name}': "
                        f"executable '{exe}' not found in PATH"
                    )
                server_params = mcp.StdioServerParameters(
                    command=self._config.command[0],
                    args=self._config.command[1:],
                    env={**os.environ, **self._config.env},
                )
                read, write = await stack.enter_async_context(
                    mcp.client.stdio.stdio_client(server_params)
                )
            else:  # sse
                if not self._config.url:
                    raise RuntimeError(
                        f"MCP server '{self._config.name}': "
                        "sse transport requires 'url'"
                    )
                read, write = await stack.enter_async_context(
                    mcp.client.sse.sse_client(self._config.url)
                )

            session = await stack.enter_async_context(
                mcp.ClientSession(read, write)
            )
            await session.initialize()

            tools_response = await session.list_tools()
            self._cached_tools = [
                ToolDefinition(
                    name=tool.name,
                    description=tool.description or "",
                    parameters=(
                        tool.inputSchema
                        if tool.inputSchema
                        else {"type": "object", "properties": {}}
                    ),
                )
                for tool in tools_response.tools
            ]
            self._session = session
            self._exit_stack = stack
            self._status = ConnectionStatus.CONNECTED
            logger.info(
                "MCP session '{}' connected — {} tools available",
                self._config.name,
                len(self._cached_tools),
            )
        except Exception:
            await stack.aclose()
            self._status = ConnectionStatus.ERROR
            raise

    async def stop(self) -> None:
        """Disconnect and release all resources.

        Uses ``anyio.CancelScope(shield=True)`` so that cleanup completes
        even when the parent task is being cancelled (e.g. during uvicorn
        lifespan teardown after a port-conflict error).
        """
        if self._exit_stack:
            stack = self._exit_stack
            self._exit_stack = None
            try:
                import anyio
                with anyio.CancelScope(shield=True):
                    await stack.aclose()
            except Exception as exc:
                logger.warning(
                    "Error closing MCP session '{}': {}",
                    self._config.name,
                    exc,
                )
        self._session = None
        self._status = ConnectionStatus.DISCONNECTED
        self._cached_tools = []

    def get_tools(self) -> list[ToolDefinition]:
        """Return cached tool definitions (populated after ``start()``)."""
        return list(self._cached_tools)

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute a tools/call request and return the string result.

        Args:
            tool_name: Original tool name (without mcp_ prefix).
            args: Tool arguments dict.

        Returns:
            String content of the tool result.

        Raises:
            RuntimeError: If the session is not connected.
        """
        if (
            self._session is None
            or self._status != ConnectionStatus.CONNECTED
        ):
            raise RuntimeError(
                f"MCP server '{self._config.name}' is not connected"
            )
        result = await self._session.call_tool(tool_name, args)
        return "\n".join(
            block.text
            for block in result.content
            if hasattr(block, "text")
        )

    @property
    def status(self) -> ConnectionStatus:
        """Current connection status."""
        return self._status

    @property
    def server_name(self) -> str:
        """Server name from configuration."""
        return self._config.name
