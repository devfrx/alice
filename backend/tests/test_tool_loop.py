"""Tests for the tool calling loop (Phase 3.8).

Integration-style tests for ``run_tool_loop()`` with mocked WebSocket,
DB session, LLMService, and ToolRegistry.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from backend.services.turn.tool_loop import run_tool_loop
from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult
from backend.db.models import Message

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


# Maps an interaction *kind* to the outbound request frame type the real
# channel emits — mirrored here so ``.sent`` assertions stay meaningful.
_REQ_FRAME_TYPE = {
    "tool_confirmation": "tool_confirmation_required",
    "client_tool_call": "client_tool_call",
    "ask_user": "ask_user_required",
}


class MockWebSocket:
    """Combined sink + interaction channel double for ``run_tool_loop``.

    Records outbound events in :attr:`sent` (sink role) and answers
    interaction requests in-process (channel role): confirmations resolve
    from ``auto_confirm`` and client-tool calls via :meth:`_answer_client`.
    Each request also appends its outbound frame to :attr:`sent`, matching
    what :class:`WebSocketInteractionChannel` puts on the wire.
    """

    def __init__(self, *, auto_confirm: bool | None = None) -> None:
        self.sent: list[dict] = []
        self._auto_confirm = auto_confirm
        self._cancel_event = asyncio.Event()

    # --- sink role ---------------------------------------------------
    async def send(self, event: dict) -> None:
        """Record an outbound event."""
        self.sent.append(event)

    @property
    def is_connected(self) -> bool:
        return True

    # --- channel role ------------------------------------------------
    @property
    def connected(self) -> bool:
        return True

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def cancel_event(self) -> asyncio.Event:
        return self._cancel_event

    def begin_turn(self) -> asyncio.Event:
        self._cancel_event = asyncio.Event()
        return self._cancel_event

    async def request(
        self,
        kind: str,
        payload: dict,
        *,
        execution_id: str,
        timeout_s: float,
        cancel_event: asyncio.Event | None = None,
    ) -> dict | None:
        """Mirror the real channel: emit the request frame, then answer it."""
        self.sent.append(
            {"type": _REQ_FRAME_TYPE[kind], "execution_id": execution_id, **payload},
        )
        if kind == "tool_confirmation":
            if self._auto_confirm is None:
                return None  # timeout → not approved
            return {
                "type": "tool_confirmation_response",
                "execution_id": execution_id,
                "approved": self._auto_confirm,
            }
        if kind == "client_tool_call":
            return self._answer_client(execution_id)
        return None

    def _answer_client(self, execution_id: str) -> dict | None:
        """Default: no client connected → timeout (overridden in subclass)."""
        return None


class _ResultSet:
    """Fake DB result set."""

    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return self._items


class MockSession:
    """Fake async DB session that tracks add/flush calls."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flush_count: int = 0

    def add(self, obj: Any) -> None:
        """Record added objects."""
        self.added.append(obj)

    async def flush(self) -> None:
        """No-op flush."""
        self.flush_count += 1

    async def commit(self) -> None:
        """No-op commit."""
        pass

    async def exec(self, _stmt: Any) -> _ResultSet:
        """Return all added Message objects."""
        msgs = [o for o in self.added if isinstance(o, Message)]
        return _ResultSet(msgs)


