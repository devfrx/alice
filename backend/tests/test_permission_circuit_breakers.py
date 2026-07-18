"""Circuit-breaker tests for ``PermissionService.decide`` (Fase 7).

The breakers hold in **every** tier — even ``autopilot``: a forbidden tool, a
filesystem tool with no workspace scope set, and an out-of-scope path are always
denied. An explicit ``allow`` rule may bypass *only* the out-of-scope check,
never the forbidden or no-scope breakers.
"""

from __future__ import annotations

import pytest

from backend.core.plugin_models import ToolDefinition
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_rules import RuleEffect
from backend.services.permission_service import (
    GateAction,
    PermissionOutcome,
    PermissionService,
)

CONV = "conv-1"
ALL_TIERS = [
    PermissionMode.STRICT,
    PermissionMode.AUTO_EDITS,
    PermissionMode.PLAN,
    PermissionMode.AUTOPILOT,
]


def _tool(name: str = "t", *, risk_level: str = "safe", capabilities=(), path_args=()):
    return ToolDefinition(
        name=name, description="d", risk_level=risk_level,  # type: ignore[arg-type]
        capabilities=capabilities, path_args=path_args,
    )


@pytest.mark.parametrize("mode", ALL_TIERS)
def test_forbidden_blocked_in_every_tier(mode) -> None:
    svc = PermissionService()
    d = svc.decide(
        tool_name="t", args={}, tool_def=_tool(risk_level="forbidden"),
        conversation_id=CONV, mode=mode,
    )
    assert d.action is GateAction.DENY
    assert d.outcome is PermissionOutcome.DENY_FORBIDDEN


@pytest.mark.parametrize("mode", ALL_TIERS)
def test_fs_tool_with_no_scope_blocked_in_every_tier(mode) -> None:
    # No scope provider ⇒ no workspace boundary ⇒ filesystem tools are blocked.
    svc = PermissionService()
    tool = _tool(capabilities=("fs_write",), path_args=("path",))
    d = svc.decide(
        tool_name="t", args={"path": "C:/anywhere/f.txt"}, tool_def=tool,
        conversation_id=CONV, mode=mode,
    )
    assert d.action is GateAction.DENY
    assert d.outcome is PermissionOutcome.DENY_NO_SCOPE


@pytest.mark.parametrize("mode", ALL_TIERS)
def test_out_of_scope_path_blocked_in_every_tier(tmp_path, mode) -> None:
    scope = tmp_path / "ws"
    scope.mkdir()
    svc = PermissionService(scope_provider=lambda _c: [scope])
    tool = _tool(capabilities=("fs_write",), path_args=("path",))
    d = svc.decide(
        tool_name="t", args={"path": str(tmp_path / "outside" / "f.txt")},
        tool_def=tool, conversation_id=CONV, mode=mode,
    )
    assert d.action is GateAction.DENY
    assert d.outcome is PermissionOutcome.DENY_SCOPE


def test_allow_rule_bypasses_out_of_scope_but_not_no_scope(tmp_path) -> None:
    scope = tmp_path / "ws"
    scope.mkdir()
    svc = PermissionService(
        scope_provider=lambda _c: [scope],
        rule_provider=lambda _c, _t: RuleEffect.ALLOW,
    )
    tool = _tool(capabilities=("fs_write",), path_args=("path",))

    # Out-of-scope path: the allow rule lets it through (in autopilot → ALLOW).
    d = svc.decide(
        tool_name="t", args={"path": str(tmp_path / "outside" / "f")},
        tool_def=tool, conversation_id=CONV, mode=PermissionMode.AUTOPILOT,
    )
    assert d.action is GateAction.ALLOW

    # But an allow rule cannot conjure a scope: with NO scope set, still denied.
    svc_noscope = PermissionService(rule_provider=lambda _c, _t: RuleEffect.ALLOW)
    d2 = svc_noscope.decide(
        tool_name="t", args={"path": "C:/x/f"}, tool_def=tool,
        conversation_id=CONV, mode=PermissionMode.AUTOPILOT,
    )
    assert d2.action is GateAction.DENY
    assert d2.outcome is PermissionOutcome.DENY_NO_SCOPE


def test_allow_rule_bypasses_out_of_scope_but_not_forbidden(tmp_path) -> None:
    scope = tmp_path / "ws"
    scope.mkdir()
    svc = PermissionService(
        scope_provider=lambda _c: [scope],
        rule_provider=lambda _c, _t: RuleEffect.ALLOW,
    )
    # Out-of-scope path with an allow rule → ALLOW.
    tool = _tool(capabilities=("fs_write",), path_args=("path",))
    assert svc.decide(
        tool_name="t", args={"path": str(tmp_path / "outside" / "f")},
        tool_def=tool, conversation_id=CONV, mode=PermissionMode.STRICT,
    ).action is GateAction.ALLOW

    # Forbidden still wins over an allow rule.
    forbidden = _tool(risk_level="forbidden")
    d = svc.decide(
        tool_name="t", args={}, tool_def=forbidden,
        conversation_id=CONV, mode=PermissionMode.STRICT,
    )
    assert d.action is GateAction.DENY
    assert d.outcome is PermissionOutcome.DENY_FORBIDDEN
