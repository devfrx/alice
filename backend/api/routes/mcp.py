"""AL\\CE — MCP server management REST endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from backend.core.context import AppContext
from backend.core.event_bus import AliceEvent

if TYPE_CHECKING:
    from backend.plugins.mcp_client.plugin import McpClientPlugin

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _get_mcp_plugin(ctx: AppContext) -> McpClientPlugin | None:
    """Retrieve the McpClientPlugin from the plugin manager.

    Returns:
        The McpClientPlugin instance, or None if not loaded.
    """
    if ctx.plugin_manager is None:
        return None
    return ctx.plugin_manager.get_plugin("mcp_client")


@router.get("/servers")
async def list_mcp_servers(request: Request) -> dict[str, Any]:
    """List configured MCP servers and their connection status."""
    ctx: AppContext = request.app.state.context

    configured = [
        {
            "name": s.name,
            "transport": s.transport,
            "enabled": s.enabled,
            "command": s.command,
            "url": s.url,
        }
        for s in ctx.config.mcp.servers
    ]

    plugin = _get_mcp_plugin(ctx)
    statuses: dict[str, str] = {}
    if plugin:
        statuses = await plugin.get_status()

    servers = []
    for srv in configured:
        name = srv["name"]
        srv_tools: list[dict[str, str]] = []
        if plugin:
            srv_tools = [
                {"name": t.name, "description": t.description}
                for t in plugin.get_server_tools(name)
            ]
        servers.append({
            **srv,
            "status": statuses.get(name, "not_loaded"),
            "tools": srv_tools,
        })

    return {"servers": servers}


@router.get("/servers/{server_name}")
async def get_mcp_server(
    request: Request, server_name: str,
) -> dict[str, Any]:
    """Get details for a specific MCP server."""
    ctx: AppContext = request.app.state.context

    server_config = next(
        (s for s in ctx.config.mcp.servers if s.name == server_name),
        None,
    )
    if server_config is None:
        raise HTTPException(
            status_code=404,
            detail=f"MCP server '{server_name}' not found",
        )

    plugin = _get_mcp_plugin(ctx)
    statuses: dict[str, str] = {}
    if plugin:
        statuses = await plugin.get_status()

    tools: list[dict[str, str]] = []
    if plugin:
        tools = [
            {"name": t.name, "description": t.description}
            for t in plugin.get_server_tools(server_name)
        ]

    return {
        "name": server_config.name,
        "transport": server_config.transport,
        "enabled": server_config.enabled,
        "command": server_config.command,
        "url": server_config.url,
        "status": statuses.get(server_name, "not_loaded"),
        "tools": tools,
    }


@router.post("/servers/{server_name}/reconnect")
async def reconnect_mcp_server(
    request: Request, server_name: str,
) -> dict[str, Any]:
    """Attempt to reconnect to a specific MCP server."""
    ctx: AppContext = request.app.state.context

    plugin = _get_mcp_plugin(ctx)
    if plugin is None:
        raise HTTPException(
            status_code=503,
            detail="MCP client plugin not loaded",
        )

    server_config = next(
        (s for s in ctx.config.mcp.servers if s.name == server_name),
        None,
    )
    if server_config is None:
        raise HTTPException(
            status_code=404,
            detail=f"MCP server '{server_name}' not found",
        )

    try:
        session = await plugin.reconnect_server(
            server_name, server_config,
        )
        await ctx.event_bus.emit(
            AliceEvent.MCP_SERVER_CONNECTED, server=server_name,
        )
        return {
            "status": "connected",
            "tools_count": len(session.get_tools()),
        }
    except Exception as exc:
        logger.warning(
            "MCP reconnect '{}' failed: {}", server_name, exc,
        )
        await ctx.event_bus.emit(
            AliceEvent.MCP_SERVER_DISCONNECTED,
            server=server_name,
            reason=str(exc),
        )
        raise HTTPException(
            status_code=503,
            detail=f"Reconnection failed: {exc}",
        )
