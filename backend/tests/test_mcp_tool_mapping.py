"""Tests for MCP server config extensions and annotations→gate mapping (Fase 2)."""

from mcp.types import Tool, ToolAnnotations

from backend.core.config import McpServerConfig
from backend.services.mcp_tool_mapping import map_mcp_tool


def test_mcp_server_config_defaults() -> None:
    cfg = McpServerConfig(name="filesystem", command=["npx", "server"])
    assert cfg.trust_annotations is True
    assert cfg.path_args == {}


def test_mcp_server_config_explicit_values() -> None:
    cfg = McpServerConfig(
        name="filesystem",
        command=["npx", "server"],
        trust_annotations=False,
        path_args={"write_file": ["path"], "move_file": ["source", "destination"]},
    )
    assert cfg.trust_annotations is False
    assert cfg.path_args["move_file"] == ["source", "destination"]


def _tool(name: str = "t", annotations: ToolAnnotations | None = None) -> Tool:
    return Tool(
        name=name,
        inputSchema={"type": "object", "properties": {}},
        annotations=annotations,
    )


def _server(**kw) -> McpServerConfig:
    return McpServerConfig(name="srv", command=["x"], **kw)


def test_read_only_tool_maps_to_mcp_read_safe_no_confirm() -> None:
    td = map_mcp_tool(_tool(annotations=ToolAnnotations(readOnlyHint=True)), _server())
    assert td.capabilities == ("mcp_read",)
    assert td.risk_level == "safe"
    assert td.requires_confirmation is False


def test_non_destructive_write_maps_to_mcp_write_medium_confirm() -> None:
    td = map_mcp_tool(
        _tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False)),
        _server(),
    )
    assert td.capabilities == ("mcp_write",)
    assert td.risk_level == "medium"
    assert td.requires_confirmation is True


def test_destructive_write_maps_to_dangerous() -> None:
    td = map_mcp_tool(
        _tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True)),
        _server(),
    )
    assert td.risk_level == "dangerous"
    assert td.requires_confirmation is True


def test_missing_annotations_falls_back_conservative() -> None:
    td = map_mcp_tool(_tool(annotations=None), _server())
    assert td.capabilities == ("mcp_write",)
    assert td.risk_level == "dangerous"
    assert td.requires_confirmation is True


def test_untrusted_server_ignores_annotations() -> None:
    td = map_mcp_tool(
        _tool(annotations=ToolAnnotations(readOnlyHint=True)),
        _server(trust_annotations=False),
    )
    assert td.capabilities == ("mcp_write",)
    assert td.risk_level == "dangerous"


def test_path_args_promote_to_fs_capability() -> None:
    server = _server(path_args={"write_file": ["path"], "read_file": ["path"]})
    write_td = map_mcp_tool(
        _tool(
            name="write_file",
            annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
        ),
        server,
    )
    read_td = map_mcp_tool(
        _tool(name="read_file", annotations=ToolAnnotations(readOnlyHint=True)), server
    )
    assert write_td.capabilities == ("fs_write",)
    assert write_td.path_args == ("path",)
    assert read_td.capabilities == ("fs_read",)
    assert read_td.path_args == ("path",)
