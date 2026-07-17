"""Test ``PermissionServiceAdapter`` — mode per-call + mapping GateAction.

Servizi di piattaforma mockati con ``MagicMock`` (``PermissionService``,
``PermissionModeService``, ``ToolRegistry``): l'adapter è testato in
isolamento, senza costruire i servizi reali.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services.agent import ports
from backend.services.agent.adapters.permission import PermissionServiceAdapter
from backend.services.agent.models import ToolInvocation
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_service import GateAction as PlatformGateAction
from backend.services.permission_service import GateDecision, PermissionOutcome


def _call(name: str = "fs_read_file", args: dict | None = None) -> ToolInvocation:
    return ToolInvocation(call_id="call_1", name=name, args=args or {}, raw_args="{}")


def _make_adapter(
    *, decision: GateDecision, tool_def: object | None = None,
) -> tuple[PermissionServiceAdapter, MagicMock, MagicMock, MagicMock]:
    permission_service = MagicMock()
    permission_service.decide.return_value = decision
    mode_service = MagicMock()
    mode_service.get_mode.return_value = PermissionMode.STRICT
    tool_registry = MagicMock()
    tool_registry.get_tool_definition.return_value = tool_def
    adapter = PermissionServiceAdapter(
        permission_service=permission_service,
        mode_service=mode_service,
        tool_registry=tool_registry,
        conversation_id="conv-1",
    )
    return adapter, permission_service, mode_service, tool_registry


async def test_mode_and_tool_def_resolved_on_every_call() -> None:
    adapter, permission_service, mode_service, tool_registry = _make_adapter(
        decision=GateDecision.allow(),
    )
    call = _call()

    await adapter.decide(call, conversation_id="conv-1")
    await adapter.decide(call, conversation_id="conv-1")

    assert mode_service.get_mode.call_count == 2
    assert tool_registry.get_tool_definition.call_count == 2
    assert permission_service.decide.call_count == 2


async def test_decide_passes_resolved_mode_and_tool_def_through() -> None:
    adapter, permission_service, mode_service, tool_registry = _make_adapter(
        decision=GateDecision.allow(),
    )
    mode_service.get_mode.return_value = PermissionMode.AUTOPILOT
    call = _call(name="terminal_exec", args={"cmd": "ls"})

    await adapter.decide(call, conversation_id="conv-42")

    permission_service.decide.assert_called_once_with(
        tool_name="terminal_exec",
        args={"cmd": "ls"},
        tool_def=tool_registry.get_tool_definition.return_value,
        conversation_id="conv-42",
        mode=PermissionMode.AUTOPILOT,
    )


@pytest.mark.parametrize(
    ("platform_action", "expected_action"),
    [
        (PlatformGateAction.ALLOW, ports.GateAction.EXECUTE),
        (PlatformGateAction.DENY, ports.GateAction.DENY),
        (PlatformGateAction.NEEDS_CONFIRMATION, ports.GateAction.CONFIRM),
    ],
)
async def test_gate_action_mapping(
    platform_action: PlatformGateAction, expected_action: ports.GateAction,
) -> None:
    decision = GateDecision(
        action=platform_action, outcome=PermissionOutcome.DENY_SCOPE, reason="outside_scope",
    )
    adapter, *_ = _make_adapter(decision=decision)

    verdict = await adapter.decide(_call(), conversation_id="conv-1")

    assert verdict.action == expected_action
    assert verdict.outcome == "deny_scope"
    assert verdict.reason == "outside_scope"


async def test_verdict_carries_risk_level_and_description_from_tool_def() -> None:
    tool_def = MagicMock(risk_level="dangerous", description="borra tutto")
    adapter, *_ = _make_adapter(decision=GateDecision.allow(), tool_def=tool_def)

    verdict = await adapter.decide(_call(), conversation_id="conv-1")

    assert verdict.risk_level == "dangerous"
    assert verdict.description == "borra tutto"


async def test_verdict_risk_level_and_description_none_when_tool_unknown() -> None:
    adapter, *_ = _make_adapter(decision=GateDecision.allow(), tool_def=None)

    verdict = await adapter.decide(_call(name="unknown_tool"), conversation_id="conv-1")

    assert verdict.risk_level is None
    assert verdict.description is None


async def test_decide_passes_resolved_namespaced_name_for_bare_tool_call() -> None:
    """Un nome "nudo" emesso dal modello (es. ``remember``) deve arrivare a
    ``PermissionService.decide`` come nome namespaced risolto (``memory_remember``),
    non come nome nudo — altrimenti rules/grants per-conversazione keyed sul nome
    namespaced non fanno mai match.
    """
    tool_def = MagicMock(risk_level="safe", description="ricorda un fatto")
    permission_service = MagicMock()
    permission_service.decide.return_value = GateDecision.allow()
    mode_service = MagicMock()
    mode_service.get_mode.return_value = PermissionMode.STRICT
    tool_registry = MagicMock()

    def get_tool_definition(name: str) -> object | None:
        if name == "memory_remember":
            return tool_def
        return None

    tool_registry.get_tool_definition.side_effect = get_tool_definition
    tool_registry.get_all_tools.return_value = [
        {"function": {"name": "memory_remember"}},
        {"function": {"name": "other_tool"}},
    ]
    adapter = PermissionServiceAdapter(
        permission_service=permission_service,
        mode_service=mode_service,
        tool_registry=tool_registry,
        conversation_id="conv-1",
    )
    call = _call(name="remember", args={"fact": "x"})

    await adapter.decide(call, conversation_id="conv-1")

    permission_service.decide.assert_called_once_with(
        tool_name="memory_remember",
        args={"fact": "x"},
        tool_def=tool_def,
        conversation_id="conv-1",
        mode=PermissionMode.STRICT,
    )


async def test_decide_falls_back_to_bare_name_when_unresolvable() -> None:
    """Nome nudo ambiguo o sconosciuto -> fallback al nome nudo originale (nessuna
    regressione rispetto al comportamento pre-fix per i nomi non risolvibili).
    """
    permission_service = MagicMock()
    permission_service.decide.return_value = GateDecision.allow()
    mode_service = MagicMock()
    mode_service.get_mode.return_value = PermissionMode.STRICT
    tool_registry = MagicMock()
    tool_registry.get_tool_definition.return_value = None
    tool_registry.get_all_tools.return_value = []
    adapter = PermissionServiceAdapter(
        permission_service=permission_service,
        mode_service=mode_service,
        tool_registry=tool_registry,
        conversation_id="conv-1",
    )
    call = _call(name="totally_unknown", args={})

    await adapter.decide(call, conversation_id="conv-1")

    permission_service.decide.assert_called_once_with(
        tool_name="totally_unknown",
        args={},
        tool_def=None,
        conversation_id="conv-1",
        mode=PermissionMode.STRICT,
    )
