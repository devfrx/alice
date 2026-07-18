"""Tier × capability matrix for MCP tools through ``PermissionService.decide`` (Fase 2).

Pins the permission perimeter for MCP tools end-to-end: the ``ToolDefinition``s
are built with the real annotations→gate mapping (``map_mcp_tool`` over
``mcp.types.Tool``/``ToolAnnotations``), then pushed through the gate exactly
like a native tool. Covers the ``mcp_read``/``mcp_write`` capabilities, the
``plan`` read-only block, the ``path_args`` promotion to real fs confinement,
and the precedence of an explicit user deny-rule.
"""

from __future__ import annotations

from pathlib import Path

from mcp.types import Tool, ToolAnnotations

from backend.core.config import McpServerConfig
from backend.core.plugin_models import ToolDefinition
from backend.services.mcp_tool_mapping import map_mcp_tool
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_rules import RuleEffect
from backend.services.permission_service import (
    GateAction,
    PermissionOutcome,
    PermissionService,
)

CONV = "conv-1"

_PATH_PROPS: dict[str, object] = {"path": {"type": "string"}}


def _mcp_tool(
    name: str = "mcp_srv_tool",
    annotations: ToolAnnotations | None = None,
    properties: dict[str, object] | None = None,
) -> Tool:
    return Tool(
        name=name,
        inputSchema={"type": "object", "properties": properties or {}},
        annotations=annotations,
    )


def _server(path_args: dict[str, list[str]] | None = None) -> McpServerConfig:
    return McpServerConfig(name="srv", command=["x"], path_args=path_args or {})


def _mcp_write_dangerous(name: str = "mcp_srv_write") -> ToolDefinition:
    """MCP tool without annotations → conservative (mcp_write, dangerous, confirm)."""
    return map_mcp_tool(_mcp_tool(name, annotations=None), _server())


def _mcp_write_medium(name: str = "mcp_srv_write") -> ToolDefinition:
    """MCP write with ``destructiveHint=False`` → (mcp_write, medium, confirm)."""
    return map_mcp_tool(
        _mcp_tool(name, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False)),
        _server(),
    )


def _mcp_read(name: str = "mcp_srv_read") -> ToolDefinition:
    """MCP tool with ``readOnlyHint=True`` → (mcp_read, safe, no confirm)."""
    return map_mcp_tool(
        _mcp_tool(name, annotations=ToolAnnotations(readOnlyHint=True)), _server(),
    )


def _mcp_fs_write(name: str = "write_file") -> ToolDefinition:
    """MCP tool promoted to real ``fs_write`` via declared ``path_args``."""
    return map_mcp_tool(
        _mcp_tool(name, annotations=None, properties=_PATH_PROPS),
        _server(path_args={name: ["path"]}),
    )


def _svc(
    *,
    scope: list[Path] | None = None,
    rules: dict[str, RuleEffect] | None = None,
) -> PermissionService:
    scope_provider = (lambda _c: scope) if scope is not None else None
    rule_provider = (lambda _c, t: (rules or {}).get(t)) if rules is not None else None
    return PermissionService(scope_provider=scope_provider, rule_provider=rule_provider)


def _act(
    svc: PermissionService,
    tool: ToolDefinition,
    mode: PermissionMode,
    args: dict[str, object] | None = None,
) -> GateAction:
    return svc.decide(
        tool_name=tool.name, args=args or {}, tool_def=tool,
        conversation_id=CONV, mode=mode,
    ).action


# ---------------------------------------------------------------------------
# tier × capability matrix
# ---------------------------------------------------------------------------


def test_mcp_write_dangerous_prompts_in_strict() -> None:
    # 1. conservative fallback (no annotations) in strict → confirmation.
    act = _act(_svc(), _mcp_write_dangerous(), PermissionMode.STRICT)
    assert act is GateAction.NEEDS_CONFIRMATION


def test_mcp_write_dangerous_prompts_in_auto_edits() -> None:
    # 2. auto_edits never auto-approves a dangerous tool.
    act = _act(_svc(), _mcp_write_dangerous(), PermissionMode.AUTO_EDITS)
    assert act is GateAction.NEEDS_CONFIRMATION


def test_mcp_write_medium_prompts_in_auto_edits() -> None:
    # 3. medium mcp_write is NOT an in-scope fs_write: requires_confirmation wins.
    act = _act(_svc(), _mcp_write_medium(), PermissionMode.AUTO_EDITS)
    assert act is GateAction.NEEDS_CONFIRMATION


def test_mcp_write_denied_in_plan() -> None:
    # 4. plan is read-only: an MCP write is denied, not confirmed.
    tool = _mcp_write_dangerous()
    d = _svc().decide(
        tool_name=tool.name, args={}, tool_def=tool,
        conversation_id=CONV, mode=PermissionMode.PLAN,
    )
    assert d.action is GateAction.DENY
    assert d.outcome is PermissionOutcome.DENY_PLAN_MODE
    assert d.reason == "plan_mode"


def test_mcp_read_allowed_in_strict_and_plan() -> None:
    # 5. readOnlyHint=True → safe read, no prompt in strict nor in plan.
    tool = _mcp_read()
    assert _act(_svc(), tool, PermissionMode.STRICT) is GateAction.ALLOW
    assert _act(_svc(), tool, PermissionMode.PLAN) is GateAction.ALLOW


def test_mcp_write_allowed_in_autopilot() -> None:
    # 6. autopilot runs MCP writes without a prompt.
    act = _act(_svc(), _mcp_write_dangerous(), PermissionMode.AUTOPILOT)
    assert act is GateAction.ALLOW


def test_promoted_fs_write_outside_scope_denied(tmp_path: Path) -> None:
    # 7. path_args promotion → real scope confinement: out-of-scope path denied.
    svc = _svc(scope=[tmp_path])
    tool = _mcp_fs_write()
    assert tool.capabilities == ("fs_write",)  # promotion actually happened
    d = svc.decide(
        tool_name=tool.name, args={"path": str(tmp_path.parent / "outside" / "f.txt")},
        tool_def=tool, conversation_id=CONV, mode=PermissionMode.AUTOPILOT,
    )
    assert d.action is GateAction.DENY
    assert d.outcome is PermissionOutcome.DENY_SCOPE
    assert d.reason == "outside_scope"


def test_promoted_fs_write_in_scope_prompts_in_strict(tmp_path: Path) -> None:
    # 8. in-scope promoted write in strict → confirmation (like a native write).
    svc = _svc(scope=[tmp_path])
    tool = _mcp_fs_write()
    act = _act(svc, tool, PermissionMode.STRICT, args={"path": str(tmp_path / "f.txt")})
    assert act is GateAction.NEEDS_CONFIRMATION


def test_deny_rule_wins_on_mcp_tool_in_every_tier() -> None:
    # 9. an explicit user deny-rule on an mcp_* name beats even autopilot.
    tool = _mcp_write_dangerous("mcp_srv_write")
    svc = _svc(rules={"mcp_srv_write": RuleEffect.DENY})
    d = svc.decide(
        tool_name=tool.name, args={}, tool_def=tool,
        conversation_id=CONV, mode=PermissionMode.AUTOPILOT,
    )
    assert d.action is GateAction.DENY
    assert d.outcome is PermissionOutcome.DENY_RULE
    assert d.reason == "user_denied"
