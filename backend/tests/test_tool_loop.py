"""Tests for the tool calling loop (Phase 3.8).

Integration-style tests for ``run_tool_loop()`` with mocked WebSocket,
DB session, LLMService, and ToolRegistry.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest

from backend.api.routes._tool_loop import run_tool_loop
from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult
from backend.db.models import Conversation, Message


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockWebSocket:
    """Fake WebSocket that records sent messages and optionally auto-confirms."""

    def __init__(self, *, auto_confirm: bool | None = None) -> None:
        self.sent: list[dict] = []
        self._auto_confirm = auto_confirm

    async def send_json(self, data: dict) -> None:
        """Record outgoing WS messages."""
        self.sent.append(data)

    async def receive_text(self) -> str:
        """Return auto-confirmation response or raise TimeoutError."""
        if self._auto_confirm is not None:
            for msg in reversed(self.sent):
                if msg.get("type") == "tool_confirmation_required":
                    return json.dumps({
                        "type": "tool_confirmation_response",
                        "execution_id": msg["execution_id"],
                        "approved": self._auto_confirm,
                    })
        raise asyncio.TimeoutError


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
        self, messages: list, tools: Any = None, cancel_event: Any = None,
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

    def build_continuation_messages(self, history: list) -> list:
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


class _Ctx:
    """Lightweight stand-in for AppContext."""

    def __init__(self, registry: MockToolRegistry) -> None:
        self.tool_registry = registry
        self.conversation_file_manager = None


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
        websocket=websocket,
        ctx=_Ctx(reg),
        session=session,
        conv_id=conv_id,
        conv=Conversation(id=conv_id),
        llm=llm,
        tool_calls_from_llm=tool_calls,
        full_content="",
        thinking_content="",
        max_iterations=max_iterations,
        confirmation_timeout_s=2,
        client_ip="127.0.0.1",
        sync_fn=None,
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
