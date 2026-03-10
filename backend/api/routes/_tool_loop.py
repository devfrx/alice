"""O.M.N.I.A. — Tool calling loop for the WebSocket chat handler.

Handles iterative LLM ↔ tool execution cycles, deduplication,
user confirmation for dangerous tools, and graceful error recovery.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from typing import Any, Callable, Coroutine

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger
from sqlmodel import select

from backend.core.context import AppContext
from backend.core.plugin_models import ExecutionContext, ToolResult
from backend.db.models import Message, ToolConfirmationAudit
from backend.services.llm_service import LLMService

# Type alias for the sync callback.
SyncFn = Callable[..., Coroutine[Any, Any, None]]


async def run_tool_loop(
    *,
    websocket: WebSocket,
    ctx: AppContext,
    session: Any,
    conv_id: uuid.UUID,
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
    if ctx.tool_registry is None:
        logger.error("Tool registry not available, cannot execute tool loop")
        return full_content, thinking_content

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

        # Normalise tool-call IDs upfront so assistant msg and tool
        # responses always use the same value.
        for tc in tool_calls_from_llm:
            if not tc.get("id"):
                tc["id"] = f"call_{uuid.uuid4().hex[:24]}"

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
            tc_id = tc["id"]
            fn = tc.get("function") or {}
            tool_name = fn.get("name", "")
            if not tool_name:
                logger.warning(
                    "Skipping tool call with no function name: {}", tc,
                )
                if tc_id:
                    session.add(Message(
                        conversation_id=conv_id,
                        role="tool",
                        content="Error: tool call has no function name.",
                        tool_call_id=tc_id,
                    ))
                    await session.flush()
                continue

            raw_args = fn.get("arguments", "{}") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Invalid JSON args for tool '{}': {}",
                    tool_name, raw_args[:200],
                )
                session.add(Message(
                    conversation_id=conv_id,
                    role="tool",
                    content=f"Error: could not parse arguments \u2014 {e}",
                    tool_call_id=tc_id,
                ))
                await session.flush()
                await websocket.send_json({
                    "type": "tool_execution_done",
                    "tool_name": tool_name,
                    "result": f"Error: could not parse arguments \u2014 {e}",
                    "execution_id": str(uuid.uuid4()),
                    "success": False,
                })
                continue

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
                    tool_call_id=tc_id,
                ))
                await session.flush()  # Ensure dedup response persisted immediately
                continue
            seen.add(dedup_key)

            exec_id = str(uuid.uuid4())

            # Check if tool requires user confirmation.
            tool_def = (
                ctx.tool_registry.get_tool_definition(tool_name)
                if ctx.tool_registry
                else None
            )

            # FORBIDDEN enforcement — block tools with risk_level "forbidden"
            if tool_def and tool_def.risk_level == "forbidden":
                logger.warning(
                    "Blocked FORBIDDEN tool '{}' (exec_id={})",
                    tool_name, exec_id,
                )
                _save_rejected_tool_msg(session, conv_id, tc_id)
                await session.flush()
                await websocket.send_json({
                    "type": "tool_execution_done",
                    "tool_name": tool_name,
                    "result": "Tool is forbidden and cannot be executed.",
                    "execution_id": exec_id,
                    "success": False,
                })
                # Log audit entry for forbidden tool
                audit_entry = ToolConfirmationAudit(
                    conversation_id=conv_id,
                    execution_id=exec_id,
                    tool_name=tool_name,
                    args_json=json.dumps(args, default=str),
                    risk_level="forbidden",
                    user_approved=False,
                    rejection_reason="forbidden_tool",
                    thinking_content=thinking_content or None,
                )
                session.add(audit_entry)
                await session.flush()
                continue

            if tool_def and tool_def.requires_confirmation:
                # Check if confirmations are globally disabled in config
                confirmations_on = True
                if hasattr(ctx.config, "pc_automation"):
                    confirmations_on = ctx.config.pc_automation.confirmations_enabled

                if confirmations_on:
                    approved = await _request_confirmation(
                        websocket, tool_name, args, exec_id,
                        confirmation_timeout_s,
                        risk_level=tool_def.risk_level,
                        description=tool_def.description,
                        reasoning=thinking_content,
                        cancel_event=cancel_event,
                    )
                else:
                    logger.info(
                        "Confirmations disabled — auto-approving '{}' (exec_id={})",
                        tool_name, exec_id,
                    )
                    approved = True

                # Log audit entry for confirmation decision
                audit_entry = ToolConfirmationAudit(
                    conversation_id=conv_id,
                    execution_id=exec_id,
                    tool_name=tool_name,
                    args_json=json.dumps(args, default=str),
                    risk_level=tool_def.risk_level,
                    user_approved=approved,
                    rejection_reason=None if approved else "user_rejected",
                    thinking_content=thinking_content or None,
                )
                session.add(audit_entry)
                await session.flush()

                if not approved:
                    _save_rejected_tool_msg(
                        session, conv_id, tc_id,
                    )
                    await session.flush()  # Persist rejection immediately
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
            tasks.append((tc_id, tool_name, args, context))

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
                if not isinstance(res, Exception):
                    raise res
                # Save an error tool message to satisfy the OpenAI contract.
                failed_tc_id = tasks[idx][0]
                failed_tool_name = tasks[idx][1]
                logger.error(
                    "Tool execution exception for '{}': {}",
                    failed_tool_name, res,
                )
                session.add(Message(
                    conversation_id=conv_id,
                    role="tool",
                    content=f"Tool '{failed_tool_name}' execution failed.",
                    tool_call_id=failed_tc_id,
                ))
                await websocket.send_json({
                    "type": "tool_execution_done",
                    "tool_name": failed_tool_name,
                    "result": f"Tool '{failed_tool_name}' execution failed.",
                    "execution_id": tasks[idx][3].execution_id,
                    "success": False,
                })
                continue

            tc_id, tool_name, tool_result, exec_id = res

            content = _result_to_str(tool_result)
            is_image = (
                tool_result.content_type is not None
                and tool_result.content_type.startswith("image/")
            )

            # For images: store a short placeholder in DB (sent to
            # the LLM on re-query) and send the full base64 only to
            # the frontend for rendering.
            db_content = "[Screenshot captured successfully]" if is_image else content

            tool_msg = Message(
                conversation_id=conv_id,
                role="tool",
                content=db_content,
                tool_call_id=tc_id,
            )
            session.add(tool_msg)

            ws_payload: dict[str, Any] = {
                "type": "tool_execution_done",
                "tool_name": tool_name,
                "result": content,
                "execution_id": exec_id,
                "success": tool_result.success,
            }
            if tool_result.content_type:
                ws_payload["content_type"] = tool_result.content_type

            await websocket.send_json(ws_payload)

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
        updated_history: list[dict[str, Any]] = []
        for m in results_db.all():
            entry: dict[str, Any] = {"role": m.role, "content": m.content or ""}
            if m.role == "assistant" and m.tool_calls:
                entry["tool_calls"] = m.tool_calls
            if m.role == "tool" and m.tool_call_id:
                entry["tool_call_id"] = m.tool_call_id
            updated_history.append(entry)

        _tools_enabled = getattr(
            getattr(ctx.config, "llm", None), "tools_enabled", True
        )
        tools = (
            await ctx.tool_registry.get_available_tools()
            if ctx.tool_registry and _tools_enabled
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

        # Spawn a reader task so cancel messages are detected during streaming.
        reader_task = asyncio.create_task(
            _ws_cancel_reader(websocket, cancel_event),
        ) if cancel_event else None

        try:
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
        finally:
            if reader_task and not reader_task.done():
                reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader_task

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
    if isinstance(content, (dict, list)):
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
    risk_level: str = "medium",
    description: str = "",
    reasoning: str = "",
    cancel_event: asyncio.Event | None = None,
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
        risk_level: Risk classification (``"safe"``, ``"medium"``,
            ``"dangerous"``, ``"forbidden"``).
        description: Human-readable description of the tool action.
        reasoning: LLM thinking/reasoning content at invocation time.
        cancel_event: Optional event to set when a cancel message arrives.

    Returns:
        ``True`` if the user approved, ``False`` on rejection or timeout.
    """
    await websocket.send_json({
        "type": "tool_confirmation_required",
        "tool_name": tool_name,
        "args": args,
        "execution_id": execution_id,
        "risk_level": risk_level,
        "description": description,
        "reasoning": reasoning,
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
            # Handle cancel messages during confirmation wait.
            if msg.get("type") == "cancel":
                if cancel_event:
                    cancel_event.set()
                return False
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
        logger.warning(
            "WebSocket disconnected during confirmation for tool '{}' (exec_id={})",
            tool_name, execution_id,
        )
        return False
    except (json.JSONDecodeError, Exception):
        logger.warning(
            "Error receiving confirmation for tool '{}' (exec_id={})",
            tool_name, execution_id,
        )
        return False


async def _ws_cancel_reader(
    websocket: WebSocket,
    cancel_event: asyncio.Event | None,
) -> None:
    """Read WebSocket messages in the background during LLM re-streaming.

    Sets *cancel_event* when a ``{"type": "cancel"}`` message arrives.
    Any non-cancel messages are silently discarded (the main loop handles
    only LLM stream events during this phase).
    """
    if cancel_event is None:
        return
    try:
        while not cancel_event.is_set():
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "cancel":
                cancel_event.set()
                return
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception:
        logger.debug("WS cancel reader stopped unexpectedly")
