"""Tests for backend.plugins.agent — AgentPlugin and its meta-tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.db.models import Conversation
from backend.plugins.agent._plan import (
    MAX_STEPS,
    TaskStep,
    TaskStore,
    parse_steps,
    render_tasks,
)
from backend.plugins.agent._subagent import (
    BLOCKED_TOOL_NAMES,
    run_subagent,
)
from backend.plugins.agent.plugin import AgentPlugin
from backend.services.plan_document_service import PlanDocumentService
from backend.services.plan_service import PlanService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_ctx(conv: str = "conv-1") -> ExecutionContext:
    return ExecutionContext(
        session_id="sess-1",
        conversation_id=conv,
        execution_id="exec-1",
    )


def _make_app_context() -> AppContext:
    return AppContext(config=load_config(), event_bus=EventBus())


def _tool_entry(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": "", "parameters": {}},
    }


async def _aiter(events: list[dict[str, Any]]):
    for event in events:
        yield event


# ===========================================================================
# 1.  Tasks model (_plan.py)
# ===========================================================================


class TestParseSteps:
    def test_parse_list_of_strings(self):
        steps = parse_steps(["a", "b"])
        assert [s.description for s in steps] == ["a", "b"]
        assert all(s.status == "pending" for s in steps)

    def test_parse_list_of_objects(self):
        steps = parse_steps(
            [
                {"step": "research", "status": "completed"},
                {"description": "write", "status": "in_progress"},
            ],
        )
        assert steps[0].description == "research"
        assert steps[0].status == "completed"
        assert steps[1].description == "write"
        assert steps[1].status == "in_progress"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_steps([])

    def test_non_list_raises(self):
        with pytest.raises(ValueError):
            parse_steps("not a list")

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            parse_steps([{"step": "x", "status": "bogus"}])

    def test_empty_description_raises(self):
        with pytest.raises(ValueError):
            parse_steps([{"step": "   "}])

    def test_too_many_steps_raises(self):
        with pytest.raises(ValueError):
            parse_steps(["x"] * (MAX_STEPS + 1))


class TestRenderTasks:
    def test_render_empty(self):
        assert render_tasks([]) == "(empty plan)"

    def test_render_marks(self):
        out = render_tasks(
            [
                TaskStep("done", "completed"),
                TaskStep("now", "in_progress"),
                TaskStep("later", "pending"),
            ],
        )
        assert "[x] done" in out
        assert "[~] now" in out
        assert "[ ] later" in out


class TestTaskStore:
    @pytest.mark.asyncio
    async def test_set_get_clear(self):
        store = TaskStore()
        await store.set_plan("c1", [TaskStep("a")])
        assert len(await store.get_plan("c1")) == 1
        # Isolation between conversations.
        assert await store.get_plan("c2") == []
        await store.clear("c1")
        assert await store.get_plan("c1") == []

    @pytest.mark.asyncio
    async def test_set_replaces(self):
        store = TaskStore()
        await store.set_plan("c1", [TaskStep("a"), TaskStep("b")])
        await store.set_plan("c1", [TaskStep("c")])
        plan = await store.get_plan("c1")
        assert [s.description for s in plan] == ["c"]


# ===========================================================================
# 2.  Plugin: tool definitions & lifecycle
# ===========================================================================


class TestAgentPluginTools:
    def test_class_attributes(self):
        plugin = AgentPlugin()
        assert plugin.plugin_name == "agent"
        assert plugin.plugin_priority == 5

    @pytest.mark.asyncio
    async def test_all_tools_exposed_by_default(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        names = {t.name for t in plugin.get_tools()}
        assert names == {
            "update_tasks", "write_plan", "spawn_subagent", "ask_user",
        }
        assert all(isinstance(t, ToolDefinition) for t in plugin.get_tools())

    @pytest.mark.asyncio
    async def test_planning_tools_carry_planning_capability(self):
        # Mode policies exempt meta-tools from the capability-blocking pass
        # via ``always_offered`` on the definition (the old tier whitelist
        # keyed on the ``planning`` tag was retired); the ("planning",)
        # capability remains as classifying metadata every meta-tool must
        # still declare.
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        by_name = {t.name: t for t in plugin.get_tools()}
        for name in ("update_tasks", "write_plan", "spawn_subagent", "ask_user"):
            assert by_name[name].capabilities == ("planning",), name

    @pytest.mark.asyncio
    async def test_plan_tool_can_be_disabled(self):
        plugin = AgentPlugin()
        ctx = _make_app_context()
        ctx.config.agent.planning = False
        await plugin.initialize(ctx)
        names = {t.name for t in plugin.get_tools()}
        assert names == {"spawn_subagent", "ask_user"}

    @pytest.mark.asyncio
    async def test_subagent_tool_can_be_disabled(self):
        plugin = AgentPlugin()
        ctx = _make_app_context()
        ctx.config.agent.delegation = False
        await plugin.initialize(ctx)
        names = {t.name for t in plugin.get_tools()}
        assert names == {"update_tasks", "write_plan", "ask_user"}

    @pytest.mark.asyncio
    async def test_ask_user_tool_exposed_by_default(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        tool = next(t for t in plugin.get_tools() if t.name == "ask_user")
        assert tool.user_interaction is True
        assert tool.risk_level == "safe"
        assert tool.requires_confirmation is False
        # Multi-question contract: a required ``questions`` array whose items
        # carry id/text/type (radio|checkbox).
        assert "questions" in tool.parameters["required"]
        questions = tool.parameters["properties"]["questions"]
        assert questions["type"] == "array"
        item_props = questions["items"]["properties"]
        assert {"id", "text", "type"} <= set(item_props)

    @pytest.mark.asyncio
    async def test_ask_user_tool_can_be_disabled(self):
        plugin = AgentPlugin()
        ctx = _make_app_context()
        ctx.config.agent.clarification = False
        await plugin.initialize(ctx)
        names = {t.name for t in plugin.get_tools()}
        assert "ask_user" not in names
        # Planning / delegation remain governed by their own flags.
        assert names == {"update_tasks", "write_plan", "spawn_subagent"}

    @pytest.mark.asyncio
    async def test_ask_user_execute_is_defensive(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool(
            "ask_user",
            {"question": "Which one?"},
            _make_exec_ctx(),
        )
        assert isinstance(result, ToolResult)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_connection_status_degraded_without_services(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        assert await plugin.get_connection_status() == (
            ConnectionStatus.DEGRADED
        )


# ===========================================================================
# 3.  update_tasks tool
# ===========================================================================


class TestUpdateTasksTool:
    @pytest.mark.asyncio
    async def test_update_tasks_success(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool(
            "update_tasks",
            {"tasks": [{"step": "do X", "status": "in_progress"}, "do Y"]},
            _make_exec_ctx(),
        )
        assert result.success
        assert result.content["total_steps"] == 2
        assert result.content["completed_steps"] == 0
        assert result.content["tasks"][0]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_tasks_invalid_returns_error(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool(
            "update_tasks", {"tasks": []}, _make_exec_ctx(),
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_update_tasks_persists_in_store(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        ctx = _make_exec_ctx("conv-42")
        await plugin.execute_tool(
            "update_tasks", {"tasks": ["a", "b", "c"]}, ctx,
        )
        plan = await plugin._plans.get_plan("conv-42")
        assert len(plan) == 3

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool("nope", {}, _make_exec_ctx())
        assert not result.success


# ===========================================================================
# 3b.  write_plan tool
# ===========================================================================


class _StubPlanDocumentService:
    """Minimal stand-in capturing ``set_document`` calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def set_document(
        self, conversation_id: Any, title: str, body: str,
    ) -> None:
        self.calls.append((str(conversation_id), title, body))


