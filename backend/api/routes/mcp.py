"""AL\\CE — MCP server management REST endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel

from backend.api.ws_schema.chat import RiskLevel
from backend.core.config import McpServerConfig
from backend.core.context import AppContext
from backend.core.event_bus import AliceEvent
from backend.core.plugin_models import ToolDefinition
from backend.services.mcp_gateway import McpClientProtocol, get_mcp_client

router = APIRouter(prefix="/mcp", tags=["mcp"])

McpToolLevel = Literal["read_only", "write", "fallback"]
"""UI-facing level derived from the PROVENANCE of the server annotations."""


class McpToolOut(BaseModel):
    """Tool MCP col livello derivato dal gate (spec Fase 2 §6.4)."""

    name: str
    description: str
    level: McpToolLevel
    risk_level: RiskLevel
    requires_confirmation: bool


class McpServerOut(BaseModel):
    """Server MCP configurato: config statica + stato live + tool tipizzati."""

    name: str
    transport: str
    enabled: bool
    command: list[str] | None = None
    url: str | None = None
    status: str
    trust_annotations: bool
    tools: list[McpToolOut]


class McpServersResponse(BaseModel):
    """Elenco completo dei server MCP configurati."""

    servers: list[McpServerOut]


class McpReconnectResponse(BaseModel):
    """Esito di una riconnessione riuscita a un server MCP."""

    status: str
    tools_count: int


def _tool_level(tool_def: ToolDefinition) -> McpToolLevel:
    """Livello UI derivato dalla provenienza annotations (non dall'autorità gate)."""
    m = tool_def.mcp
    if m is None or not m.annotated or not m.trusted:
        return "fallback"
    return "read_only" if m.read_only else "write"


def _server_out(
    cfg: McpServerConfig,
    status: str,
    plugin: McpClientProtocol | None,
) -> McpServerOut:
    """Build the typed view of one configured server."""
    tools: list[McpToolOut] = []
    if plugin:
        tools = [
            McpToolOut(
                name=t.name,
                description=t.description,
                level=_tool_level(t),
                risk_level=t.risk_level,
                requires_confirmation=t.requires_confirmation,
            )
            for t in plugin.get_server_tools(cfg.name)
        ]
    return McpServerOut(
        name=cfg.name,
        transport=cfg.transport,
        enabled=cfg.enabled,
        command=cfg.command,
        url=cfg.url,
        status=status,
        trust_annotations=cfg.trust_annotations,
        tools=tools,
    )


@router.get("/servers", response_model=McpServersResponse)
async def list_mcp_servers(request: Request) -> McpServersResponse:
    """List configured MCP servers and their connection status."""
    ctx: AppContext = request.app.state.context

    plugin = get_mcp_client(ctx)
    statuses: dict[str, str] = {}
    if plugin:
        statuses = await plugin.get_status()

    return McpServersResponse(
        servers=[
            _server_out(cfg, statuses.get(cfg.name, "not_loaded"), plugin)
            for cfg in ctx.config.mcp.servers
        ],
    )


@router.get("/servers/{server_name}", response_model=McpServerOut)
async def get_mcp_server(
    request: Request, server_name: str,
) -> McpServerOut:
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

    plugin = get_mcp_client(ctx)
    statuses: dict[str, str] = {}
    if plugin:
        statuses = await plugin.get_status()

    return _server_out(
        server_config, statuses.get(server_name, "not_loaded"), plugin,
    )


@router.post(
    "/servers/{server_name}/reconnect",
    response_model=McpReconnectResponse,
)
async def reconnect_mcp_server(
    request: Request, server_name: str,
) -> McpReconnectResponse:
    """Attempt to reconnect to a specific MCP server."""
    ctx: AppContext = request.app.state.context

    plugin = get_mcp_client(ctx)
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
        return McpReconnectResponse(
            status="connected",
            tools_count=len(session.get_tools()),
        )
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
        ) from exc
