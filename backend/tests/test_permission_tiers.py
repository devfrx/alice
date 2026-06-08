"""Tier-by-tier tests for ``PermissionService.decide`` (Fase 7).

Exercises the single policy function across the four tiers
(strict / auto_edits / plan / autopilot) crossed with the operation kinds
(read / write / exec / dangerous / forbidden / confirmation-required) and the
scope-set / scope-unset axis. The pre-Fase-7 behaviour is ``strict`` with no
scope and no rules, so those assertions double as the behaviour-preservation
contract.
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


def _tool(
    name: str = "t",
    *,
    risk_level: str = "safe",
    requires_confirmation: bool = False,
    capabilities: tuple[str, ...] = (),
    path_args: tuple[str, ...] = (),
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="d",
        risk_level=risk_level,  # type: ignore[arg-type]
        requires_confirmation=requires_confirmation,
        capabilities=capabilities,
        path_args=path_args,
    )


def _svc(
    *,
    scope: list | None = None,
    rules: dict[str, RuleEffect] | None = None,
) -> PermissionService:
    scope_provider = (lambda _c: scope) if scope is not None else None
    rule_provider = (lambda _c, t: (rules or {}).get(t)) if rules is not None else None
    return PermissionService(scope_provider=scope_provider, rule_provider=rule_provider)


def _act(
    svc: PermissionService, tool: ToolDefinition, mode: PermissionMode, args=None,
) -> GateAction:
    return svc.decide(
        tool_name=tool.name, args=args or {}, tool_def=tool,
        conversation_id=CONV, mode=mode,
    ).action


# ---------------------------------------------------------------------------
# strict (default) — reproduces the pre-Fase-7 behaviour
# ---------------------------------------------------------------------------


class TestStrict:
    def test_confirmation_tool_prompts(self) -> None:
        act = _act(_svc(), _tool(requires_confirmation=True), PermissionMode.STRICT)
        assert act is GateAction.NEEDS_CONFIRMATION

    def test_plain_tool_allows(self) -> None:
        assert _act(_svc(), _tool(), PermissionMode.STRICT) is GateAction.ALLOW

    def test_forbidden_denies(self) -> None:
        assert _act(_svc(), _tool(risk_level="forbidden"), PermissionMode.STRICT) is GateAction.DENY


# ---------------------------------------------------------------------------
# auto_edits
# ---------------------------------------------------------------------------


class TestAutoEdits:
    def test_safe_write_in_scope_auto_allows(self, tmp_path) -> None:
        svc = _svc(scope=[tmp_path])
        tool = _tool(risk_level="medium", capabilities=("fs_write",), path_args=("path",))
        act = _act(svc, tool, PermissionMode.AUTO_EDITS, args={"path": str(tmp_path / "f.txt")})
        assert act is GateAction.ALLOW

    def test_dangerous_still_prompts(self, tmp_path) -> None:
        svc = _svc(scope=[tmp_path])
        tool = _tool(risk_level="dangerous", capabilities=("fs_write",), path_args=("path",))
        act = _act(svc, tool, PermissionMode.AUTO_EDITS, args={"path": str(tmp_path / "f.txt")})
        assert act is GateAction.NEEDS_CONFIRMATION

    def test_exec_still_prompts(self, tmp_path) -> None:
        svc = _svc(scope=[tmp_path])
        tool = _tool(
            risk_level="dangerous", capabilities=("process_exec", "fs_write"),
            path_args=("cwd",),
        )
        act = _act(svc, tool, PermissionMode.AUTO_EDITS, args={"cwd": str(tmp_path)})
        assert act is GateAction.NEEDS_CONFIRMATION


# ---------------------------------------------------------------------------
# plan (read-only)
# ---------------------------------------------------------------------------


class TestPlan:
    def test_write_denied(self, tmp_path) -> None:
        svc = _svc(scope=[tmp_path])
        tool = _tool(capabilities=("fs_write",), path_args=("path",))
        d = svc.decide(
            tool_name=tool.name, args={"path": str(tmp_path / "f")}, tool_def=tool,
            conversation_id=CONV, mode=PermissionMode.PLAN,
        )
        assert d.action is GateAction.DENY
        assert d.outcome is PermissionOutcome.DENY_PLAN_MODE

    def test_exec_denied(self, tmp_path) -> None:
        svc = _svc(scope=[tmp_path])
        tool = _tool(capabilities=("process_exec",))
        assert _act(svc, tool, PermissionMode.PLAN) is GateAction.DENY

    def test_read_in_scope_allowed(self, tmp_path) -> None:
        svc = _svc(scope=[tmp_path])
        tool = _tool(capabilities=("fs_read",), path_args=("path",), requires_confirmation=True)
        act = _act(svc, tool, PermissionMode.PLAN, args={"path": str(tmp_path / "f")})
        assert act is GateAction.ALLOW  # reads never prompt, even with requires_confirmation

    def test_neutral_safe_tool_allowed(self) -> None:
        assert _act(_svc(), _tool(), PermissionMode.PLAN) is GateAction.ALLOW


# ---------------------------------------------------------------------------
# autopilot
# ---------------------------------------------------------------------------


class TestAutopilot:
    def test_confirmation_tool_runs_without_prompt(self) -> None:
        tool = _tool(requires_confirmation=True, risk_level="dangerous")
        assert _act(_svc(), tool, PermissionMode.AUTOPILOT) is GateAction.ALLOW

    def test_write_in_scope_runs(self, tmp_path) -> None:
        svc = _svc(scope=[tmp_path])
        tool = _tool(risk_level="dangerous", capabilities=("fs_write",), path_args=("path",))
        act = _act(svc, tool, PermissionMode.AUTOPILOT, args={"path": str(tmp_path / "f")})
        assert act is GateAction.ALLOW


# ---------------------------------------------------------------------------
# reads-in-scope never prompt (cross-tier invariant)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode",
    [
        PermissionMode.STRICT,
        PermissionMode.AUTO_EDITS,
        PermissionMode.PLAN,
        PermissionMode.AUTOPILOT,
    ],
)
def test_read_in_scope_never_prompts(tmp_path, mode) -> None:
    svc = _svc(scope=[tmp_path])
    tool = _tool(capabilities=("fs_read",), path_args=("path",), requires_confirmation=True)
    act = _act(svc, tool, mode, args={"path": str(tmp_path / "doc.txt")})
    assert act is GateAction.ALLOW


# ---------------------------------------------------------------------------
# persistent rules override the tier default
# ---------------------------------------------------------------------------


class TestRulesOverrideTier:
    def test_allow_rule_runs_a_strict_confirmation_tool(self) -> None:
        svc = _svc(rules={"t": RuleEffect.ALLOW})
        act = _act(svc, _tool(requires_confirmation=True), PermissionMode.STRICT)
        assert act is GateAction.ALLOW

    def test_ask_rule_prompts_in_autopilot(self) -> None:
        svc = _svc(rules={"t": RuleEffect.ASK})
        assert _act(svc, _tool(), PermissionMode.AUTOPILOT) is GateAction.NEEDS_CONFIRMATION

    def test_deny_rule_blocks_in_autopilot(self) -> None:
        svc = _svc(rules={"t": RuleEffect.DENY})
        d = svc.decide(
            tool_name="t", args={}, tool_def=_tool(), conversation_id=CONV,
            mode=PermissionMode.AUTOPILOT,
        )
        assert d.action is GateAction.DENY
        assert d.outcome is PermissionOutcome.DENY_RULE
