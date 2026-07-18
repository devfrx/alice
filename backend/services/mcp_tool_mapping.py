"""Pure mapping from MCP tool metadata onto the permission-gate vocabulary.

Spec: docs/superpowers/specs/2026-07-18-agent-v2-fase2-fondamenta-tool-design.md §3.1.
Conservative-by-default: a tool without (trusted) annotations is treated as
destructive — confirmed in strict AND auto_edits, withheld and denied in plan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from backend.core.plugin_models import ToolDefinition

if TYPE_CHECKING:
    from mcp.types import Tool

    from backend.core.config import McpServerConfig

MCP_READ_CAPABILITY = "mcp_read"
MCP_WRITE_CAPABILITY = "mcp_write"


def map_mcp_tool(tool: Tool, server: McpServerConfig) -> ToolDefinition:
    """Build the gate-aware ToolDefinition for one MCP tool.

    Args:
        tool: The raw tool as listed by the MCP server.
        server: The server's connection config (``trust_annotations``,
            ``path_args``).

    Returns:
        A ``ToolDefinition`` whose capabilities / risk_level /
        requires_confirmation / path_args reflect the (trusted) MCP
        annotations, falling back to the conservative destructive-write
        classification when annotations are absent or untrusted.
    """
    annotations = tool.annotations if server.trust_annotations else None

    risk_level: Literal["safe", "medium", "dangerous", "forbidden"]
    if annotations is not None and annotations.readOnlyHint is True:
        capabilities: tuple[str, ...] = (MCP_READ_CAPABILITY,)
        risk_level, requires_confirmation = "safe", False
    elif annotations is not None:
        # Annotations present, not read-only.  MCP spec: destructiveHint
        # defaults to True when omitted.
        destructive = annotations.destructiveHint is not False
        capabilities = (MCP_WRITE_CAPABILITY,)
        risk_level = "dangerous" if destructive else "medium"
        requires_confirmation = True
    else:
        # No annotations (or untrusted server): conservative fallback.
        capabilities = (MCP_WRITE_CAPABILITY,)
        risk_level, requires_confirmation = "dangerous", True

    declared_paths = tuple(server.path_args.get(tool.name, ()))
    if declared_paths:
        # Path-aware tool: promote to a real fs capability so the gate's
        # per-conversation scope confinement applies by construction.
        capabilities = ("fs_read",) if capabilities == (MCP_READ_CAPABILITY,) else ("fs_write",)

    return ToolDefinition(
        name=tool.name,
        # MCP servers can have very long descriptions; truncate to the
        # 1024-char limit enforced by ToolDefinition.validate().
        description=(tool.description or "")[:1024],
        parameters=(tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}}),
        capabilities=capabilities,
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
        path_args=declared_paths,
    )
