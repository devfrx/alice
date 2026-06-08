"""AL\\CE — Agent plugin.

Exposes two Claude/GPT-style agentic meta-tools that sit *on top of* the
existing tool loop, giving the model first-class planning and delegation:

* ``update_plan`` — maintain a visible, mutable todo-list for the current
  conversation.  Calling it replaces the whole plan, so the model always
  owns the source of truth.  Costs no extra inference: it is just a tool
  the model calls inside its normal loop.
* ``spawn_subagent`` — delegate ONE self-contained task to an
  isolated-context sub-agent that runs its own mini tool-loop and returns a
  single concise summary.  Execution is serial / blocking (single local GPU
  serialises inference), which is exactly the context-isolation pattern.

Both tools are opt-in via the ``agent.planning`` / ``agent.delegation``
flags in :class:`~backend.core.config.AgentConfig`.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)

from ._plan import PlanStore, parse_steps, render_plan
from ._subagent import run_subagent

if TYPE_CHECKING:
    from backend.core.context import AppContext


class AgentPlugin(BasePlugin):
    """Planning and delegation meta-tools for agentic execution."""

    plugin_name: str = "agent"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Agentic meta-tools: a mutable todo-list (update_plan) and "
        "isolated-context task delegation (spawn_subagent)."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 5

    def __init__(self) -> None:
        super().__init__()
        self._plans = PlanStore()

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Initialise the plugin and its per-conversation plan store."""
        await super().initialize(ctx)

    # -- Tools -------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return the agent meta-tool definitions.

        Tools are gated by the ``agent.planning`` / ``agent.delegation`` /
        ``agent.clarification`` config flags so a deployment can expose any
        subset (e.g. planning without delegation, or neither).

        Returns:
            Zero to three ``ToolDefinition`` objects.
        """
        cfg = self._ctx.config.agent if self._ctx else None
        tools: list[ToolDefinition] = []

        if cfg is None or cfg.planning:
            tools.append(
                ToolDefinition(
                    name="update_plan",
                    description=(
                        "Create or update your working todo-list for a "
                        "complex, multi-step task. Call this to break the "
                        "task into steps, then call it again to mark steps "
                        "in_progress/completed as you go. Each call REPLACES "
                        "the whole plan. Use it for non-trivial work so the "
                        "user can follow your progress; skip it for simple "
                        "one-shot answers."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "plan": {
                                "type": "array",
                                "description": (
                                    "Ordered list of steps. Each item is an "
                                    "object with 'step' (description) and "
                                    "'status' (pending|in_progress|completed)."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "step": {"type": "string"},
                                        "status": {
                                            "type": "string",
                                            "enum": [
                                                "pending",
                                                "in_progress",
                                                "completed",
                                            ],
                                        },
                                    },
                                    "required": ["step"],
                                },
                            },
                        },
                        "required": ["plan"],
                    },
                    result_type="json",
                    risk_level="safe",
                    timeout_ms=5000,
                ),
            )

        if cfg is None or cfg.delegation:
            tools.append(
                ToolDefinition(
                    name="spawn_subagent",
                    description=(
                        "Delegate ONE self-contained sub-task to an isolated "
                        "sub-agent with a clean context. The sub-agent runs "
                        "its own tool loop and returns a single concise "
                        "summary — it never sees this conversation. Use it "
                        "for focused research or exploration that would "
                        "otherwise clutter your context (e.g. 'find which "
                        "files define X', 'summarise the latest news on Y'). "
                        "Runs synchronously: you get the result before "
                        "continuing. Do NOT use it for trivial single tool "
                        "calls you can make yourself."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": (
                                    "The self-contained task for the "
                                    "sub-agent, phrased as a clear "
                                    "instruction."
                                ),
                            },
                            "context": {
                                "type": "string",
                                "description": (
                                    "Optional extra context the sub-agent "
                                    "needs (it cannot see the conversation)."
                                ),
                            },
                            "allowed_tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Optional allow-list of tool names the "
                                    "sub-agent may use. Omit to allow all "
                                    "safe tools."
                                ),
                            },
                        },
                        "required": ["task"],
                    },
                    result_type="json",
                    risk_level="safe",
                    timeout_ms=300_000,
                ),
            )

        if cfg is None or cfg.clarification:
            tools.append(
                ToolDefinition(
                    name="ask_user",
                    description=(
                        "Ask the user a clarifying question and WAIT for their "
                        "answer before continuing. Use this only when you "
                        "genuinely need information that only the user can "
                        "provide — a missing detail, a choice between concrete "
                        "options, or confirmation of intent — and cannot "
                        "reasonably proceed without it. Provide 'options' for a "
                        "multiple-choice question, or omit it for a free-form "
                        "answer. Do not overuse it: for trivial gaps, make a "
                        "reasonable assumption and proceed."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": (
                                    "The question to ask the user, phrased "
                                    "clearly and concisely."
                                ),
                            },
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Optional list of suggested answers the "
                                    "user can pick from (they may also answer "
                                    "freely)."
                                ),
                            },
                        },
                        "required": ["question"],
                    },
                    result_type="string",
                    risk_level="safe",
                    user_interaction=True,
                    timeout_ms=300_000,
                ),
            )

        return tools

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested agent meta-tool.

        Args:
            tool_name: ``"update_plan"``, ``"spawn_subagent"``, or
                ``"ask_user"`` (the last is handled defensively — it is
                normally intercepted by the interaction channel).
            args: Caller-supplied arguments.
            context: Execution metadata (session, conversation).

        Returns:
            A ``ToolResult`` with the payload or an error.
        """
        try:
            if tool_name == "update_plan":
                return await self._update_plan(args, context)
            if tool_name == "spawn_subagent":
                return await self._spawn_subagent(args, context)
            if tool_name == "ask_user":
                return ToolResult.error(
                    "ask_user is handled by the interaction channel, not "
                    "server execution.",
                )
            return ToolResult.error(f"Unknown tool: {tool_name}")
        except Exception as exc:
            self.logger.error("Tool {} failed: {}", tool_name, exc)
            return ToolResult.error(str(exc))

    # -- Tool implementations ---------------------------------------------

    async def _update_plan(
        self, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        """Replace the conversation's todo-list with the supplied steps."""
        start = time.perf_counter()
        try:
            steps = parse_steps(args.get("plan"))
        except ValueError as exc:
            return ToolResult.error(str(exc))

        steps_dicts = [s.to_dict() for s in steps]
        plan_service = self._ctx.plan_service if self._ctx is not None else None
        if plan_service is not None:
            await plan_service.set_plan(context.conversation_id, steps_dicts)
        else:
            await self._plans.set_plan(context.conversation_id, steps)
        elapsed = (time.perf_counter() - start) * 1000.0
        completed = sum(1 for s in steps if s.status == "completed")
        return ToolResult.ok(
            {
                "ok": True,
                "total_steps": len(steps),
                "completed_steps": completed,
                "plan": [s.to_dict() for s in steps],
                "rendered": render_plan(steps),
            },
            content_type="application/json",
            execution_time_ms=elapsed,
        )

    async def _spawn_subagent(
        self, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult:
        """Run an isolated sub-agent and return its summary."""
        if self._ctx is None:
            return ToolResult.error("Plugin not initialised")
        cfg = self._ctx.config.agent.subagent

        task = str(args.get("task", "")).strip()
        if not task:
            return ToolResult.error("'task' is required and must be non-empty")

        extra = args.get("context")
        extra_context = str(extra).strip() if extra else None

        allowed_raw = args.get("allowed_tools")
        allowed_tools: list[str] | None = None
        if isinstance(allowed_raw, list):
            allowed_tools = [str(t) for t in allowed_raw if str(t).strip()]
            allowed_tools = allowed_tools or None

        start = time.perf_counter()
        logger.info("spawn_subagent: delegating task: {}", task[:120])
        result = await run_subagent(
            ctx=self._ctx,
            task=task,
            context=extra_context,
            allowed_tools=allowed_tools,
            max_steps=cfg.max_steps,
            max_output_tokens=cfg.max_output_tokens,
            timeout_seconds=cfg.timeout_seconds,
            max_tools=cfg.max_tools,
            conversation_id=context.conversation_id,
            session_id=context.session_id,
        )
        elapsed = (time.perf_counter() - start) * 1000.0

        if result.stop_reason == "error":
            return ToolResult.error(
                f"Sub-agent failed: {result.error}",
                execution_time_ms=elapsed,
            )

        return ToolResult.ok(
            {
                "summary": result.summary,
                "stop_reason": result.stop_reason,
                "steps_used": result.steps_used,
                "tools_called": result.tools_called,
            },
            content_type="application/json",
            execution_time_ms=elapsed,
        )

    # -- Health ------------------------------------------------------------

    def check_dependencies(self) -> list[str]:
        """No external dependencies — always returns an empty list."""
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Healthy whenever the LLM service and tool registry are wired."""
        if self._ctx is None:
            return ConnectionStatus.UNKNOWN
        if self._ctx.llm_service is None or self._ctx.tool_registry is None:
            return ConnectionStatus.DEGRADED
        return ConnectionStatus.CONNECTED
