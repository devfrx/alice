"""Tests for the central PermissionService gate (risk, scope, rules).

Covers the responsibilities the agent engine delegates to
``PermissionService.decide``: risk policy (forbidden), by-construction
filesystem scope confinement (deny-by-default outside the conversation
scope), and persisted ``PermissionRule`` overrides via ``rule_provider``.
Tier-by-tier behaviour lives in ``test_permission_tiers.py``; the cross-tier
circuit breakers (forbidden / no-scope / out-of-scope in every tier) in
``test_permission_circuit_breakers.py``.
"""

from __future__ import annotations

from pathlib import Path

from backend.core.plugin_models import ToolDefinition
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_rules import RuleEffect
from backend.services.permission_service import (
    GateAction,
    GateDecision,
    PermissionOutcome,
    PermissionService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONV = "conv-1"


def _tool(
    name: str,
    *,
    risk_level: str = "safe",
    requires_confirmation: bool = False,
    capabilities: tuple[str, ...] = (),
    path_args: tuple[str, ...] = (),
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Test tool {name}",
        risk_level=risk_level,  # type: ignore[arg-type]
        requires_confirmation=requires_confirmation,
        capabilities=capabilities,
        path_args=path_args,
    )


def _decide(
    svc: PermissionService,
    tool_def: ToolDefinition | None,
    args: dict[str, object] | None = None,
    *,
    conversation_id: str = _CONV,
    mode: PermissionMode = PermissionMode.STRICT,
) -> GateDecision:
    return svc.decide(
        tool_name=tool_def.name if tool_def is not None else "mystery",
        args=args or {},
        tool_def=tool_def,
        conversation_id=conversation_id,
        mode=mode,
    )


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------


class TestRiskPolicy:
    def test_non_forbidden_levels_allowed_without_confirmation(self) -> None:
        """Risk levels other than ``forbidden`` never deny by themselves."""
        svc = PermissionService()
        for level in ("safe", "medium", "dangerous"):
            decision = _decide(svc, _tool(f"t_{level}", risk_level=level))
            assert decision.action is GateAction.ALLOW, level
            assert decision.outcome is PermissionOutcome.ALLOW

    def test_unknown_tool_def_allowed(self) -> None:
        """``tool_def=None`` is allowed here (the registry rejects truly
        unknown tools at execution time)."""
        svc = PermissionService()
        assert _decide(svc, None).action is GateAction.ALLOW

    def test_requires_confirmation_classification(self) -> None:
        assert PermissionService.requires_confirmation(
            _tool("c", requires_confirmation=True),
        ) is True
        assert PermissionService.requires_confirmation(_tool("c")) is False
        assert PermissionService.requires_confirmation(None) is False

    def test_is_forbidden_helper(self) -> None:
        assert PermissionService.is_forbidden(
            _tool("x", risk_level="forbidden"),
        ) is True
        assert PermissionService.is_forbidden(_tool("x")) is False
        assert PermissionService.is_forbidden(None) is False


# ---------------------------------------------------------------------------
# Scope confinement (by construction)
# ---------------------------------------------------------------------------


class TestScopeConfinement:
    """Confinement mechanics unique to this suite.

    The basic in/out-of-scope cases and the no-scope breaker are pinned
    across every tier in ``test_permission_circuit_breakers.py``.
    """

    def test_path_inside_scope_allowed(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("fs_write_file", capabilities=("fs_write",), path_args=("path",))
        inside = str(scope / "sub" / "note.txt")
        assert _decide(svc, tool, {"path": inside}).action is GateAction.ALLOW

    def test_traversal_cannot_escape_scope(self, tmp_path: Path) -> None:
        """A ``..`` traversal out of the scope resolves and is denied."""
        scope = tmp_path / "workspace"
        scope.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("fs_read_file", capabilities=("fs_read",), path_args=("path",))
        sneaky = str(scope / ".." / "etc" / "shadow")
        decision = _decide(svc, tool, {"path": sneaky})
        assert decision.action is GateAction.DENY
        assert decision.outcome is PermissionOutcome.DENY_SCOPE

    def test_non_fs_tool_not_confined(self, tmp_path: Path) -> None:
        """A tool without an fs_* capability is never path-confined, even
        when its args carry an out-of-scope path."""
        scope = tmp_path / "workspace"
        scope.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("web_fetch", path_args=("path",))  # no fs capability
        outside = str(tmp_path / "elsewhere" / "x")
        assert _decide(svc, tool, {"path": outside}).action is GateAction.ALLOW

    def test_fs_tool_without_path_arg_present_allowed(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("fs_list", capabilities=("fs_read",), path_args=("path",))
        # No "path" key supplied → nothing to confine → allowed.
        assert _decide(svc, tool, {}).action is GateAction.ALLOW

    def test_forbidden_path_inside_scope_denied(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        blocked = scope / "secret"
        blocked.mkdir()
        svc = PermissionService(
            scope_provider=lambda _c: [scope],
            forbidden_paths=[blocked],
        )
        tool = _tool("fs_read_file", capabilities=("fs_read",), path_args=("path",))
        decision = _decide(svc, tool, {"path": str(blocked / "key.pem")})
        assert decision.action is GateAction.DENY
        assert decision.outcome is PermissionOutcome.DENY_SCOPE

    def test_multiple_scope_roots(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [a, b])
        tool = _tool("fs_read_file", capabilities=("fs_read",), path_args=("path",))
        assert _decide(svc, tool, {"path": str(b / "f")}).action is GateAction.ALLOW


# ---------------------------------------------------------------------------
# Persisted rule overrides (the "remember" of a confirmation)
# ---------------------------------------------------------------------------


class TestRuleOverrides:
    """An ``allow`` rule bypasses only the out-of-scope check.

    Forbidden-beats-allow-rule and the no-scope breaker are pinned in
    ``test_permission_circuit_breakers.py``.
    """

    def test_allow_rule_bypasses_scope_denial(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        outside = str(tmp_path / "elsewhere" / "f.txt")
        rules: dict[str, RuleEffect] = {}
        svc = PermissionService(
            scope_provider=lambda _c: [scope],
            rule_provider=lambda _c, tool: rules.get(tool),
        )
        tool = _tool("fs_write_file", capabilities=("fs_write",), path_args=("path",))

        assert _decide(svc, tool, {"path": outside}).action is GateAction.DENY
        rules["fs_write_file"] = RuleEffect.ALLOW
        assert _decide(svc, tool, {"path": outside}).action is GateAction.ALLOW

    def test_allow_rule_is_scoped_per_conversation(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        outside = str(tmp_path / "elsewhere" / "f.txt")
        svc = PermissionService(
            scope_provider=lambda _c: [scope],
            rule_provider=lambda conv, _t: (
                RuleEffect.ALLOW if conv == "conv-A" else None
            ),
        )
        tool = _tool("fs_write_file", capabilities=("fs_write",), path_args=("path",))

        assert (
            _decide(svc, tool, {"path": outside}, conversation_id="conv-A").action
            is GateAction.ALLOW
        )
        # Other conversation is unaffected.
        assert (
            _decide(svc, tool, {"path": outside}, conversation_id="conv-B").action
            is GateAction.DENY
        )


# ---------------------------------------------------------------------------
# explain_denial (Fase 8 — subagent / headless surfaces)
# ---------------------------------------------------------------------------


def test_explain_denial_allow_returns_none() -> None:
    svc = PermissionService()
    assert (
        svc.explain_denial(
            tool_name="calendar_list",
            args={},
            tool_def=None,
            conversation_id="c1",
            mode=PermissionMode.AUTOPILOT,
        )
        is None
    )


def test_explain_denial_needs_confirmation_is_clean_denial() -> None:
    """A confirmation verdict is a denial on surfaces with no user to ask."""
    svc = PermissionService()
    tool_def = ToolDefinition(
        name="danger_tool",
        description="Confirmation-gated test tool",
        requires_confirmation=True,
        risk_level="dangerous",
    )
    message = svc.explain_denial(
        tool_name="danger_tool",
        args={},
        tool_def=tool_def,
        conversation_id="c1",
        mode=PermissionMode.STRICT,
    )
    assert message is not None
    assert "confirmation" in message


def test_explain_denial_forbidden_is_denied_with_reason() -> None:
    svc = PermissionService()
    tool_def = ToolDefinition(
        name="forbidden_tool",
        description="Forbidden test tool",
        risk_level="forbidden",
    )
    message = svc.explain_denial(
        tool_name="forbidden_tool",
        args={},
        tool_def=tool_def,
        conversation_id="c1",
        mode=PermissionMode.AUTOPILOT,
    )
    assert message is not None
    assert "denied" in message


def test_explain_denial_none_mode_falls_back_to_strict() -> None:
    svc = PermissionService()
    tool_def = ToolDefinition(
        name="danger_tool",
        description="Confirmation-gated test tool",
        requires_confirmation=True,
        risk_level="dangerous",
    )
    # None mode is coerced to STRICT (fail-conservative) → clean denial.
    message = svc.explain_denial(
        tool_name="danger_tool",
        args={},
        tool_def=tool_def,
        conversation_id="c1",
        mode=None,
    )
    assert message is not None
