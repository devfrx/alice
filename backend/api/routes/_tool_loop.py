"""O.M.N.I.A. — Tool calling loop for the WebSocket chat handler.

Handles iterative LLM ↔ tool execution cycles, deduplication,
user confirmation for dangerous tools, and graceful error recovery.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Coroutine

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from sqlmodel import select

from backend.core.context import AppContext
from backend.core.plugin_models import ExecutionContext, ToolResult
from backend.db.models import Conversation, Message
from backend.services.llm_service import LLMService

# Type alias for the sync callback.
SyncFn = Callable[..., Coroutine[Any, Any, None]]


async def run_tool_loop(
    *,
    websocket: WebSocket,
    ctx: AppContext,
    session: Any,
    conv_id: uuid.UUID,
    conv: Conversation,
    llm: LLMService,
    tool_calls_from_llm: list[dict[str, Any]],
    full_content: str,
    thinking_content: str,
    max_iterations: int,
    confirmation_timeout_s: int,
    client_ip: str,
    sync_fn: SyncFn | None,
    cancel_event: asyncio.Event | None = None,
) -> tuple[str, str]:
    """Execute the tool-calling loop until the LLM produces a final answer.

    Iterates up to *max_iterations* rounds.  In each round the assistant
    message (with ``tool_calls``) is persisted, every requested tool is
    executed (in parallel), results are saved as ``role="tool"`` messages,
    and the LLM is re-queried with the updated history.

    Args:
        websocket: The active WebSocket connection.
        ctx: Application context (tool registry, config, etc.).
        session: Active async DB session (caller manages commit).
        conv_id: Current conversation UUID.
        conv: The Conversation ORM object.
        llm: LLMService instance for re-querying.
        tool_calls_from_llm: Initial tool calls from the first LLM response.
        full_content: Text content from the first LLM response.
        thinking_content: Thinking tokens from the first LLM response.
        max_iterations: Safety cap on loop iterations.
        confirmation_timeout_s: Seconds to wait for user confirmation.
        client_ip: Client IP used as session_id in ExecutionContext.
        sync_fn: Async callback to sync conversation to JSON file.
        cancel_event: Optional event that, when set, signals the loop
            to stop early and return accumulated content.

    Returns:
        ``(full_content, thinking_content)`` of the final LLM response
        (the one with no further tool calls).
    """
    for iteration in range(max_iterations):
        if not tool_calls_from_llm:
            break

        # Check for cancellation at the start of each iteration.
        if cancel_event and cancel_event.is_set():
            logger.debug("Tool loop cancelled at iteration {}", iteration + 1)
            break

        logger.info(
            "Tool loop iteration {}/{} — {} tool call(s)",
            iteration + 1, max_iterations, len(tool_calls_from_llm),
        )

        # 1. Save assistant message with tool_calls to DB.
        asst_msg = Message(
            conversation_id=conv_id,
            role="assistant",
            content=full_content,
            tool_calls=[
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": tc["function"],
                }
                for tc in tool_calls_from_llm
            ],
            thinking_content=thinking_content or None,
        )
        session.add(asst_msg)
        await session.flush()

        # 2. Build execution tasks — dedup and check confirmation.
        seen: set[tuple[str, str]] = set()
        tasks: list[tuple[str, str, dict[str, Any], ExecutionContext]] = []

        for tc in tool_calls_from_llm:
            tool_name = tc["function"]["name"]
            raw_args = tc["function"].get("arguments", "{}") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}

            dedup_key = (tool_name, json.dumps(args, sort_keys=True))
            if dedup_key in seen:
                logger.warning(
                    "Dedup: skipping duplicate tool call {}(…)", tool_name,
                )
                # OpenAI API requires a tool response for EVERY tool_call_id.
                session.add(Message(
                    conversation_id=conv_id,
                    role="tool",
                    content="Duplicate call — see prior result.",
                    tool_call_id=tc["id"],
                ))
                continue
            seen.add(dedup_key)

            exec_id = str(uuid.uuid4())

            # Check if tool requires user confirmation.
            tool_def = (
                ctx.tool_registry.get_tool_definition(tool_name)
                if ctx.tool_registry
                else None
            )
            if tool_def and tool_def.requires_confirmation:
                approved = await _request_confirmation(
                    websocket, tool_name, args, exec_id,
                    confirmation_timeout_s,
                )
                if not approved:
                    _save_rejected_tool_msg(
                        session, conv_id, tc["id"],
                    )
                    await websocket.send_json({
                        "type": "tool_execution_done",
                        "tool_name": tool_name,
                        "result": "Tool execution rejected or timed out.",
                        "execution_id": exec_id,
                        "success": False,
                    })
                    continue

            await websocket.send_json({
                "type": "tool_execution_start",
                "tool_name": tool_name,
                "execution_id": exec_id,
            })

            context = ExecutionContext(
                session_id=client_ip,
                conversation_id=str(conv_id),
                execution_id=exec_id,
            )
            tasks.append((tc["id"], tool_name, args, context))

        # 3. Execute all tools in parallel.
        results = await asyncio.gather(
            *[_exec_one(ctx, tc_id, name, a, c) for tc_id, name, a, c in tasks],
            return_exceptions=True,
        )

        # 4. Process results — persist and notify WS.
        # NOTE: Cancel check is AFTER persistence to avoid orphaned tool_calls
        # in the DB (OpenAI API requires a tool response for every tool_call_id).
        for idx, res in enumerate(results):
            if isinstance(res, BaseException):
                logger.error("Tool execution exception: {}", res)
                # Save an error tool message to satisfy the OpenAI contract.
                failed_tc_id = tasks[idx][0]
                failed_tool_name = tasks[idx][1]
                session.add(Message(
                    conversation_id=conv_id,
                    role="tool",
                    content=f"Tool execution failed: {res}",
                    tool_call_id=failed_tc_id,
                ))
                await websocket.send_json({
                    "type": "tool_execution_done",
                    "tool_name": failed_tool_name,
                    "result": f"Tool execution failed: {res}",
                    "execution_id": tasks[idx][3].execution_id,
                    "success": False,
                })
                continue

            tc_id, tool_name, tool_result, exec_id = res

            content = _result_to_str(tool_result)

            tool_msg = Message(
                conversation_id=conv_id,
                role="tool",
                content=content,
                tool_call_id=tc_id,
            )
            session.add(tool_msg)

            await websocket.send_json({
                "type": "tool_execution_done",
                "tool_name": tool_name,
                "result": content,
                "execution_id": exec_id,
                "success": tool_result.success,
            })

        await session.flush()

        # Check for cancellation AFTER results are persisted (DB consistent).
        if cancel_event and cancel_event.is_set():
            logger.debug("Tool loop cancelled after tool execution")
            break

        # 5. Sync conversation to JSON file.
        if ctx.conversation_file_manager and sync_fn:
            await sync_fn(session, conv_id, ctx.conversation_file_manager)

        # 6. Rebuild messages from full DB history and re-query LLM.
        stmt = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at)
        )
        results_db = await session.exec(stmt)
        updated_history: list[dict[str, Any]] = [
            {
                "role": m.role,
                "content": m.content,
                "tool_calls": m.tool_calls,
                "tool_call_id": m.tool_call_id,
            }
            for m in results_db.all()
        ]

        tools = (
            await ctx.tool_registry.get_available_tools()
            if ctx.tool_registry
            else None
        )
        if tools is not None and len(tools) == 0:
            tools = None  # empty list confuses some LLMs

        messages = llm.build_continuation_messages(history=updated_history)

        # 7. Re-stream LLM.
        full_content = ""
        thinking_content = ""
        tool_calls_from_llm = []

        await websocket.send_json({
            "type": "llm_requery",
            "iteration": iteration + 1,
        })

        async for event in llm.chat(
            messages, tools=tools, cancel_event=cancel_event,
        ):
            if event["type"] == "token":
                full_content += event["content"]
                await websocket.send_json(event)
            elif event["type"] == "thinking":
                thinking_content += event["content"]
                await websocket.send_json(event)
            elif event["type"] == "tool_call":
                tool_calls_from_llm.append(event)
            elif event["type"] == "done":
                pass

    else:
        # Loop exhausted max_iterations without a clean break.
        if tool_calls_from_llm:
            logger.warning(
                "Tool loop hit max iterations ({}) — forcing final answer",
                max_iterations,
            )
            await websocket.send_json({
                "type": "warning",
                "content": f"Tool loop exceeded maximum iterations ({max_iterations}). Returning partial response.",
            })

    return full_content, thinking_content


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _exec_one(
    ctx: AppContext,
    tc_id: str,
    name: str,
    args: dict[str, Any],
    context: ExecutionContext,
) -> tuple[str, str, ToolResult, str]:
    """Execute a single tool and return its result alongside metadata."""
    result = await ctx.tool_registry.execute_tool(name, args, context)
    return tc_id, name, result, context.execution_id


def _result_to_str(tool_result: ToolResult) -> str:
    """Coerce a ``ToolResult`` payload into a plain string."""
    content = tool_result.content
    if isinstance(content, dict):
        return json.dumps(content)
    if content is None:
        return tool_result.error_message or "No result"
    return str(content)


def _save_rejected_tool_msg(
    session: Any,
    conv_id: uuid.UUID,
    tool_call_id: str,
) -> None:
    """Persist a tool message recording that execution was rejected."""
    msg = Message(
        conversation_id=conv_id,
        role="tool",
        content="Tool execution was rejected by user or timed out.",
        tool_call_id=tool_call_id,
    )
    session.add(msg)


async def _request_confirmation(
    websocket: WebSocket,
    tool_name: str,
    args: dict[str, Any],
    execution_id: str,
    timeout_s: int,
) -> bool:
    """Send a confirmation request and wait for the user's response.

    Sends a ``tool_confirmation_required`` WS message and blocks until
    a matching ``tool_confirmation_response`` arrives or *timeout_s*
    elapses.

    Args:
        websocket: Active WebSocket connection.
        tool_name: Name of the tool requiring confirmation.
        args: Arguments the tool will be called with.
        execution_id: Unique execution ID for correlation.
        timeout_s: Maximum seconds to wait.

    Returns:
        ``True`` if the user approved, ``False`` on rejection or timeout.
    """
    await websocket.send_json({
        "type": "tool_confirmation_required",
        "tool_name": tool_name,
        "args": args,
        "execution_id": execution_id,
    })

    deadline = asyncio.get_event_loop().time() + timeout_s
    try:
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=remaining,
            )
            msg = json.loads(raw)
            if (
                msg.get("type") == "tool_confirmation_response"
                and msg.get("execution_id") == execution_id
            ):
                return bool(msg.get("approved", False))
    except asyncio.TimeoutError:
        logger.warning(
            "Confirmation timed out for tool '{}' (exec_id={})",
            tool_name, execution_id,
        )
        return False
    except WebSocketDisconnect:
        raise
    except (json.JSONDecodeError, Exception):
        logger.warning(
            "Error receiving confirmation for tool '{}' (exec_id={})",
            tool_name, execution_id,
        )
        return False
