"""Tests for the central PermissionService (Fase 2, foundation D).

Covers the three responsibilities the turn engine delegates: risk policy
(forbidden), by-construction filesystem scope confinement (deny-by-default
outside the conversation scope), and per-conversation grants.
"""

from __future__ import annotations

from pathlib import Path

from backend.core.plugin_models import ToolDefinition
from backend.services.permission_service import (
    PermissionDecision,
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


def _evaluate(
    svc: PermissionService,
    tool_def: ToolDefinition,
    args: dict[str, object] | None = None,
    *,
    conversation_id: str = _CONV,
) -> PermissionDecision:
    return svc.evaluate(
        tool_name=tool_def.name,
        args=args or {},
        tool_def=tool_def,
        conversation_id=conversation_id,
    )


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------


class TestRiskPolicy:
    def test_forbidden_tool_is_denied(self) -> None:
        svc = PermissionService()
        decision = _evaluate(svc, _tool("danger", risk_level="forbidden"))
        assert decision.allowed is False
        assert decision.outcome is PermissionOutcome.DENY_FORBIDDEN
        assert decision.reason == "forbidden_tool"

    def test_non_forbidden_levels_allowed_without_scope(self) -> None:
        svc = PermissionService()
        for level in ("safe", "medium", "dangerous"):
            decision = _evaluate(svc, _tool(f"t_{level}", risk_level=level))
            assert decision.allowed is True, level
            assert decision.outcome is PermissionOutcome.ALLOW

    def test_unknown_tool_def_allowed(self) -> None:
        """``tool_def=None`` is allowed here (the registry rejects truly
        unknown tools at execution time)."""
        svc = PermissionService()
        decision = svc.evaluate(
            tool_name="mystery", args={}, tool_def=None, conversation_id=_CONV,
        )
        assert decision.allowed is True

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
    def test_no_scope_provider_means_no_confinement(self, tmp_path: Path) -> None:
        """Fase 2 default: no scope provider ⇒ fs tools run unconfined."""
        svc = PermissionService()  # scope_provider=None
        tool = _tool("fs_write_file", capabilities=("fs_write",), path_args=("path",))
        outside = str(tmp_path / "anywhere" / "f.txt")
        assert _evaluate(svc, tool, {"path": outside}).allowed is True

    def test_path_inside_scope_allowed(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("fs_write_file", capabilities=("fs_write",), path_args=("path",))
        inside = str(scope / "sub" / "note.txt")
        decision = _evaluate(svc, tool, {"path": inside})
        assert decision.allowed is True

    def test_path_outside_scope_denied_by_default(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        outside = tmp_path / "secrets"
        outside.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("fs_read_file", capabilities=("fs_read",), path_args=("path",))
        decision = _evaluate(svc, tool, {"path": str(outside / "passwords.txt")})
        assert decision.allowed is False
        assert decision.outcome is PermissionOutcome.DENY_SCOPE
        assert decision.reason == "outside_scope"

    def test_traversal_cannot_escape_scope(self, tmp_path: Path) -> None:
        """A ``..`` traversal out of the scope resolves and is denied."""
        scope = tmp_path / "workspace"
        scope.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("fs_read_file", capabilities=("fs_read",), path_args=("path",))
        sneaky = str(scope / ".." / "etc" / "shadow")
        assert _evaluate(svc, tool, {"path": sneaky}).allowed is False

    def test_non_fs_tool_not_confined(self, tmp_path: Path) -> None:
        """A tool without an fs_* capability is never path-confined, even
        when its args carry an out-of-scope path."""
        scope = tmp_path / "workspace"
        scope.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("web_fetch", path_args=("path",))  # no fs capability
        outside = str(tmp_path / "elsewhere" / "x")
        assert _evaluate(svc, tool, {"path": outside}).allowed is True

    def test_fs_tool_without_path_arg_present_allowed(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("fs_list", capabilities=("fs_read",), path_args=("path",))
        # No "path" key supplied → nothing to confine → allowed.
        assert _evaluate(svc, tool, {}).allowed is True

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
        decision = _evaluate(svc, tool, {"path": str(blocked / "key.pem")})
        assert decision.allowed is False
        assert decision.outcome is PermissionOutcome.DENY_SCOPE

    def test_multiple_scope_roots(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [a, b])
        tool = _tool("fs_read_file", capabilities=("fs_read",), path_args=("path",))
        assert _evaluate(svc, tool, {"path": str(b / "f")}).allowed is True


# ---------------------------------------------------------------------------
# Per-conversation grants
# ---------------------------------------------------------------------------


class TestGrants:
    def test_grant_bypasses_scope_denial(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        outside = str(tmp_path / "elsewhere" / "f.txt")
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("fs_write_file", capabilities=("fs_write",), path_args=("path",))

        assert _evaluate(svc, tool, {"path": outside}).allowed is False
        svc.grant(_CONV, "fs_write_file")
        assert _evaluate(svc, tool, {"path": outside}).allowed is True

    def test_grant_is_scoped_per_conversation(self, tmp_path: Path) -> None:
        scope = tmp_path / "workspace"
        scope.mkdir()
        outside = str(tmp_path / "elsewhere" / "f.txt")
        svc = PermissionService(scope_provider=lambda _c: [scope])
        tool = _tool("fs_write_file", capabilities=("fs_write",), path_args=("path",))

        svc.grant("conv-A", "fs_write_file")
        assert _evaluate(svc, tool, {"path": outside}, conversation_id="conv-A").allowed
        # Other conversation is unaffected.
        assert not _evaluate(
            svc, tool, {"path": outside}, conversation_id="conv-B",
        ).allowed

    def test_revoke_and_clear(self) -> None:
        svc = PermissionService()
        svc.grant(_CONV, "k")
        assert svc.is_granted(_CONV, "k") is True
        svc.revoke(_CONV, "k")
        assert svc.is_granted(_CONV, "k") is False
        svc.grant(_CONV, "k2")
        svc.clear_grants(_CONV)
        assert svc.is_granted(_CONV, "k2") is False

    def test_forbidden_beats_grant(self, tmp_path: Path) -> None:
        """A grant never resurrects a forbidden tool."""
        svc = PermissionService(scope_provider=lambda _c: [tmp_path])
        svc.grant(_CONV, "danger")
        decision = _evaluate(svc, _tool("danger", risk_level="forbidden"))
        assert decision.allowed is False
        assert decision.outcome is PermissionOutcome.DENY_FORBIDDEN