class MockLLM:
    """Fake LLMService with controllable chat() async generator."""

    def __init__(self, responses: list[list[dict]] | None = None) -> None:
        self._responses = responses or []
        self._idx = 0

    async def chat(
        self,
        messages: list,
        tools: Any = None,
        cancel_event: Any = None,
        system_prompt: str | None = None,
    ):
        """Yield events from the pre-configured response list."""
        if self._idx < len(self._responses):
            events = self._responses[self._idx]
            self._idx += 1
            for e in events:
                yield e
        else:
            yield {"type": "token", "content": "Final answer."}
            yield {"type": "done"}

    def build_continuation_messages(
        self,
        history: list,
        memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list:
        """Passthrough system prompt + history."""
        return [{"role": "system", "content": "sys"}]


class MockToolRegistry:
    """Fake ToolRegistry with controllable per-tool behaviour."""

    def __init__(
        self,
        definitions: dict[str, ToolDefinition] | None = None,
        execute_fn: Any = None,
    ) -> None:
        self._definitions = definitions or {}
        self._execute_fn = execute_fn
        self.execute_calls: list[str] = []

    async def execute_tool(
        self, name: str, args: dict, context: ExecutionContext,
    ) -> ToolResult:
        """Execute (or delegate to execute_fn) for the given tool."""
        self.execute_calls.append(name)
        if self._execute_fn:
            return await self._execute_fn(name, args, context)
        return ToolResult.ok(f"result:{name}")

    async def get_available_tools(self) -> list[dict]:
        """Return OpenAI-format entries for all definitions."""
        return [
            {"type": "function", "function": {"name": n, "description": "d"}}
            for n in self._definitions
        ]

    def get_tool_definition(self, name: str) -> ToolDefinition | None:
        """Lookup a tool definition by name."""
        return self._definitions.get(name)


class _PermissionsCfg:
    """Minimal PermissionsConfig stand-in."""

    def __init__(self) -> None:
        self.confirmations_enabled: bool = True


class _LLMCfg:
    """Minimal LLMConfig stand-in."""

    def __init__(self) -> None:
        self.tools_enabled: bool = True
        self.max_tools: int = 0
        self.priority_plugins: list[str] = []
        self.tool_execution_timeout: float = 120.0


class _Cfg:
    """Minimal config stand-in."""

    def __init__(self) -> None:
        self.permissions = _PermissionsCfg()
        self.llm = _LLMCfg()


class _EventBus:
    """Minimal EventBus stand-in."""

    async def emit(self, *args, **kwargs) -> None:
        pass


class _Ctx:
    """Lightweight stand-in for AppContext."""

    def __init__(self, registry: MockToolRegistry) -> None:
        self.tool_registry = registry
        self.config = _Cfg()
        self.event_bus = _EventBus()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tc(name: str, args: str = "{}") -> dict:
    """Create a tool_call dict as the LLM would emit it."""
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "function": {"name": name, "arguments": args},
    }


async def _run(
    tool_calls: list[dict],
    *,
    registry: MockToolRegistry | None = None,
    ws: MockWebSocket | None = None,
    llm_responses: list[list[dict]] | None = None,
    max_iterations: int = 5,
    cancel_event: asyncio.Event | None = None,
) -> tuple[MockWebSocket, MockSession, MockToolRegistry]:
    """Convenience wrapper that calls run_tool_loop with default mocks."""
    reg = registry or MockToolRegistry()
    websocket = ws or MockWebSocket()
    session = MockSession()
    conv_id = uuid.uuid4()
    llm = MockLLM(llm_responses)

    await run_tool_loop(
        channel=websocket,
        sink=websocket,
        ctx=_Ctx(reg),
        session=session,
        conv_id=conv_id,
        llm=llm,
        tool_calls_from_llm=tool_calls,
        full_content="",
        thinking_content="",
        max_iterations=max_iterations,
        confirmation_timeout_s=2,
        client_ip="127.0.0.1",
        cancel_event=cancel_event,
    )
    return websocket, session, reg


# ---------------------------------------------------------------------------
# Tests — max iterations
# ---------------------------------------------------------------------------


class TestMaxIterations:
    """Loop respects the max_iterations safety cap."""

    @pytest.mark.asyncio
    async def test_stops_after_max_iterations(self) -> None:
        """With max_iterations=1, loop runs once then emits a warning."""
        # LLM re-query yields another tool_call, but loop should stop.
        llm_resp = [[
            {"type": "tool_call", "id": "call_2",
             "function": {"name": "t", "arguments": "{}"}},
            {"type": "done"},
        ]]
        ws, session, reg = await _run(
            [_tc("tool_a")],
            llm_responses=llm_resp,
            max_iterations=1,
        )
        warnings = [m for m in ws.sent if m.get("type") == "warning"]
        assert len(warnings) == 1
        assert "maximum iterations" in warnings[0]["content"].lower()


# ---------------------------------------------------------------------------
# Tests — parallel execution
# ---------------------------------------------------------------------------


class TestParallelExecution:
    """Multiple tool calls in one iteration are executed in parallel."""

    @pytest.mark.asyncio
    async def test_multiple_tools_executed(self) -> None:
        """Two different tool calls → both get execution_start messages."""
        llm_resp = [[
            {"type": "token", "content": "Done"},
            {"type": "done"},
        ]]
        ws, session, reg = await _run(
            [_tc("tool_a"), _tc("tool_b")],
            llm_responses=llm_resp,
        )
        starts = [m for m in ws.sent if m.get("type") == "tool_execution_start"]
        assert len(starts) == 2
        names = {s["tool_name"] for s in starts}
        assert names == {"tool_a", "tool_b"}


# ---------------------------------------------------------------------------
# Tests — deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Duplicate tool+args in one iteration are skipped."""

    @pytest.mark.asyncio
    async def test_duplicate_tool_calls_skipped(self) -> None:
        """Two identical calls → only one execution, one dedup message."""
        llm_resp = [[
            {"type": "token", "content": "Done"},
            {"type": "done"},
        ]]
        ws, _, reg = await _run(
            [_tc("tool_a"), _tc("tool_a")],
            llm_responses=llm_resp,
        )
        starts = [m for m in ws.sent if m.get("type") == "tool_execution_start"]
        assert len(starts) == 1
        assert len(reg.execute_calls) == 1


