"""AL\\CE — Typed access to the MCP client plugin for REST routes.

Routes must not import plugin internals (layering contract §4).  This
module gives them a STRUCTURAL protocol of the (few) ``McpClientPlugin``
methods they use plus accessors that normalise the unavailable states
into the canonical 503s.  The plugin satisfies the protocol implicitly;
nothing here imports from ``backend.plugins``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from fastapi import HTTPException

if TYPE_CHECKING:
    from backend.core.context import AppContext
    from backend.core.plugin_models import ToolDefinition
    from backend.services.mcp_session import McpSession


@runtime_checkable
class McpClientProtocol(Protocol):
    """The surface of the MCP client plugin consumed by REST routes."""

    async def get_status(self) -> dict[str, str]:
        """Connection status per configured server."""
        ...

    def get_server_tools(self, server_name: str) -> list[ToolDefinition]:
        """Tool definitions currently exposed by a server."""
        ...

    async def reconnect_server(
        self, server_name: str, config: object,
    ) -> McpSession:
        """Tear down and re-establish a server session."""
        ...

    def get_session(self, server_name: str) -> McpSession | None:
        """The live session for a server, or ``None`` if not connected."""
        ...


def get_mcp_client(ctx: AppContext) -> McpClientProtocol | None:
    """The MCP client plugin as a protocol, or ``None`` if not loaded."""
    if ctx.plugin_manager is None:
        return None
    plugin = ctx.plugin_manager.get_plugin("mcp_client")
    if plugin is None:
        return None
    return cast("McpClientProtocol", plugin)  # structural: McpClientPlugin satisfies the protocol


def require_mcp_session(ctx: AppContext, server_name: str) -> McpSession:
    """The live MCP session for ``server_name`` or the canonical 503s.

    Raises:
        HTTPException: 503 when the plugin manager, the MCP client plugin
            or the server session is unavailable.
    """
    if ctx.plugin_manager is None:
        raise HTTPException(503, "Plugin manager not available")
    client = get_mcp_client(ctx)
    if client is None:
        raise HTTPException(503, "MCP client plugin not loaded")
    session = client.get_session(server_name)
    if session is None:
        raise HTTPException(503, f"MCP server '{server_name}' not connected")
    return session
