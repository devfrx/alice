"""Tests for backend.plugins.agent — AgentPlugin and its meta-tools."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.agent._plan import (
    MAX_STEPS,
    PlanStep,
    PlanStore,
    parse_steps,
    render_plan,
)
from backend.plugins.agent._subagent import (
    BLOCKED_TOOL_NAMES,
    SubagentResult,
    run_subagent,
)
from backend.plugins.agent.plugin import AgentPlugin


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
# 1.  Plan model (_plan.py)
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


class TestRenderPlan:
    def test_render_empty(self):
        assert render_plan([]) == "(empty plan)"

    def test_render_marks(self):
        out = render_plan(
            [
                PlanStep("done", "completed"),
                PlanStep("now", "in_progress"),
                PlanStep("later", "pending"),
            ],
        )
        assert "[x] done" in out
        assert "[~] now" in out
        assert "[ ] later" in out


class TestPlanStore:
    @pytest.mark.asyncio
    async def test_set_get_clear(self):
        store = PlanStore()
        await store.set_plan("c1", [PlanStep("a")])
        assert len(await store.get_plan("c1")) == 1
        # Isolation between conversations.
        assert await store.get_plan("c2") == []
        await store.clear("c1")
        assert await store.get_plan("c1") == []

    @pytest.mark.asyncio
    async def test_set_replaces(self):
        store = PlanStore()
        await store.set_plan("c1", [PlanStep("a"), PlanStep("b")])
        await store.set_plan("c1", [PlanStep("c")])
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
    async def test_both_tools_exposed_by_default(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        names = {t.name for t in plugin.get_tools()}
        assert names == {"update_plan", "spawn_subagent"}
        assert all(isinstance(t, ToolDefinition) for t in plugin.get_tools())

    @pytest.mark.asyncio
    async def test_plan_tool_can_be_disabled(self):
        plugin = AgentPlugin()
        ctx = _make_app_context()
        ctx.config.agent.planning = False
        await plugin.initialize(ctx)
        names = {t.name for t in plugin.get_tools()}
        assert names == {"spawn_subagent"}

    @pytest.mark.asyncio
    async def test_subagent_tool_can_be_disabled(self):
        plugin = AgentPlugin()
        ctx = _make_app_context()
        ctx.config.agent.delegation = False
        await plugin.initialize(ctx)
        names = {t.name for t in plugin.get_tools()}
        assert names == {"update_plan"}

    @pytest.mark.asyncio
    async def test_connection_status_degraded_without_services(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        assert await plugin.get_connection_status() == (
            ConnectionStatus.DEGRADED
        )


# ===========================================================================
# 3.  update_plan tool
# ===========================================================================


class TestUpdatePlanTool:
    @pytest.mark.asyncio
    async def test_update_plan_success(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool(
            "update_plan",
            {"plan": [{"step": "do X", "status": "in_progress"}, "do Y"]},
            _make_exec_ctx(),
        )
        assert result.success
        assert result.content["total_steps"] == 2
        assert result.content["completed_steps"] == 0
        assert result.content["plan"][0]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_plan_invalid_returns_error(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        result = await plugin.execute_tool(
            "update_plan", {"plan": []}, _make_exec_ctx(),
        )
        assert not result.success

    @pytest.mark.asyncio
    async def test_update_plan_persists_in_store(self):
        plugin = AgentPlugin()
        await plugin.initialize(_make_app_context())
        ctx = _make_exec_ctx("conv-42")
        await plugin.execute_tool(
            "update_plan", {"plan": ["a", "b", "c"]}, ctx,
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
                _tool_entry("agent_update_plan"),
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