# ---------------------------------------------------------------------------
# Tests — error recovery
# ---------------------------------------------------------------------------


class TestErrorRecovery:
    """Tool execution failure is caught and reported."""

    @pytest.mark.asyncio
    async def test_tool_failure_saved_as_error(self) -> None:
        """If execute_tool raises, an error message is persisted and sent."""

        async def _fail(name, args, ctx):
            raise RuntimeError("tool crashed")

        llm_resp = [[
            {"type": "token", "content": "Error handled"},
            {"type": "done"},
        ]]
        ws, session, _ = await _run(
            [_tc("bad_tool")],
            registry=MockToolRegistry(execute_fn=_fail),
            llm_responses=llm_resp,
        )
        # Error WS message sent
        error_msgs = [
            m for m in ws.sent
            if m.get("type") == "tool_execution_done" and m.get("success") is False
        ]
        assert len(error_msgs) == 1
        assert "failed" in error_msgs[0]["result"].lower()


# ---------------------------------------------------------------------------
# Tests — cancellation
# ---------------------------------------------------------------------------


class TestCancellation:
    """cancel_event stops the loop before tool execution."""

    @pytest.mark.asyncio
    async def test_cancel_event_breaks_loop(self) -> None:
        """When cancel_event is set, no tools are executed."""
        cancel = asyncio.Event()
        cancel.set()
        ws, _, reg = await _run(
            [_tc("tool_a")],
            cancel_event=cancel,
        )
        starts = [m for m in ws.sent if m.get("type") == "tool_execution_start"]
        assert len(starts) == 0
        assert len(reg.execute_calls) == 0


# ---------------------------------------------------------------------------
# Tests — confirmation flow
# ---------------------------------------------------------------------------


class TestConfirmation:
    """User confirmation for dangerous tools."""

    @pytest.mark.asyncio
    async def test_confirmation_approved(self) -> None:
        """Approved confirmation → tool is executed."""
        confirmable = ToolDefinition(
            name="danger", description="Dangerous op",
            requires_confirmation=True,
        )
        reg = MockToolRegistry(definitions={"danger": confirmable})
        ws = MockWebSocket(auto_confirm=True)
        llm_resp = [[
            {"type": "token", "content": "Done"},
            {"type": "done"},
        ]]
        ws, _, reg = await _run(
            [_tc("danger")],
            registry=reg,
            ws=ws,
            llm_responses=llm_resp,
        )
        assert len(reg.execute_calls) == 1
        confirm_reqs = [
            m for m in ws.sent if m.get("type") == "tool_confirmation_required"
        ]
        assert len(confirm_reqs) == 1

    @pytest.mark.asyncio
    async def test_confirmation_rejected(self) -> None:
        """Rejected (timed-out) confirmation → tool is NOT executed."""
        confirmable = ToolDefinition(
            name="danger", description="Dangerous op",
            requires_confirmation=True,
        )
        reg = MockToolRegistry(definitions={"danger": confirmable})
        # auto_confirm=None → receive_text raises TimeoutError → rejected
        ws = MockWebSocket(auto_confirm=None)
        llm_resp = [[
            {"type": "token", "content": "Rejected"},
            {"type": "done"},
        ]]
        ws, session, reg = await _run(
            [_tc("danger")],
            registry=reg,
            ws=ws,
            llm_responses=llm_resp,
        )
        assert len(reg.execute_calls) == 0
        rejection_msgs = [
            m for m in ws.sent
            if m.get("type") == "tool_execution_done" and m.get("success") is False
        ]
        assert len(rejection_msgs) == 1


# ---------------------------------------------------------------------------
# Tests — client-executed tools
# ---------------------------------------------------------------------------


class _ClientToolWebSocket(MockWebSocket):
    """Channel double that answers ``client_tool_call`` requests.

    Returns a ``client_tool_result`` for each delegated client tool,
    simulating the Continuum web client executing a block tool against the
    open editor.
    """

    def __init__(self, *, success: bool = True, result: Any = None,
                 error: str | None = None) -> None:
        super().__init__()
        self._reply_success = success
        self._reply_result = result
        self._reply_error = error

    def _answer_client(self, execution_id: str) -> dict | None:
        """Return a client_tool_result for the delegated call."""
        payload: dict[str, Any] = {
            "type": "client_tool_result",
            "execution_id": execution_id,
            "success": self._reply_success,
        }
        if self._reply_success:
            payload["result"] = self._reply_result
        else:
            payload["error"] = self._reply_error
        return payload


