"""Permission gating of the app_command kernel tool (Fase 7, spec §7).

The ``ui_command`` capability marks a tool whose EFFECTIVE capability is
per-call: the invoked command's manifest tag, resolved via the injected
``command_capability_provider``. Matrix under test (spec §7):

* navigation/read → ALLOW in every tier, ``plan`` included;
* mutate/destructive → DENY in ``plan``;
* strict → CONFIRM for mutate/destructive;
* auto_edits → ALLOW mutate, CONFIRM destructive;
* autopilot → ALLOW;
* unknown command / no manifest → treated as destructive (fail-conservative).
"""

from __future__ import annotations

import pytest

from backend.core.plugin_models import ToolDefinition
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_rules import RuleEffect
from backend.services.permission_service import GateAction, PermissionService

_CAPS = {
    "view.switch": "navigation",
    "settings.get": "read",
    "conversation.new": "mutate",
    "conversation.delete": "destructive",
}

APP_COMMAND = ToolDefinition(
    name="app_command",
    description="Command Layer tool",
    parameters={"type": "object", "properties": {"name": {"type": "string"}}},
    capabilities=("ui_command",),
)


def _service() -> PermissionService:
    return PermissionService(command_capability_provider=_CAPS.get)


def _decide(
    service: PermissionService, command: str, mode: PermissionMode,
) -> GateAction:
    return service.decide(
        tool_name="app_command",
        args={"name": command},
        tool_def=APP_COMMAND,
        conversation_id="c1",
        mode=mode,
    ).action


@pytest.mark.parametrize("mode", list(PermissionMode))
@pytest.mark.parametrize("command", ["view.switch", "settings.get"])
def test_navigation_and_read_allowed_everywhere(
    mode: PermissionMode, command: str,
) -> None:
    assert _decide(_service(), command, mode) is GateAction.ALLOW


@pytest.mark.parametrize("command", ["conversation.new", "conversation.delete"])
def test_mutate_and_destructive_denied_in_plan(command: str) -> None:
    assert _decide(_service(), command, PermissionMode.PLAN) is GateAction.DENY


@pytest.mark.parametrize("command", ["conversation.new", "conversation.delete"])
def test_mutate_and_destructive_confirm_in_strict(command: str) -> None:
    assert (
        _decide(_service(), command, PermissionMode.STRICT)
        is GateAction.NEEDS_CONFIRMATION
    )


def test_auto_edits_allows_mutate_confirms_destructive() -> None:
    service = _service()
    assert (
        _decide(service, "conversation.new", PermissionMode.AUTO_EDITS)
        is GateAction.ALLOW
    )
    assert (
        _decide(service, "conversation.delete", PermissionMode.AUTO_EDITS)
        is GateAction.NEEDS_CONFIRMATION
    )


def test_autopilot_allows_all() -> None:
    service = _service()
    for command in _CAPS:
        assert _decide(service, command, PermissionMode.AUTOPILOT) is GateAction.ALLOW


def test_unknown_command_is_fail_conservative() -> None:
    service = _service()
    assert _decide(service, "ghost.cmd", PermissionMode.PLAN) is GateAction.DENY
    assert (
        _decide(service, "ghost.cmd", PermissionMode.STRICT)
        is GateAction.NEEDS_CONFIRMATION
    )
    assert _decide(service, "ghost.cmd", PermissionMode.AUTOPILOT) is GateAction.ALLOW


def test_no_provider_is_fail_conservative() -> None:
    service = PermissionService()
    assert (
        _decide(service, "view.switch", PermissionMode.STRICT)
        is GateAction.NEEDS_CONFIRMATION
    )


def test_rules_and_grants_still_apply() -> None:
    deny = PermissionService(
        command_capability_provider=_CAPS.get,
        rule_provider=lambda conv, tool: RuleEffect.DENY,
    )
    assert _decide(deny, "view.switch", PermissionMode.AUTOPILOT) is GateAction.DENY

    ask = PermissionService(
        command_capability_provider=_CAPS.get,
        rule_provider=lambda conv, tool: RuleEffect.ASK,
    )
    assert (
        _decide(ask, "conversation.new", PermissionMode.AUTOPILOT)
        is GateAction.NEEDS_CONFIRMATION
    )

    granted = _service()
    granted.grant("c1", "app_command")
    assert (
        _decide(granted, "conversation.delete", PermissionMode.STRICT)
        is GateAction.ALLOW
    )


def test_plan_deny_beats_grants_and_allow_rules() -> None:
    """Plan mode read-only stance holds even against grants/allow rules.

    Mirrors the documented fs invariant (decide() step 5): grants do not
    reopen mutations in plan mode.
    """
    granted = _service()
    granted.grant("c1", "app_command")
    assert _decide(granted, "conversation.new", PermissionMode.PLAN) is GateAction.DENY

    allow_rule = PermissionService(
        command_capability_provider=_CAPS.get,
        rule_provider=lambda conv, tool: RuleEffect.ALLOW,
    )
    assert (
        _decide(allow_rule, "conversation.delete", PermissionMode.PLAN)
        is GateAction.DENY
    )


def test_ask_rule_never_prompts_for_navigation_and_read() -> None:
    """Reads never prompt (any tier) — mirrors the fs step-6 invariant."""
    ask = PermissionService(
        command_capability_provider=_CAPS.get,
        rule_provider=lambda conv, tool: RuleEffect.ASK,
    )
    assert _decide(ask, "view.switch", PermissionMode.STRICT) is GateAction.ALLOW
    assert _decide(ask, "settings.get", PermissionMode.STRICT) is GateAction.ALLOW


def test_crafted_args_are_fail_conservative() -> None:
    """Missing or non-string ``name`` resolves to no capability → destructive."""
    service = _service()
    for crafted in ({}, {"name": {"nested": "dict"}}, {"name": 42}):
        decision = service.decide(
            tool_name="app_command",
            args=crafted,
            tool_def=APP_COMMAND,
            conversation_id="c1",
            mode=PermissionMode.STRICT,
        )
        assert decision.action is GateAction.NEEDS_CONFIRMATION


def test_hybrid_ui_command_with_fs_caps_keeps_scope_confinement() -> None:
    """ui_command + fs/exec capability must NOT skip the fs guard (2-bis).

    A hybrid falls through to scope confinement: with no scope set, an
    fs-tagged tool is denied (no_scope breaker), never gated by the §7
    matrix.
    """
    hybrid = ToolDefinition(
        name="sneaky_tool",
        description="Hybrid tool trying to ride the ui_command branch",
        parameters={"type": "object", "properties": {"name": {"type": "string"}}},
        capabilities=("ui_command", "fs_write"),
        path_args=("path",),
    )
    service = PermissionService(
        command_capability_provider=lambda name: "navigation",
        scope_provider=lambda conv: [],
    )
    decision = service.decide(
        tool_name="sneaky_tool",
        args={"name": "view.switch", "path": "C:/anywhere"},
        tool_def=hybrid,
        conversation_id="c1",
        mode=PermissionMode.AUTOPILOT,
    )
    assert decision.action is GateAction.DENY
