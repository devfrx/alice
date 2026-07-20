"""Pure mapping from MCP tool metadata onto the permission-gate vocabulary.

Spec: docs/superpowers/specs/2026-07-18-agent-v2-fase2-fondamenta-tool-design.md §3.1.
Conservative-by-default: a tool without (trusted) annotations is treated as
destructive — confirmed in strict AND auto_edits, withheld and denied in plan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger

from backend.core.plugin_models import McpToolMeta, ToolDefinition

# The gate owns the capability vocabulary — single source of truth (no cycle:
# the gate never imports this mapper).
from backend.services.permission_service import (
    MCP_READ_CAPABILITY,
    MCP_WRITE_CAPABILITY,
)

if TYPE_CHECKING:
    from mcp.types import Tool

    from backend.core.config import McpServerConfig


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
        classification when annotations are absent or untrusted.  The
        provenance that this mapping would otherwise discard (server name,
        whether annotations were present, whether they were trusted) is
        preserved structured in ``ToolDefinition.mcp`` (:class:`McpToolMeta`)
        for downstream consumers — informational only, never read by the gate.

    Notes:
        ``path_args`` promotion is validated against the tool's
        ``inputSchema``: every declared argument must exist in the schema's
        ``properties``, otherwise the scope check would be vacuous
        (``args.get(name)`` always ``None``). On mismatch (config typo, or
        the server renamed the argument) the tool falls back to the
        conservative classification with empty ``path_args`` — fail-closed.
        A tool mapped to an explicitly empty list (``path_args: {"tool": []}``)
        is deliberately treated as NOT path-aware: no fs promotion, the plain
        annotation-derived classification applies.
    """
    annotations = tool.annotations if server.trust_annotations else None

    risk_level: Literal["safe", "medium", "dangerous", "forbidden"]
    if annotations is not None and annotations.readOnlyHint is True:
        capabilities: tuple[str, ...] = (MCP_READ_CAPABILITY,)
        risk_level, requires_confirmation = "safe", False
        meta = McpToolMeta(
            server=server.name,
            annotated=True,
            trusted=True,
            read_only=True,
            destructive=False,
        )
    elif annotations is not None:
        # Annotations present, not read-only.  MCP spec: destructiveHint
        # defaults to True when omitted.
        destructive = annotations.destructiveHint is not False
        capabilities = (MCP_WRITE_CAPABILITY,)
        risk_level = "dangerous" if destructive else "medium"
        requires_confirmation = True
        meta = McpToolMeta(
            server=server.name,
            annotated=True,
            trusted=True,
            read_only=False,
            destructive=destructive,
        )
    else:
        # No annotations (or untrusted server): conservative fallback.
        # ``annotated`` legge ``tool.annotations`` ORIGINALE: la locale
        # ``annotations`` è già azzerata quando il server non è fidato,
        # ma il meta deve dire la verità sulla provenienza.
        capabilities = (MCP_WRITE_CAPABILITY,)
        risk_level, requires_confirmation = "dangerous", True
        meta = McpToolMeta(
            server=server.name,
            annotated=tool.annotations is not None,
            trusted=server.trust_annotations,
            read_only=False,
            destructive=None,
        )

    declared_paths = tuple(server.path_args.get(tool.name, ()))
    if declared_paths:
        schema_properties = (tool.inputSchema or {}).get("properties")
        if not isinstance(schema_properties, dict):
            # Malformed schema (``properties`` null, string, list, …): a
            # ``in`` check against a non-dict would raise or, worse, match
            # by substring.  Treat every declared arg as missing instead —
            # same fail-closed path, same warning.
            schema_properties = {}
        missing = [arg for arg in declared_paths if arg not in schema_properties]
        if missing:
            # Fail-closed: promoting anyway would give the gate a vacuous
            # scope check (the declared arg never appears in the call args,
            # so ``args.get(name)`` is always ``None`` and every call passes).
            logger.warning(
                "MCP server '{}' tool '{}': declared path_args {} not found "
                "in the tool's inputSchema properties — ignoring path_args "
                "and applying the conservative classification",
                server.name,
                tool.name,
                missing,
            )
            capabilities = (MCP_WRITE_CAPABILITY,)
            risk_level, requires_confirmation = "dangerous", True
            declared_paths = ()
        else:
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
        mcp=meta,
    )