class TestClientExecutedTools:
    """Tools flagged ``client_execution`` are delegated to the client."""

    @pytest.mark.asyncio
    async def test_client_tool_round_trip(self) -> None:
        """A client tool gets a client_tool_call and persists the result."""
        client_def = ToolDefinition(
            name="continuum_list_blocks",
            description="List blocks",
            client_execution=True,
        )
        reg = MockToolRegistry(definitions={"continuum_list_blocks": client_def})
        ws = _ClientToolWebSocket(result={"count": 2, "blocks": []})
        llm_resp = [[
            {"type": "token", "content": "Listed"},
            {"type": "done"},
        ]]
        ws, session, reg = await _run(
            [_tc("continuum_list_blocks")],
            registry=reg,
            ws=ws,
            llm_responses=llm_resp,
        )
        # The server must NOT run the tool locally.
        assert reg.execute_calls == []
        # A client_tool_call frame was emitted.
        calls = [m for m in ws.sent if m.get("type") == "client_tool_call"]
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "continuum_list_blocks"
        # The result is reported as a successful tool_execution_done.
        done = [
            m for m in ws.sent
            if m.get("type") == "tool_execution_done"
            and m.get("tool_name") == "continuum_list_blocks"
        ]
        assert len(done) == 1
        assert done[0]["success"] is True
        # A role="tool" message was persisted for the LLM loop.
        tool_msgs = [
            o for o in session.added
            if isinstance(o, Message) and o.role == "tool"
        ]
        assert len(tool_msgs) == 1

    @pytest.mark.asyncio
    async def test_client_tool_failure_reported(self) -> None:
        """A client-reported failure becomes a failed tool_execution_done."""
        client_def = ToolDefinition(
            name="continuum_update_block",
            description="Update block",
            client_execution=True,
        )
        reg = MockToolRegistry(definitions={"continuum_update_block": client_def})
        ws = _ClientToolWebSocket(success=False, error="Block index out of range.")
        llm_resp = [[
            {"type": "token", "content": "Handled"},
            {"type": "done"},
        ]]
        ws, session, reg = await _run(
            [_tc("continuum_update_block", '{"index": 99}')],
            registry=reg,
            ws=ws,
            llm_responses=llm_resp,
        )
        assert reg.execute_calls == []
        failures = [
            m for m in ws.sent
            if m.get("type") == "tool_execution_done" and m.get("success") is False
        ]
        assert len(failures) == 1

    @pytest.mark.asyncio
    async def test_client_tool_not_deduplicated(self) -> None:
        """Identical client tool calls are NOT collapsed (live state changes)."""
        client_def = ToolDefinition(
            name="continuum_list_blocks",
            description="List blocks",
            client_execution=True,
        )
        reg = MockToolRegistry(definitions={"continuum_list_blocks": client_def})
        ws = _ClientToolWebSocket(result={"count": 0, "blocks": []})
        llm_resp = [[
            {"type": "token", "content": "Listed twice"},
            {"type": "done"},
        ]]
        ws, _, _ = await _run(
            [_tc("continuum_list_blocks"), _tc("continuum_list_blocks")],
            registry=reg,
            ws=ws,
            llm_responses=llm_resp,
        )
        calls = [m for m in ws.sent if m.get("type") == "client_tool_call"]
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# Tests — empty response retry
# ---------------------------------------------------------------------------


class TestEmptyResponseRetry:
    """LLM returns empty completion after tool execution → retry."""

    @pytest.mark.asyncio
    async def test_retries_on_empty_response(self) -> None:
        """When re-query returns empty, the loop retries and succeeds."""
        # First re-query: empty (no content, no tool_calls).
        # Second re-query: real content.
        llm_resp = [
            [{"type": "done"}],  # empty response
            [{"type": "token", "content": "Got it!"}, {"type": "done"}],
        ]
        ws, _, _ = await _run(
            [_tc("tool_a")],
            llm_responses=llm_resp,
        )
        # The final content should be "Got it!" from the retry.
        tokens = [
            m["content"] for m in ws.sent if m.get("type") == "token"
        ]
        assert "Got it!" in tokens

    @pytest.mark.asyncio
    async def test_accepts_after_max_retries(self) -> None:
        """If all retries return empty, loop accepts empty and stops."""
        # All re-queries return empty — loop should still finish.
        llm_resp = [
            [{"type": "done"}],  # empty 1
            [{"type": "done"}],  # empty 2
            [{"type": "done"}],  # empty 3
        ]
        ws, _, _ = await _run(
            [_tc("tool_a")],
            llm_responses=llm_resp,
        )
        tokens = [
            m["content"] for m in ws.sent if m.get("type") == "token"
        ]
        # No content tokens since all retries were empty.
        assert tokens == []
