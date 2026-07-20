"""AL\\CE — REST tests for the typed /api/mcp/* routes (spec Fase 2 §6.4).

Mock level: the routes resolve the plugin ONLY through
``backend.api.routes.mcp.get_mcp_client`` and read config from
``ctx.config.mcp.servers`` — so the tests monkeypatch exactly those two
seams (a structural fake satisfying ``McpClientProtocol`` + a real
``McpServerConfig``) against the real test app. No fake MCP subprocess,
no plugin_manager surgery.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from backend.api.routes.mcp import _tool_level
from backend.core.config import McpServerConfig
from backend.core.plugin_models import McpToolMeta, ToolDefinition

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mcp_tool(
    name: str,
    *,
    meta: McpToolMeta | None,
    risk: str = "medium",
    confirm: bool = True,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"desc {name}",
        risk_level=risk,  # type: ignore[arg-type]
        requires_confirmation=confirm,
        mcp=meta,
    )


def _meta(
    *,
    annotated: bool = True,
    trusted: bool = True,
    read_only: bool = False,
    destructive: bool | None = None,
) -> McpToolMeta:
    return McpToolMeta(
        server="srv",
        annotated=annotated,
        trusted=trusted,
        read_only=read_only,
        destructive=destructive,
    )


class _FakeSession:
    """Bare session stub: only ``get_tools`` is consumed by the routes."""

    def __init__(self, tools: list[ToolDefinition]) -> None:
        self._tools = tools

    def get_tools(self) -> list[ToolDefinition]:
        return self._tools


class _FakeMcpClient:
    """Structural stand-in for ``McpClientProtocol``."""

    def __init__(
        self,
        *,
        tools: list[ToolDefinition] | None = None,
        status: str = "connected",
        fail_reconnect: bool = False,
    ) -> None:
        self._tools = tools or []
        self._status = status
        self._fail_reconnect = fail_reconnect

    async def get_status(self) -> dict[str, str]:
        return {"srv": self._status}

    def get_server_tools(self, server_name: str) -> list[ToolDefinition]:
        if self._status != "connected" or server_name != "srv":
            return []
        return self._tools

    async def reconnect_server(self, server_name: str, config: Any) -> _FakeSession:
        if self._fail_reconnect:
            raise RuntimeError("boom")
        return _FakeSession(self._tools)

    def get_session(self, server_name: str) -> _FakeSession | None:
        if self._status != "connected":
            return None
        return _FakeSession(self._tools)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    app: Any,
    *,
    plugin: _FakeMcpClient | None,
    trust_annotations: bool = True,
) -> None:
    """Wire a fake server config + fake plugin into the test app."""
    cfg = McpServerConfig(
        name="srv",
        command=["echo", "hi"],
        trust_annotations=trust_annotations,
    )
    ctx = app.state.context
    monkeypatch.setattr(ctx.config.mcp, "servers", [cfg])
    monkeypatch.setattr(
        "backend.api.routes.mcp.get_mcp_client", lambda _ctx: plugin,
    )


_TOOL_KEYS = {"name", "description", "level", "risk_level", "requires_confirmation"}
_SERVER_KEYS = {
    "name",
    "transport",
    "enabled",
    "command",
    "url",
    "status",
    "trust_annotations",
    "tools",
}


# ---------------------------------------------------------------------------
# Unit: _tool_level
# ---------------------------------------------------------------------------


def test_tool_level_native_tool_is_fallback() -> None:
    """A tool without MCP provenance (mcp=None) derives to fallback."""
    assert _tool_level(_mcp_tool("t", meta=None)) == "fallback"


def test_tool_level_unannotated_is_fallback() -> None:
    """Missing annotations → conservative fallback, whatever the trust."""
    assert _tool_level(_mcp_tool("t", meta=_meta(annotated=False))) == "fallback"


def test_tool_level_untrusted_is_fallback() -> None:
    """trust_annotations=False demotes even annotated read-only tools."""
    meta = _meta(trusted=False, read_only=True)
    assert _tool_level(_mcp_tool("t", meta=meta)) == "fallback"


def test_tool_level_trusted_read_only() -> None:
    """Annotated + trusted + readOnlyHint → read_only."""
    assert _tool_level(_mcp_tool("t", meta=_meta(read_only=True))) == "read_only"


def test_tool_level_trusted_write() -> None:
    """Annotated + trusted, not read-only → write."""
    meta = _meta(read_only=False, destructive=True)
    assert _tool_level(_mcp_tool("t", meta=meta)) == "write"


# ---------------------------------------------------------------------------
# Routes: GET /api/mcp/servers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_servers_empty(
    client: AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No MCP servers configured → 200 with an empty typed list."""
    monkeypatch.setattr(app.state.context.config.mcp, "servers", [])
    resp = await client.get("/api/mcp/servers")
    assert resp.status_code == 200
    assert resp.json() == {"servers": []}


