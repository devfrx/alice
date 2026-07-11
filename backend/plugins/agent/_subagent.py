"""AL\\CE — Agent plugin: isolated-context sub-agent runner.

A *sub-agent* is a self-contained mini tool-loop that runs with a **clean
context window** (only the delegated task — never the parent conversation)
and returns a single concise summary to the parent.

Execution is deliberately **serial / blocking**: a local single-GPU LM Studio
backend serialises inference, so there is no throughput benefit to running
sub-agents concurrently.  The parent ``spawn_subagent`` tool ``await``\\s this
runner to completion before continuing its own loop — which is exactly the
context-isolation pattern used by Claude/GPT "task" tools.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.core.plugin_models import ExecutionContext

if TYPE_CHECKING:
    from backend.core.context import AppContext

ProgressCallback = Callable[[int, int, str], Awaitable[None]]
"""(step, max_steps, note) — reports sub-agent progress (Fase 8)."""

#: Tools a sub-agent may never call (prevents unbounded recursion).
BLOCKED_TOOL_NAMES: frozenset[str] = frozenset(
    {"agent_spawn_subagent", "agent_update_tasks"},
)

_SUBAGENT_SYSTEM_PROMPT = (
    "You are a focused sub-agent spawned by a primary AI assistant to "
    "complete ONE self-contained task in isolation.\n\n"
    "You have a CLEAN context: you only see the task below, not the parent "
    "conversation. Use the available tools to gather information or perform "
    "the work, then produce a concise, self-contained final answer that the "
    "primary assistant can use directly.\n\n"
    "Rules:\n"
    "- Do the work yourself; never ask the parent or the user questions.\n"
    "- Stop calling tools as soon as you have enough to answer.\n"
    "- Be concise and factual: report findings and results, not your process."
)


@dataclass(slots=True)
class SubagentResult:
    """Outcome of a single sub-agent run.

    Attributes:
        summary: The sub-agent's final natural-language answer.
        steps_used: Number of LLM turns consumed.
        tools_called: Namespaced names of tools the sub-agent invoked.
        input_tokens: Total prompt tokens reported across steps.
        output_tokens: Total completion tokens reported across steps.
        stop_reason: ``"completed"``, ``"max_steps"``, ``"timeout"``,
            ``"cancelled"`` or ``"error"``.
        error: Human-readable error detail when ``stop_reason == "error"``.
    """

    summary: str = ""
    steps_used: int = 0
    tools_called: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "completed"
    error: str | None = None


def _resolve_subagent_tools(
    available: list[dict[str, Any]],
    ctx: AppContext,
    allowed: list[str] | None,
    max_tools: int,
) -> list[dict[str, Any]]:
    """Filter the available toolset down to what a sub-agent may use.

    Excludes the agent meta-tools, confirmation-gated / dangerous tools and
    client-executed tools (no UI to run them in a sub-agent), then optionally
    restricts to the caller-supplied ``allowed`` allow-list.
    """
    registry = ctx.tool_registry
    selected: list[dict[str, Any]] = []
    for entry in available:
        name = entry["function"]["name"]
        if name in BLOCKED_TOOL_NAMES:
            continue
        if registry is not None:
            tool_def = registry.get_tool_definition(name)
            if tool_def is not None and (
                tool_def.requires_confirmation
                or tool_def.risk_level in ("dangerous", "forbidden")
                or tool_def.client_execution
            ):
                continue
        if allowed and not any(
            name == a or name.endswith(f"_{a}") for a in allowed
        ):
            continue
        selected.append(entry)
        if len(selected) >= max_tools:
            break
    return selected


def _gate_tool_call(
    ctx: AppContext, name: str, args: dict[str, Any], conversation_id: str,
) -> str | None:
    """Consult the central permission gate for one sub-agent tool call.

    Same policy as a normal turn (spec §4.5/§8: no privileged path): the
    PARENT conversation's permission mode and scope apply. Accessed via
    ``ctx`` duck-typed — plugins never import services classes directly.

    Returns:
        ``None`` when allowed, else the human-readable denial.
    """
    permission_service = getattr(ctx, "permission_service", None)
    if permission_service is None:
        return None
    registry = ctx.tool_registry
    tool_def = registry.get_tool_definition(name) if registry is not None else None
    mode_service = getattr(ctx, "permission_mode_service", None)
    mode = mode_service.get_mode(conversation_id) if mode_service is not None else None
    denial: str | None = permission_service.explain_denial(
        tool_name=name,
        args=args,
        tool_def=tool_def,
        conversation_id=conversation_id,
        mode=mode,
    )
    return denial


async def _run_loop(
    *,
    ctx: AppContext,
    task: str,
    context: str | None,
    tools: list[dict[str, Any]],
    max_steps: int,
    max_output_tokens: int,
    conversation_id: str,
    session_id: str,
    cancel_event: asyncio.Event,
    result: SubagentResult,
    progress_cb: ProgressCallback | None = None,
) -> None:
    """Drive the sub-agent tool-loop, mutating *result* in place."""
    llm = ctx.llm_service
    registry = ctx.tool_registry
    if llm is None or registry is None:  # pragma: no cover - guarded by caller
        result.stop_reason = "error"
        result.error = "LLM service or tool registry unavailable"
        return

    user_block = task if not context else f"{task}\n\nContext:\n{context}"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SUBAGENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_block},
    ]

    for step in range(max_steps):
        result.steps_used = step + 1
        if progress_cb is not None:
            with contextlib.suppress(Exception):
                await progress_cb(step + 1, max_steps, f"step {step + 1}/{max_steps}")
        content_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        errored: str | None = None

        async for event in llm.chat(
            messages,
            tools=tools,
            cancel_event=cancel_event,
            max_output_tokens=max_output_tokens,
        ):
            etype = event.get("type")
            if etype == "token":
                content_parts.append(event.get("content", ""))
            elif etype == "tool_call":
                tool_calls.append(event)
            elif etype == "usage":
                result.input_tokens += int(event.get("input_tokens", 0) or 0)
                result.output_tokens += int(event.get("output_tokens", 0) or 0)
            elif etype == "error":
                errored = event.get("content", "unknown LLM error")

        if errored is not None:
            result.stop_reason = "error"
            result.error = errored
            return

        content = "".join(content_parts).strip()

        if not tool_calls:
            result.summary = content
            result.stop_reason = "completed"
            return

        messages.append(
            {
                "role": "assistant",
                "content": content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": tc["function"],
                    }
                    for tc in tool_calls
                ],
            },
        )

        for tool_call in tool_calls:
            fn = tool_call["function"]
            name = fn["name"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}

            denial = _gate_tool_call(ctx, name, args, conversation_id)
            if denial is not None:
                result.tools_called.append(name)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": f"ERROR: {denial}",
                    },
                )
                continue

            exec_ctx = ExecutionContext(
                session_id=session_id,
                conversation_id=conversation_id,
                execution_id=str(uuid.uuid4()),
            )
            tool_result = await registry.execute_tool(name, args, exec_ctx)
            result.tools_called.append(name)
            payload = (
                tool_result.content
                if tool_result.success
                else f"ERROR: {tool_result.error_message}"
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": payload
                    if isinstance(payload, str)
                    else json.dumps(payload, default=str),
                },
            )

    result.stop_reason = "max_steps"
    if not result.summary:
        result.summary = (
            "Sub-agent reached its step budget before producing a final "
            "answer. Partial findings are in the tool results above."
        )


async def run_subagent(
    *,
    ctx: AppContext,
    task: str,
    context: str | None,
    allowed_tools: list[str] | None,
    max_steps: int,
    max_output_tokens: int,
    timeout_seconds: float,
    max_tools: int,
    conversation_id: str,
    session_id: str,
    progress_cb: ProgressCallback | None = None,
) -> SubagentResult:
    """Run a sub-agent to completion and return its result.

    Args:
        ctx: The shared application context (provides LLM + tool registry).
        task: The self-contained task for the sub-agent.
        context: Optional extra context distilled by the parent.
        allowed_tools: Optional allow-list of tool names (bare or namespaced).
        max_steps: Tool-loop iteration cap.
        max_output_tokens: Per-step output token cap.
        timeout_seconds: Wall-clock budget for the whole run.
        max_tools: Maximum number of tools to expose to the sub-agent.
        conversation_id: Parent conversation id (for tool execution context).
        session_id: Parent session id (for tool execution context).
        progress_cb: Optional per-step progress reporter (Fase 8 observability).

    Returns:
        A :class:`SubagentResult` — never raises.
    """
    result = SubagentResult()
    if ctx.llm_service is None or ctx.tool_registry is None:
        result.stop_reason = "error"
        result.error = "LLM service or tool registry unavailable"
        return result

    available = await ctx.tool_registry.get_available_tools()
    tools = _resolve_subagent_tools(available, ctx, allowed_tools, max_tools)

    cancel_event = asyncio.Event()
    try:
        await asyncio.wait_for(
            _run_loop(
                ctx=ctx,
                task=task,
                context=context,
                tools=tools,
                max_steps=max_steps,
                max_output_tokens=max_output_tokens,
                conversation_id=conversation_id,
                session_id=session_id,
                cancel_event=cancel_event,
                result=result,
                progress_cb=progress_cb,
            ),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        cancel_event.set()
        result.stop_reason = "timeout"
        if not result.summary:
            result.summary = (
                "Sub-agent timed out before producing a final answer."
            )
    except asyncio.CancelledError:
        cancel_event.set()
        result.stop_reason = "cancelled"
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Sub-agent run failed")
        result.stop_reason = "error"
        result.error = str(exc)

    return result
