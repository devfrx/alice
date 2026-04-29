"""AL\\CE — MCP Client plugin.

Bridges AL\\CE to external MCP servers. Each server's tools are
namespaced as ``mcp_{server_name}_{tool_name}`` and exposed via
``get_tools()``, making them available to the LLM automatically.
"""

from __future__ import annotations

import re
from typing import Any

from backend.core.context import AppContext
from backend.core.event_bus import AliceEvent
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.services.mcp_session import McpSession


class McpClientPlugin(BasePlugin):
    """Bridges AL\\CE to external MCP servers.

    At startup, connects to every enabled server in ``config.mcp.servers``.
    Each server's tools are namespaced as ``mcp_{server_name}_{tool_name}``
    and exposed via ``get_tools()``, making them available to the LLM.
    """

    plugin_name = "mcp_client"
    plugin_version = "1.0.0"
    plugin_description = (
        "Bridges AL\\CE to external MCP servers "
        "(filesystem, git, browser, search engine, …)"
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 10  # Load after other plugins

    def __init__(self) -> None:
        super().__init__()
        self._sessions: dict[str, McpSession] = {}
        self._tool_dispatch_map: dict[str, tuple[str, str]] = {}

    async def initialize(self, ctx: AppContext) -> None:
        """Connect to all enabled MCP servers from configuration."""
        await super().initialize(ctx)

        for server_cfg in ctx.config.mcp.servers:
            if not server_cfg.enabled:
                self.logger.debug(
                    "MCP server '{}' is disabled, skipping",
                    server_cfg.name,
                )
                continue

            session = McpSession(server_cfg)
            try:
                await session.start()
                self._sessions[server_cfg.name] = session
                self.logger.info(
                    "MCP '{}' connected ({} tools)",
                    server_cfg.name,
                    len(session.get_tools()),
                )
                await ctx.event_bus.emit(
                    AliceEvent.MCP_SERVER_CONNECTED,
                    server=server_cfg.name,
                )
            except Exception as exc:
                self.logger.error(
                    "MCP '{}' connection failed: {}",
                    server_cfg.name,
                    exc,
                )
                await ctx.event_bus.emit(
                    AliceEvent.MCP_SERVER_DISCONNECTED,
                    server=server_cfg.name,
                    reason=str(exc),
                )

    async def cleanup(self) -> None:
        """Disconnect all MCP sessions."""
        for session in self._sessions.values():
            try:
                await session.stop()
            except Exception as exc:
                self.logger.warning(
                    "Error closing MCP '{}': {}",
                    session.server_name,
                    exc,
                )
        self._sessions.clear()
        self._tool_dispatch_map.clear()
        await super().cleanup()

    # MCP tools often return large payloads (web pages, file content, directory
    # listings, search results).  Using the global default of 4 KB would cause
    # almost every fetch-style call to be silently truncated before the LLM
    # can act on it.  20 000 chars is a safe ceiling that stays well within
    # typical context windows while covering most real-world responses.
    _MCP_MAX_RESULT_CHARS: int = 20_000

    # Maximum length for a tool name (from plugin_models.TOOL_NAME_PATTERN).
    _MAX_TOOL_NAME_LEN: int = 64

    def get_tools(self) -> list[ToolDefinition]:
        """Aggregate tool definitions from all connected MCP sessions."""
        tools: list[ToolDefinition] = []
        dispatch_map: dict[str, tuple[str, str]] = {}
        for server_name, session in self._sessions.items():
            if session.status != ConnectionStatus.CONNECTED:
                continue
            safe_server = re.sub(r"[^a-zA-Z0-9_-]", "_", server_name)
            for tool in session.get_tools():
                full_name = f"mcp_{safe_server}_{tool.name}"
                # Truncate to 64-char limit enforced by ToolDefinition
                if len(full_name) > self._MAX_TOOL_NAME_LEN:
                    self.logger.warning(
                        "MCP tool name '{}' exceeds {} chars, truncating",
                        full_name, self._MAX_TOOL_NAME_LEN,
                    )
                    full_name = full_name[:self._MAX_TOOL_NAME_LEN]
                # Truncation may collide with another tool that already
                # mapped to the same prefix.  Skip the duplicate so we do
                # not silently route both names to the wrong server/tool.
                if full_name in dispatch_map:
                    existing_server, existing_tool = dispatch_map[full_name]
                    self.logger.warning(
                        "MCP tool name collision after truncation: '{}' "
                        "already maps to ({}, {}); skipping ({}, {})",
                        full_name,
                        existing_server, existing_tool,
                        server_name, tool.name,
                    )
                    continue
                full_desc = f"[{server_name}] {tool.description}"
                try:
                    tools.append(
                        ToolDefinition(
                            name=full_name,
                            description=full_desc[:512],
                            parameters=tool.parameters,
                            max_result_chars=self._MCP_MAX_RESULT_CHARS,
                        )
                    )
                    # Map display name → (server, original tool name)
                    # so truncated names dispatch to the correct tool.
                    dispatch_map[full_name] = (server_name, tool.name)
                except ValueError as exc:
                    self.logger.warning(
                        "Skipping invalid MCP tool '{}': {}",
                        full_name, exc,
                    )
        self._tool_dispatch_map = dispatch_map
        return tools

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch a tool call to the correct MCP session.

        Uses the dispatch map populated by :meth:`get_tools` for O(1)
        lookup that correctly handles truncated tool names.  Falls back
        to prefix matching when the map has no entry.
        """
        # Fast path: dispatch map (handles truncated names correctly)
        if tool_name in self._tool_dispatch_map:
            server_name, original_name = self._tool_dispatch_map[tool_name]
            session = self._sessions.get(server_name)
            if session is None:
                return ToolResult.error(
                    f"MCP server '{server_name}' is not connected"
                )
            try:
                content = await session.call_tool(original_name, args)
                return ToolResult.ok(content)
            except Exception as exc:
                return ToolResult.error(
                    f"MCP tool '{original_name}' on server "
                    f"'{server_name}' failed: {exc}"
                )

        # Fallback: prefix matching for tools not yet in the map
        sorted_sessions = sorted(
            self._sessions.items(),
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
        for server_name, session in sorted_sessions:
            safe_server = re.sub(r"[^a-zA-Z0-9_-]", "_", server_name)
            prefix = f"mcp_{safe_server}_"
            if tool_name.startswith(prefix):
                original_name = tool_name[len(prefix):]
                try:
                    content = await session.call_tool(
                        original_name, args,
                    )
                    return ToolResult.ok(content)
                except Exception as exc:
                    return ToolResult.error(
                        f"MCP tool '{original_name}' on server "
                        f"'{server_name}' failed: {exc}"
                    )

        return ToolResult.error(f"MCP tool not found: {tool_name}")

    async def get_connection_status(self) -> ConnectionStatus:
        """Aggregate connection status across all MCP sessions."""
        if not self._sessions:
            return ConnectionStatus.CONNECTED  # No servers = not an error
        connected = sum(
            1
            for s in self._sessions.values()
            if s.status == ConnectionStatus.CONNECTED
        )
        if connected == len(self._sessions):
            return ConnectionStatus.CONNECTED
        return (
            ConnectionStatus.DEGRADED
            if connected > 0
            else ConnectionStatus.ERROR
        )

    def get_server_tools(
        self, server_name: str,
    ) -> list[ToolDefinition]:
        """Return tool definitions for a specific connected server."""
        session = self._sessions.get(server_name)
        if session and session.status == ConnectionStatus.CONNECTED:
            return session.get_tools()
        return []

    def get_session(self, server_name: str) -> McpSession | None:
        """Return the live :class:`McpSession` for ``server_name``.

        Public accessor used by REST endpoints (e.g. the MCP memory
        routes) that need to invoke tools on a specific server without
        going through the LLM tool-dispatch path.

        Args:
            server_name: Name of the configured MCP server.

        Returns:
            The live session if the server is connected, otherwise
            ``None``. The returned session may be in any
            :class:`ConnectionStatus`; callers should check
            ``session.status`` if they require a healthy connection.
        """
        return self._sessions.get(server_name)

    async def reconnect_server(
        self, server_name: str, config: Any,
    ) -> McpSession:
        """Stop existing session (if any) and reconnect.

        Args:
            server_name: Name of the server to reconnect.
            config: McpServerConfig for the server.

        Returns:
            The new connected McpSession.

        Raises:
            RuntimeError: If reconnection fails.
        """
        old_session = self._sessions.pop(server_name, None)
        if old_session:
            try:
                await old_session.stop()
            except Exception as exc:
                # Stale connection cleanup is best-effort; the new
                # session will be created regardless.  Log so operators
                # can spot zombie subprocesses / leaked file handles.
                logger.warning(
                    "Failed to stop stale MCP session for '{}': {}",
                    server_name,
                    exc,
                )

        session = McpSession(config)
        await session.start()
        self._sessions[server_name] = session
        return session

    async def get_status(self) -> dict[str, str]:
        """Return per-server connection status for health reporting."""
        return {
            name: s.status.value
            for name, s in self._sessions.items()
        }
