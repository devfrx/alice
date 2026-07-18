"""Tests for MCP server config extensions and annotations→gate mapping (Fase 2)."""
from backend.core.config import McpServerConfig


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