class TestWritePlanTool:
    @pytest.mark.asyncio
    async def test_write_plan_persists_and_returns_ok(self):
        ctx = _make_app_context()
        stub = _StubPlanDocumentService()
        ctx.plan_document_service = stub  # type: ignore[assignment]
        plugin = AgentPlugin()
        await plugin.initialize(ctx)

        body = "## Goal\nShip it."
        result = await plugin.execute_tool(
            "write_plan",
            {"title": "Strategy", "document": body},
            _make_exec_ctx("conv-7"),
        )
        assert result.success
        assert result.content["ok"] is True
        assert result.content["title"] == "Strategy"
        assert result.content["chars"] == len(body)
        # Persisted wholesale via the wired service (title + body).
        assert stub.calls == [("conv-7", "Strategy", body)]

    @pytest.mark.asyncio
    async def test_write_plan_without_title_passes_empty_string(self):
        ctx = _make_app_context()
        stub = _StubPlanDocumentService()
        ctx.plan_document_service = stub  # type: ignore[assignment]
        plugin = AgentPlugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "write_plan", {"document": "body only"}, _make_exec_ctx("c-1"),
        )
        assert result.success
        assert result.content["title"] == ""
        assert stub.calls == [("c-1", "", "body only")]

    @pytest.mark.asyncio
    async def test_write_plan_empty_document_returns_error(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool(
            "write_plan", {"document": "   "}, _make_exec_ctx(),
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_write_plan_missing_document_returns_error(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool(
            "write_plan", {}, _make_exec_ctx(),
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_write_plan_without_service_still_ok(self):
        # No plan_document_service wired → still validates + reports success
        # so the model's tool loop is unaffected.
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool(
            "write_plan", {"document": "x"}, _make_exec_ctx(),
        )
        assert result.success
        assert result.content["chars"] == 1


# ===========================================================================
# 4.  spawn_subagent tool + runner
# ===========================================================================


def _make_ctx_with_services(
    chat_scripts: list[list[dict[str, Any]]],
    tools: list[dict[str, Any]] | None = None,
    tool_results: dict[str, ToolResult] | None = None,
) -> AppContext:
    """Build an AppContext whose llm_service.chat replays scripted streams."""
    ctx = _make_app_context()

    llm = MagicMock()
    calls = {"n": 0}

    def _chat(*_args: Any, **_kwargs: Any):
        idx = calls["n"]
        calls["n"] += 1
        script = chat_scripts[min(idx, len(chat_scripts) - 1)]
        return _aiter(script)

    llm.chat = _chat
    ctx.llm_service = llm  # type: ignore[assignment]

    registry = MagicMock()
    registry.get_available_tools = AsyncMock(return_value=tools or [])
    registry.get_tool_definition = MagicMock(return_value=None)

    async def _execute_tool(name: str, _args: Any, _exec: Any) -> ToolResult:
        if tool_results and name in tool_results:
            return tool_results[name]
        return ToolResult.ok(f"result of {name}")

    registry.execute_tool = AsyncMock(side_effect=_execute_tool)
    ctx.tool_registry = registry  # type: ignore[assignment]
    return ctx


class TestSpawnSubagent:
    @pytest.mark.asyncio
    async def test_subagent_direct_answer(self):
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {"type": "token", "content": "the answer is 42"},
                    {"type": "usage", "input_tokens": 10, "output_tokens": 5},
                    {"type": "done", "finish_reason": "stop"},
                ],
            ],
        )
        plugin = AgentPlugin()
        await plugin.initialize(ctx)
        result = await plugin.execute_tool(
            "spawn_subagent", {"task": "what is 6*7"}, _make_exec_ctx(),
        )
        assert result.success
        assert result.content["summary"] == "the answer is 42"
        assert result.content["stop_reason"] == "completed"
        assert result.content["steps_used"] == 1

    @pytest.mark.asyncio
    async def test_subagent_uses_tool_then_answers(self):
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {
                        "type": "tool_call",
                        "id": "call_1",
                        "function": {
                            "name": "system_info_get",
                            "arguments": "{}",
                        },
                    },
                    {"type": "done", "finish_reason": "tool_calls"},
                ],
                [
                    {"type": "token", "content": "done using the tool"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            ],
            tools=[_tool_entry("system_info_get")],
        )
        plugin = AgentPlugin()
        await plugin.initialize(ctx)
        result = await plugin.execute_tool(
            "spawn_subagent",
            {"task": "get system info", "context": "extra"},
            _make_exec_ctx(),
        )
        assert result.success
        assert result.content["summary"] == "done using the tool"
        assert result.content["tools_called"] == ["system_info_get"]
        assert result.content["steps_used"] == 2

    @pytest.mark.asyncio
    async def test_subagent_missing_task(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool(
            "spawn_subagent", {"task": "  "}, _make_exec_ctx(),
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_subagent_llm_error(self):
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {"type": "error", "content": "model exploded"},
                    {"type": "done", "finish_reason": "error"},
                ],
            ],
        )
        plugin = AgentPlugin()
        await plugin.initialize(ctx)
        result = await plugin.execute_tool(
            "spawn_subagent", {"task": "do it"}, _make_exec_ctx(),
        )
        assert not result.success
        assert "model exploded" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_subagent_max_steps(self):
        # Always returns a tool call → never terminates on its own.
        loop_step = [
            {
                "type": "tool_call",
                "id": "call_x",
                "function": {"name": "system_info_get", "arguments": "{}"},
            },
            {"type": "done", "finish_reason": "tool_calls"},
        ]
        ctx = _make_ctx_with_services(
            chat_scripts=[loop_step],
            tools=[_tool_entry("system_info_get")],
        )
        ctx.config.agent.subagent.max_steps = 3
        plugin = AgentPlugin()
        await plugin.initialize(ctx)
        result = await plugin.execute_tool(
            "spawn_subagent", {"task": "loop forever"}, _make_exec_ctx(),
        )
        assert result.success
        assert result.content["stop_reason"] == "max_steps"
        assert result.content["steps_used"] == 3

    @pytest.mark.asyncio
    async def test_subagent_unavailable_services(self):
        result = await run_subagent(
            ctx=_make_app_context(),
            task="x",
            context=None,
            allowed_tools=None,
            max_steps=3,
            max_output_tokens=128,
            timeout_seconds=10.0,
            max_tools=8,
            conversation_id="c",
            session_id="s",
        )
        assert result.stop_reason == "error"

    @pytest.mark.asyncio
    async def test_blocked_tools_filtered(self):
        # Agent meta-tools must never be exposed to a sub-agent.
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {"type": "token", "content": "ok"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            ],
            tools=[
                _tool_entry("agent_spawn_subagent"),
                _tool_entry("agent_update_tasks"),
                _tool_entry("web_search_search"),
            ],
        )
        # Spy on the tools actually passed to llm.chat.
        captured: dict[str, Any] = {}

        def _chat(*_args: Any, **kwargs: Any):
            captured["tools"] = kwargs.get("tools")
            return _aiter(
                [
                    {"type": "token", "content": "ok"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            )

        ctx.llm_service.chat = _chat  # type: ignore[attr-defined]
        plugin = AgentPlugin()
        await plugin.initialize(ctx)
        await plugin.execute_tool(
            "spawn_subagent", {"task": "x"}, _make_exec_ctx(),
        )
        passed = {t["function"]["name"] for t in (captured["tools"] or [])}
        assert passed == {"web_search_search"}
        assert not (BLOCKED_TOOL_NAMES & passed)

    @pytest.mark.asyncio
    async def test_allowed_tools_allowlist(self):
        captured: dict[str, Any] = {}

        ctx = _make_ctx_with_services(
            chat_scripts=[[{"type": "done", "finish_reason": "stop"}]],
            tools=[
                _tool_entry("web_search_search"),
                _tool_entry("system_info_get"),
            ],
        )

        def _chat(*_args: Any, **kwargs: Any):
            captured["tools"] = kwargs.get("tools")
            return _aiter(
                [
                    {"type": "token", "content": "ok"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            )

        ctx.llm_service.chat = _chat  # type: ignore[attr-defined]
        plugin = AgentPlugin()
        await plugin.initialize(ctx)
        await plugin.execute_tool(
            "spawn_subagent",
            {"task": "x", "allowed_tools": ["web_search_search"]},
            _make_exec_ctx(),
        )
        passed = {t["function"]["name"] for t in (captured["tools"] or [])}
        assert passed == {"web_search_search"}

    @pytest.mark.asyncio
    async def test_subagent_denied_tool_is_not_executed(self):
        """A gate denial becomes an ERROR tool-result; execute_tool never runs."""
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {
                        "type": "tool_call",
                        "id": "call_1",
                        "function": {"name": "system_info_get", "arguments": "{}"},
                    },
                    {"type": "done", "finish_reason": "tool_calls"},
                ],
                [
                    {"type": "token", "content": "could not use the tool"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            ],
            tools=[_tool_entry("system_info_get")],
        )

        class _DenyingGate:
            calls: list[str] = []

            def explain_denial(self, *, tool_name, args, tool_def,
                               conversation_id, mode):
                self.calls.append(tool_name)
                return f"Tool '{tool_name}' denied by permission policy (test)."

        _DenyingGate.calls = []
        ctx.permission_service = _DenyingGate()
        executed: list[str] = []
        original_execute = ctx.tool_registry.execute_tool

        async def _spy_execute(name, args, exec_ctx):
            executed.append(name)
            return await original_execute(name, args, exec_ctx)

        ctx.tool_registry.execute_tool = _spy_execute  # type: ignore[method-assign]

        result = await run_subagent(
            ctx=ctx,
            task="get system info",
            context=None,
            allowed_tools=None,
            max_steps=3,
            max_output_tokens=128,
            timeout_seconds=10.0,
            max_tools=8,
            conversation_id="c",
            session_id="s",
        )
        assert result.stop_reason == "completed"
        assert executed == []
        assert _DenyingGate.calls == ["system_info_get"]

    @pytest.mark.asyncio
    async def test_subagent_allowed_by_gate_executes(self):
        """explain_denial → None lets the call through to execute_tool."""
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {
                        "type": "tool_call",
                        "id": "call_1",
                        "function": {"name": "system_info_get", "arguments": "{}"},
                    },
                    {"type": "done", "finish_reason": "tool_calls"},
                ],
                [
                    {"type": "token", "content": "done"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            ],
            tools=[_tool_entry("system_info_get")],
        )

        class _AllowingGate:
            def explain_denial(self, **kwargs):
                return None

        ctx.permission_service = _AllowingGate()
        result = await run_subagent(
            ctx=ctx,
            task="get system info",
            context=None,
            allowed_tools=None,
            max_steps=3,
            max_output_tokens=128,
            timeout_seconds=10.0,
            max_tools=8,
            conversation_id="c",
            session_id="s",
        )
        assert result.tools_called == ["system_info_get"]

    @pytest.mark.asyncio
    async def test_subagent_progress_cb_called_per_step(self):
        ctx = _make_ctx_with_services(
            chat_scripts=[
                [
                    {"type": "token", "content": "the answer"},
                    {"type": "done", "finish_reason": "stop"},
                ],
            ],
        )
        progress: list[tuple[int, int, str]] = []

        async def _cb(step: int, total: int, note: str) -> None:
            progress.append((step, total, note))

        result = await run_subagent(
            ctx=ctx,
            task="quick",
            context=None,
            allowed_tools=None,
            max_steps=3,
            max_output_tokens=128,
            timeout_seconds=10.0,
            max_tools=8,
            conversation_id="c",
            session_id="s",
            progress_cb=_cb,
        )
        assert result.stop_reason == "completed"
        assert progress == [(1, 3, "step 1/3")]


# ===========================================================================
# 5.  update_tasks persistence via a wired PlanService
# ===========================================================================


@pytest.fixture
async def plan_session_factory():
    """In-memory SQLite + session factory (mirrors test_plan_service.py).

    Foreign-key enforcement is enabled per-connection so the
    ``ConversationPlan -> Conversation`` FK is exercised.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_fk(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(
        engine, class_=SQLModelAsyncSession, expire_on_commit=False,
    )
    yield factory
    await engine.dispose()


class TestUpdateTasksPersistence:
    """``update_tasks`` persists via ``ctx.plan_service`` when one is wired."""

    @pytest.mark.asyncio
    async def test_update_tasks_persists_and_broadcasts(
        self, plan_session_factory,
    ):
        # Parent conversation row (FK target for ConversationPlan).
        async with plan_session_factory() as session:
            conv = Conversation(title="t")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
            conv_id = conv.id

        captured: list[dict[str, Any]] = []

        async def _capture(event_payload: dict[str, Any]) -> None:
            captured.append(event_payload)

        plan_service = PlanService(session_factory=plan_session_factory)
        plan_service.set_event_callback(_capture)

        ctx = _make_app_context()
        ctx.plan_service = plan_service

        plugin = AgentPlugin()
        await plugin.initialize(ctx)

        expected_steps = [
            {"step": "research", "status": "in_progress"},
            {"step": "write", "status": "pending"},
        ]
        result = await plugin.execute_tool(
            "update_tasks",
            {"tasks": [{"step": "research", "status": "in_progress"}, "write"]},
            _make_exec_ctx(str(conv_id)),
        )
        assert result.success

        # Persisted to the DB via the service (not the in-memory store).
        assert await plan_service.get_plan(conv_id) == expected_steps
        # The in-memory fallback store was NOT written to.
        assert await plugin._plans.get_plan(str(conv_id)) == []

        # The tasks.updated broadcast fired once with the canonical payload.
        assert captured == [
            {
                "type": "tasks.updated",
                "conversation_id": str(conv_id),
                "steps": expected_steps,
            }
        ]


# ===========================================================================
# 6.  write_plan persistence via a wired PlanDocumentService
# ===========================================================================


class TestWritePlanPersistence:
    """``write_plan`` persists the document via ``ctx.plan_document_service``."""

    @pytest.mark.asyncio
    async def test_write_plan_persists_and_broadcasts(
        self, plan_session_factory,
    ):
        # Parent conversation row (FK target for ConversationPlanDocument).
        async with plan_session_factory() as session:
            conv = Conversation(title="t")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
            conv_id = conv.id

        captured: list[dict[str, Any]] = []

        async def _capture(event_payload: dict[str, Any]) -> None:
            captured.append(event_payload)

        doc_service = PlanDocumentService(session_factory=plan_session_factory)
        doc_service.set_event_callback(_capture)

        ctx = _make_app_context()
        ctx.plan_document_service = doc_service

        plugin = AgentPlugin()
        await plugin.initialize(ctx)

        body = "## Plan\n1. analyse\n2. build"
        result = await plugin.execute_tool(
            "write_plan",
            {"title": "Release", "document": body},
            _make_exec_ctx(str(conv_id)),
        )
        assert result.success
        assert result.content["title"] == "Release"
        assert result.content["chars"] == len(body)

        # Persisted to the DB via the service (round-trips title + body).
        stored = await doc_service.get_document(conv_id)
        assert stored is not None
        assert stored["title"] == "Release"
        assert stored["body"] == body

        # The plan_document.updated broadcast fired once.
        assert len(captured) == 1
        assert captured[0]["type"] == "plan_document.updated"
        assert captured[0]["conversation_id"] == str(conv_id)
        assert captured[0]["title"] == "Release"
        assert captured[0]["body"] == body


# ===========================================================================
# 7.  Orchestration contract (always_offered + usage_guidance)
# ===========================================================================


class TestOrchestrationContract:
    """The four meta-tools are always offered and carry usage guidance."""

    def test_meta_tools_always_offered_with_guidance(self):
        plugin = AgentPlugin()
        tools = {t.name: t for t in plugin.get_tools()}
        assert set(tools) == {
            "update_tasks", "write_plan", "spawn_subagent", "ask_user",
        }
        for name, tool in tools.items():
            assert tool.always_offered is True, name
            assert tool.usage_guidance, name
            assert f"`{name}`" in tool.usage_guidance, name