@pytest.mark.asyncio
async def test_list_servers_typed_shape(
    client: AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Connected server → full shape with trust_annotations + typed tools."""
    tools = [
        _mcp_tool("read_notes", meta=_meta(read_only=True), risk="safe", confirm=False),
        _mcp_tool("write_notes", meta=_meta(destructive=False)),
        _mcp_tool("legacy", meta=_meta(annotated=False), risk="dangerous"),
    ]
    _install(monkeypatch, app, plugin=_FakeMcpClient(tools=tools))

    resp = await client.get("/api/mcp/servers")
    assert resp.status_code == 200
    servers = resp.json()["servers"]
    assert len(servers) == 1

    srv = servers[0]
    assert set(srv.keys()) == _SERVER_KEYS
    assert srv["name"] == "srv"
    assert srv["transport"] == "stdio"
    assert srv["enabled"] is True
    assert srv["command"] == ["echo", "hi"]
    assert srv["url"] is None
    assert srv["status"] == "connected"
    assert srv["trust_annotations"] is True

    by_name = {t["name"]: t for t in srv["tools"]}
    assert set(by_name) == {"read_notes", "write_notes", "legacy"}
    for tool in by_name.values():
        assert set(tool.keys()) == _TOOL_KEYS
    assert by_name["read_notes"]["level"] == "read_only"
    assert by_name["read_notes"]["risk_level"] == "safe"
    assert by_name["read_notes"]["requires_confirmation"] is False
    assert by_name["write_notes"]["level"] == "write"
    assert by_name["legacy"]["level"] == "fallback"
    assert by_name["legacy"]["risk_level"] == "dangerous"


@pytest.mark.asyncio
async def test_list_servers_disconnected_has_no_tools(
    client: AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disconnected server keeps its config entry but exposes no tools."""
    plugin = _FakeMcpClient(tools=[_mcp_tool("t", meta=_meta())], status="error")
    _install(monkeypatch, app, plugin=plugin, trust_annotations=False)

    resp = await client.get("/api/mcp/servers")
    assert resp.status_code == 200
    srv = resp.json()["servers"][0]
    assert srv["status"] == "error"
    assert srv["trust_annotations"] is False
    assert srv["tools"] == []


# ---------------------------------------------------------------------------
# Routes: GET /api/mcp/servers/{server_name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_server_404_when_not_configured(
    client: AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown server name → 404 (semantics unchanged)."""
    monkeypatch.setattr(app.state.context.config.mcp, "servers", [])
    resp = await client.get("/api/mcp/servers/ghost")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_server_detail_typed(
    client: AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-server route returns the same typed flat shape."""
    tools = [_mcp_tool("read_notes", meta=_meta(read_only=True), risk="safe")]
    _install(monkeypatch, app, plugin=_FakeMcpClient(tools=tools))

    resp = await client.get("/api/mcp/servers/srv")
    assert resp.status_code == 200
    srv = resp.json()
    assert set(srv.keys()) == _SERVER_KEYS
    assert srv["name"] == "srv"
    assert srv["trust_annotations"] is True
    assert srv["tools"][0]["level"] == "read_only"


# ---------------------------------------------------------------------------
# Routes: POST /api/mcp/servers/{server_name}/reconnect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnect_503_when_plugin_missing(
    client: AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plugin not loaded → 503 before any config lookup."""
    _install(monkeypatch, app, plugin=None)
    resp = await client.post("/api/mcp/servers/srv/reconnect")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_reconnect_404_when_not_configured(
    client: AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plugin present but server not in config → 404."""
    _install(monkeypatch, app, plugin=_FakeMcpClient())
    resp = await client.post("/api/mcp/servers/ghost/reconnect")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reconnect_success_typed(
    client: AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful reconnect → typed {status, tools_count}."""
    tools = [_mcp_tool("a", meta=_meta()), _mcp_tool("b", meta=_meta())]
    _install(monkeypatch, app, plugin=_FakeMcpClient(tools=tools))
    resp = await client.post("/api/mcp/servers/srv/reconnect")
    assert resp.status_code == 200
    assert resp.json() == {"status": "connected", "tools_count": 2}


@pytest.mark.asyncio
async def test_reconnect_failure_503(
    client: AsyncClient, app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconnect raising inside the plugin → clean 503."""
    _install(monkeypatch, app, plugin=_FakeMcpClient(fail_reconnect=True))
    resp = await client.post("/api/mcp/servers/srv/reconnect")
    assert resp.status_code == 503
