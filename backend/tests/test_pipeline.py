"""Tests for the tool-call middleware pipeline (Fase 2, foundation C).

Each middleware is exercised in isolation, plus the chain ordering /
short-circuit semantics and the two-phase ``ToolPipeline.gate`` / ``execute``
split. No DB, no WebSocket — just the in-memory contracts.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult
from backend.services.permission_service import PermissionService
from backend.services.turn.pipeline import (
    ConfirmationMiddleware,
    DedupMiddleware,
    Disposition,
    ExecuteMiddleware,
    InteractionMiddleware,
    PermissionMiddleware,
    ToolCall,
    ToolOutcome,
    ToolPipeline,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeSink:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, event: dict) -> None:
        self.sent.append(event)


class _FakeChannel:
    def __init__(
        self,
        *,
        confirm: bool | None = None,
        client_reply: dict | None = None,
        connected: bool = True,
        cancelled: bool = False,
    ) -> None:
        self.requests: list[tuple[str, dict, str]] = []
        self._confirm = confirm
        self._client_reply = client_reply
        self._connected = connected
        self._cancelled = cancelled

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    async def request(
        self, kind: str, payload: dict, *, execution_id: str,
        timeout_s: float, cancel_event: asyncio.Event | None = None,
    ) -> dict | None:
        self.requests.append((kind, payload, execution_id))
        if kind == "tool_confirmation":
            return None if self._confirm is None else {"approved": self._confirm}
        if kind == "client_tool_call":
            return self._client_reply
        return None


class _FakeRegistry:
    def __init__(
        self, result: ToolResult | None = None, raises: Exception | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._result = result if result is not None else ToolResult.ok("ok")
        self._raises = raises

    async def execute_tool(self, name: str, args: dict, context: object) -> ToolResult:
        self.calls.append(name)
        if self._raises is not None:
            raise self._raises
        return self._result


def _tool(
    name: str = "t",
    *,
    risk_level: str = "safe",
    requires_confirmation: bool = False,
    client_execution: bool = False,
    capabilities: tuple[str, ...] = (),
    path_args: tuple[str, ...] = (),
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"tool {name}",
        risk_level=risk_level,  # type: ignore[arg-type]
        requires_confirmation=requires_confirmation,
        client_execution=client_execution,
        capabilities=capabilities,
        path_args=path_args,
    )


def _call(
    *,
    tool_def: ToolDefinition | None = None,
    tool_name: str = "t",
    args: dict | None = None,
    dedup_key: str = "k",
    is_client: bool = False,
) -> ToolCall:
    return ToolCall(
        tc_id="call_1",
        tool_name=tool_name,
        args=args or {},
        tool_def=tool_def,
        exec_id="exec_1",
        conversation_id="conv-1",
        context=ExecutionContext(
            session_id="ip", conversation_id="conv-1", execution_id="exec_1",
        ),
        dedup_key=dedup_key,
        is_client=is_client,
    )


async def _proceed(call: ToolCall) -> ToolOutcome:
    """A terminal that signals the call passed (server execute)."""
    return ToolOutcome(call, Disposition.EXECUTE)


# ---------------------------------------------------------------------------
# DedupMiddleware
# ---------------------------------------------------------------------------


class TestDedup:
    @pytest.mark.asyncio
    async def test_duplicate_server_call_short_circuits(self) -> None:
        seen = {"k"}
        outcome = await DedupMiddleware(seen).handle(_call(), _proceed)
        assert outcome.disposition is Disposition.DEDUPED

    @pytest.mark.asyncio
    async def test_unseen_call_proceeds(self) -> None:
        outcome = await DedupMiddleware(set()).handle(_call(), _proceed)
        assert outcome.disposition is Disposition.EXECUTE

    @pytest.mark.asyncio
    async def test_client_call_never_deduped(self) -> None:
        seen = {"k"}
        outcome = await DedupMiddleware(seen).handle(
            _call(is_client=True), _proceed,
        )
        assert outcome.disposition is Disposition.EXECUTE


# ---------------------------------------------------------------------------
# PermissionMiddleware
# ---------------------------------------------------------------------------


class TestPermission:
    @pytest.mark.asyncio
    async def test_forbidden_blocked_with_audit(self) -> None:
        mw = PermissionMiddleware(PermissionService())
        call = _call(tool_def=_tool(risk_level="forbidden"))
        outcome = await mw.handle(call, _proceed)
        assert outcome.disposition is Disposition.FORBIDDEN
        assert call.audit_decision is not None
        assert call.audit_decision.approved is False
        assert call.audit_decision.reason == "forbidden_tool"
        assert call.audit_decision.risk_level == "forbidden"

    @pytest.mark.asyncio
    async def test_allowed_proceeds(self) -> None:
        mw = PermissionMiddleware(PermissionService())
        outcome = await mw.handle(_call(tool_def=_tool()), _proceed)
        assert outcome.disposition is Disposition.EXECUTE

    @pytest.mark.asyncio
    async def test_out_of_scope_denied(self, tmp_path) -> None:
        scope = tmp_path / "ws"
        scope.mkdir()
        svc = PermissionService(scope_provider=lambda _c: [scope])
        mw = PermissionMiddleware(svc)
        tool = _tool(capabilities=("fs_write",), path_args=("path",))
        call = _call(tool_def=tool, args={"path": str(tmp_path / "out" / "f")})
        outcome = await mw.handle(call, _proceed)
        assert outcome.disposition is Disposition.SCOPE_DENIED
        assert outcome.reason == "outside_scope"


# ---------------------------------------------------------------------------
# ConfirmationMiddleware
# ---------------------------------------------------------------------------


def _confirm_mw(channel: _FakeChannel, *, enabled: bool) -> ConfirmationMiddleware:
    return ConfirmationMiddleware(
        channel=channel,
        permission_service=PermissionService(),
        confirmations_enabled=enabled,
        confirmation_timeout_s=5,
        reasoning="why",
        cancel_event=None,
    )


class TestConfirmation:
    @pytest.mark.asyncio
    async def test_no_confirmation_required_passes(self) -> None:
        ch = _FakeChannel()
        outcome = await _confirm_mw(ch, enabled=True).handle(
            _call(tool_def=_tool()), _proceed,
        )
        assert outcome.disposition is Disposition.EXECUTE
        assert ch.requests == []  # no round-trip

    @pytest.mark.asyncio
    async def test_approved_passes_with_audit(self) -> None:
        ch = _FakeChannel(confirm=True)
        call = _call(tool_def=_tool(requires_confirmation=True, risk_level="dangerous"))
        outcome = await _confirm_mw(ch, enabled=True).handle(call, _proceed)
        assert outcome.disposition is Disposition.EXECUTE
        assert len(ch.requests) == 1
        assert call.audit_decision is not None
        assert call.audit_decision.approved is True
        assert call.audit_decision.reason is None

    @pytest.mark.asyncio
    async def test_rejected_short_circuits_with_audit(self) -> None:
        ch = _FakeChannel(confirm=False)
        call = _call(tool_def=_tool(requires_confirmation=True, risk_level="dangerous"))
        outcome = await _confirm_mw(ch, enabled=True).handle(call, _proceed)
        assert outcome.disposition is Disposition.REJECTED
        assert call.audit_decision is not None
        assert call.audit_decision.approved is False
        assert call.audit_decision.reason == "user_rejected"

    @pytest.mark.asyncio
    async def test_timeout_is_rejection(self) -> None:
        ch = _FakeChannel(confirm=None)  # request returns None
        call = _call(tool_def=_tool(requires_confirmation=True))
        outcome = await _confirm_mw(ch, enabled=True).handle(call, _proceed)
        assert outcome.disposition is Disposition.REJECTED

    @pytest.mark.asyncio
    async def test_disabled_auto_approves_without_roundtrip(self) -> None:
        ch = _FakeChannel()
        call = _call(tool_def=_tool(requires_confirmation=True, risk_level="medium"))
        outcome = await _confirm_mw(ch, enabled=False).handle(call, _proceed)
        assert outcome.disposition is Disposition.EXECUTE
        assert ch.requests == []  # auto-approved, no prompt
        assert call.audit_decision is not None
        assert call.audit_decision.approved is True


# ---------------------------------------------------------------------------
# InteractionMiddleware
# ---------------------------------------------------------------------------


def _interaction_mw(sink: _FakeSink, channel: _FakeChannel, seen: set[str]):
    return InteractionMiddleware(
        sink=sink, channel=channel, seen=seen,
        tool_exec_timeout=5.0, cancel_event=None,
    )


class TestInteraction:
    @pytest.mark.asyncio
    async def test_server_tool_emits_start_marks_seen_and_proceeds(self) -> None:
        sink, ch, seen = _FakeSink(), _FakeChannel(), set()
        outcome = await _interaction_mw(sink, ch, seen).handle(
            _call(tool_def=_tool()), _proceed,
        )
        assert outcome.disposition is Disposition.EXECUTE
        assert [e["type"] for e in sink.sent] == ["tool_execution_start"]
        assert "k" in seen
        assert ch.requests == []  # no client round-trip for server tools

    @pytest.mark.asyncio
    async def test_client_tool_round_trips(self) -> None:
        sink, seen = _FakeSink(), set()
        ch = _FakeChannel(client_reply={"success": True, "result": {"n": 1}})
        call = _call(tool_def=_tool(client_execution=True))
        outcome = await _interaction_mw(sink, ch, seen).handle(call, _proceed)
        assert outcome.disposition is Disposition.CLIENT_EXECUTED
        assert outcome.result is not None and outcome.result.success is True
        assert ch.requests and ch.requests[0][0] == "client_tool_call"
        # start emitted before the round-trip; call marked seen.
        assert sink.sent[0]["type"] == "tool_execution_start"
        assert "k" in seen

    @pytest.mark.asyncio
    async def test_client_tool_failure_is_error_result(self) -> None:
        sink, seen = _FakeSink(), set()
        ch = _FakeChannel(client_reply={"success": False, "error": "boom"})
        call = _call(tool_def=_tool(client_execution=True))
        outcome = await _interaction_mw(sink, ch, seen).handle(call, _proceed)
        assert outcome.disposition is Disposition.CLIENT_EXECUTED
        assert outcome.result is not None and outcome.result.success is False


# ---------------------------------------------------------------------------
# ExecuteMiddleware
# ---------------------------------------------------------------------------


class TestExecute:
    @pytest.mark.asyncio
    async def test_runs_tool_and_returns_result(self) -> None:
        reg = _FakeRegistry(result=ToolResult.ok("hello"))
        mw = ExecuteMiddleware(tool_registry=reg, sink=_FakeSink())
        outcome = await mw.handle(_call(tool_def=_tool()), _proceed)
        assert outcome.disposition is Disposition.EXECUTED
        assert outcome.result is not None and outcome.result.content == "hello"
        assert reg.calls == ["t"]


# ---------------------------------------------------------------------------
# ToolPipeline — ordering / short-circuit / two-phase
# ---------------------------------------------------------------------------


class _Recorder:
    """Middleware that records its tag then delegates (no short-circuit)."""

    def __init__(self, tag: str, log: list[str]) -> None:
        self._tag = tag
        self._log = log

    async def handle(self, call: ToolCall, nxt) -> ToolOutcome:
        self._log.append(self._tag)
        return await nxt(call)


class _Stopper:
    """Middleware that short-circuits with a terminal outcome."""

    def __init__(self, tag: str, log: list[str]) -> None:
        self._tag = tag
        self._log = log

    async def handle(self, call: ToolCall, nxt) -> ToolOutcome:
        self._log.append(self._tag)
        return ToolOutcome(call, Disposition.DEDUPED)


class TestPipelineOrdering:
    @pytest.mark.asyncio
    async def test_gate_runs_middlewares_in_order(self) -> None:
        log: list[str] = []
        pipe = ToolPipeline(
            [_Recorder("a", log), _Recorder("b", log), _Recorder("c", log)],
            ExecuteMiddleware(tool_registry=_FakeRegistry(), sink=_FakeSink()),
        )
        outcome = await pipe.gate(_call(tool_def=_tool()))
        assert log == ["a", "b", "c"]
        assert outcome.disposition is Disposition.EXECUTE  # gate terminal

    @pytest.mark.asyncio
    async def test_short_circuit_skips_downstream(self) -> None:
        log: list[str] = []
        pipe = ToolPipeline(
            [_Recorder("a", log), _Stopper("b", log), _Recorder("c", log)],
            ExecuteMiddleware(tool_registry=_FakeRegistry(), sink=_FakeSink()),
        )
        outcome = await pipe.gate(_call())
        assert log == ["a", "b"]  # "c" never runs
        assert outcome.disposition is Disposition.DEDUPED

    @pytest.mark.asyncio
    async def test_execute_phase_runs_execute_middleware(self) -> None:
        reg = _FakeRegistry(result=ToolResult.ok("done"))
        pipe = ToolPipeline([], ExecuteMiddleware(tool_registry=reg, sink=_FakeSink()))
        outcome = await pipe.execute(_call(tool_def=_tool()))
        assert outcome.disposition is Disposition.EXECUTED
        assert reg.calls == ["t"]

    @pytest.mark.asyncio
    async def test_full_gate_chain_passes_clean_server_tool(self) -> None:
        """Dedup → Permission → Confirmation → Interaction all pass ⇒ EXECUTE."""
        sink, seen = _FakeSink(), set()
        ch = _FakeChannel()
        svc = PermissionService()
        pipe = ToolPipeline(
            [
                DedupMiddleware(seen),
                PermissionMiddleware(svc),
                _confirm_mw(ch, enabled=True),
                _interaction_mw(sink, ch, seen),
            ],
            ExecuteMiddleware(tool_registry=_FakeRegistry(), sink=sink),
        )
        outcome = await pipe.gate(_call(tool_def=_tool()))
        assert outcome.disposition is Disposition.EXECUTE
        assert "k" in seen
        assert [e["type"] for e in sink.sent] == ["tool_execution_start"]
