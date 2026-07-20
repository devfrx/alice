"""Test ``PermissionServiceAdapter`` — mode per-call + mapping GateAction.

Servizi di piattaforma mockati con ``MagicMock`` (``PermissionService``,
``PermissionModeService``, ``ToolRegistry``): l'adapter è testato in
isolamento, senza costruire i servizi reali.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.plugin_models import McpToolMeta
from backend.services.agent import ports
from backend.services.agent.adapters.permission import PermissionServiceAdapter
from backend.services.agent.models import ToolInvocation
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_rules import RuleEffect
from backend.services.permission_service import GateAction as PlatformGateAction
from backend.services.permission_service import GateDecision, PermissionOutcome


def _call(name: str = "fs_read_file", args: dict | None = None) -> ToolInvocation:
    return ToolInvocation(call_id="call_1", name=name, args=args or {}, raw_args="{}")


def _tool_def(
    *,
    risk_level: str = "safe",
    description: str = "",
    mcp: McpToolMeta | None = None,
) -> MagicMock:
    """``ToolDefinition`` finta con default sicuri (``mcp=None`` esplicito).

    Un ``MagicMock`` nudo auto-crea ``.mcp`` non-None e produrrebbe un
    ``tool_meta`` MCP spazzatura nel verdetto: passare da questa factory
    rende il default sicuro impossibile da dimenticare.
    """
    return MagicMock(risk_level=risk_level, description=description, mcp=mcp)


def _rule_service() -> MagicMock:
    rule_service = MagicMock()
    rule_service.add_rule = AsyncMock()
    return rule_service


def _make_adapter(
    *, decision: GateDecision, tool_def: object | None = None,
) -> tuple[PermissionServiceAdapter, MagicMock, MagicMock, MagicMock, MagicMock]:
    permission_service = MagicMock()
    permission_service.decide.return_value = decision
    mode_service = MagicMock()
    mode_service.get_mode.return_value = PermissionMode.STRICT
    tool_registry = MagicMock()
    tool_registry.get_tool_definition.return_value = tool_def
    rule_service = _rule_service()
    adapter = PermissionServiceAdapter(
        permission_service=permission_service,
        mode_service=mode_service,
        tool_registry=tool_registry,
        rule_service=rule_service,
        conversation_id="conv-1",
    )
    return adapter, permission_service, mode_service, tool_registry, rule_service


async def test_mode_and_tool_def_resolved_on_every_call() -> None:
    adapter, permission_service, mode_service, tool_registry, _ = _make_adapter(
        decision=GateDecision.allow(),
    )
    call = _call()

    await adapter.decide(call, conversation_id="conv-1")
    await adapter.decide(call, conversation_id="conv-1")

    assert mode_service.get_mode.call_count == 2
    assert tool_registry.get_tool_definition.call_count == 2
    assert permission_service.decide.call_count == 2


async def test_decide_passes_resolved_mode_and_tool_def_through() -> None:
    adapter, permission_service, mode_service, tool_registry, _ = _make_adapter(
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
    tool_def = _tool_def(risk_level="dangerous", description="borra tutto")
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
    tool_def = _tool_def(description="ricorda un fatto")
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
        rule_service=_rule_service(),
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
        rule_service=_rule_service(),
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


# ---------------------------------------------------------------------------
# tool_meta (Task 2 Fase 2: provenienza del tool nel verdetto del gate)
# ---------------------------------------------------------------------------


async def test_verdict_tool_meta_native() -> None:
    """Tool nativo noto (``mcp=None``) -> ``tool_meta`` con origin ``native``."""
    tool_def = _tool_def(description="legge un file")
    adapter, *_ = _make_adapter(decision=GateDecision.allow(), tool_def=tool_def)

    verdict = await adapter.decide(_call(), conversation_id="conv-1")

    assert verdict.tool_meta is not None
    assert verdict.tool_meta.origin == "native"
    assert verdict.tool_meta.server is None
    assert verdict.tool_meta.annotated is None
    assert verdict.tool_meta.read_only is None
    assert verdict.tool_meta.destructive is None
    assert verdict.tool_meta.trusted is None


async def test_verdict_tool_meta_mcp() -> None:
    """Tool MCP -> la provenienza (``McpToolMeta``) è copiata campo per campo."""
    meta = McpToolMeta(
        server="files", annotated=False, trusted=True, read_only=False, destructive=None,
    )
    tool_def = _tool_def(risk_level="dangerous", description="scrive un file", mcp=meta)
    adapter, *_ = _make_adapter(decision=GateDecision.allow(), tool_def=tool_def)

    verdict = await adapter.decide(_call(name="mcp_files_write"), conversation_id="conv-1")

    assert verdict.tool_meta is not None
    assert verdict.tool_meta.origin == "mcp"
    assert verdict.tool_meta.server == "files"
    assert verdict.tool_meta.annotated is False
    assert verdict.tool_meta.read_only is False
    assert verdict.tool_meta.destructive is None
    assert verdict.tool_meta.trusted is True


async def test_verdict_tool_meta_unknown_tool_is_none() -> None:
    """Tool sconosciuto al registry -> nessuna provenienza (``tool_meta is None``)."""
    adapter, *_ = _make_adapter(decision=GateDecision.allow(), tool_def=None)

    verdict = await adapter.decide(_call(name="unknown_tool"), conversation_id="conv-1")

    assert verdict.tool_meta is None


async def test_verdict_tool_meta_populated_on_deny() -> None:
    """Anche un verdetto DENY porta ``tool_meta`` quando la tool_def è risolta."""
    decision = GateDecision(
        action=PlatformGateAction.DENY,
        outcome=PermissionOutcome.DENY_SCOPE,
        reason="outside_scope",
    )
    tool_def = _tool_def(risk_level="dangerous", description="fuori scope")
    adapter, *_ = _make_adapter(decision=decision, tool_def=tool_def)

    verdict = await adapter.decide(_call(), conversation_id="conv-1")

    assert verdict.action == ports.GateAction.DENY
    assert verdict.tool_meta is not None
    assert verdict.tool_meta.origin == "native"


def test_tool_meta_as_payload_contract() -> None:
    """``as_payload()`` produce ESATTAMENTE le 6 chiavi del contratto wire."""
    meta = ports.ToolMetaInfo(
        origin="mcp", server="files", annotated=True,
        read_only=True, destructive=False, trusted=True,
    )

    assert meta.as_payload() == {
        "origin": "mcp",
        "server": "files",
        "annotated": True,
        "read_only": True,
        "destructive": False,
        "trusted": True,
    }


# ---------------------------------------------------------------------------
# remember_approval (fix smoke Fase 1: persistenza della scelta "ricorda")
# ---------------------------------------------------------------------------


async def test_remember_approval_conversation_creates_conversation_rule() -> None:
    adapter, *_, rule_service = _make_adapter(decision=GateDecision.allow())

    await adapter.remember_approval(
        _call(name="fs_write_file"), conversation_id="conv-9",
        scope=ports.RememberScope.CONVERSATION,
    )

    rule_service.add_rule.assert_awaited_once_with(
        tool_name="fs_write_file", effect=RuleEffect.ALLOW, conversation_id="conv-9",
    )


async def test_remember_approval_persistent_creates_global_rule() -> None:
    adapter, *_, rule_service = _make_adapter(decision=GateDecision.allow())

    await adapter.remember_approval(
        _call(name="fs_write_file"), conversation_id="conv-9",
        scope=ports.RememberScope.PERSISTENT,
    )

    rule_service.add_rule.assert_awaited_once_with(
        tool_name="fs_write_file", effect=RuleEffect.ALLOW, conversation_id=None,
    )


async def test_remember_approval_none_is_noop() -> None:
    adapter, *_, rule_service = _make_adapter(decision=GateDecision.allow())

    await adapter.remember_approval(
        _call(), conversation_id="conv-9", scope=ports.RememberScope.NONE,
    )

    rule_service.add_rule.assert_not_awaited()


async def test_remember_approval_uses_resolved_namespaced_name() -> None:
    """La regola è keyed sul nome NAMESPACED risolto (stessa regola del fix M1
    su ``decide``): una regola su ``remember`` nudo non farebbe mai match."""
    tool_def = _tool_def(description="ricorda un fatto")
    permission_service = MagicMock()
    mode_service = MagicMock()
    tool_registry = MagicMock()
    tool_registry.get_tool_definition.side_effect = (
        lambda name: tool_def if name == "memory_remember" else None
    )
    tool_registry.get_all_tools.return_value = [
        {"function": {"name": "memory_remember"}},
        {"function": {"name": "other_tool"}},
    ]
    rule_service = _rule_service()
    adapter = PermissionServiceAdapter(
        permission_service=permission_service,
        mode_service=mode_service,
        tool_registry=tool_registry,
        rule_service=rule_service,
        conversation_id="conv-1",
    )

    await adapter.remember_approval(
        _call(name="remember", args={"fact": "x"}), conversation_id="conv-1",
        scope=ports.RememberScope.CONVERSATION,
    )

    rule_service.add_rule.assert_awaited_once_with(
        tool_name="memory_remember", effect=RuleEffect.ALLOW, conversation_id="conv-1",
    )


async def test_remember_approval_failure_is_swallowed() -> None:
    """Best-effort: un errore di persistenza della regola NON deve mai far
    fallire la call appena approvata dall'utente (contratto della porta)."""
    adapter, *_, rule_service = _make_adapter(decision=GateDecision.allow())
    rule_service.add_rule = AsyncMock(side_effect=RuntimeError("db boom"))

    await adapter.remember_approval(
        _call(), conversation_id="conv-9", scope=ports.RememberScope.PERSISTENT,
    )  # non solleva
