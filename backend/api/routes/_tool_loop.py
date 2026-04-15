"""AL\\CE — Tool calling loop for the WebSocket chat handler.

Handles iterative LLM ↔ tool execution cycles, deduplication,
user confirmation for dangerous tools, and graceful error recovery.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import uuid
from typing import Any, Callable, Coroutine

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from backend.core.context import AppContext
from backend.core.plugin_models import ExecutionContext, ToolResult
from backend.db.models import Message, ToolConfirmationAudit
from backend.services.llm_service import LLMService

# Type alias for the sync callback.
SyncFn = Callable[..., Coroutine[Any, Any, None]]

# Max retries when the LLM returns an empty response during re-query.
# Local models occasionally produce empty completions after tool results;
# retrying typically succeeds on the next attempt.
_EMPTY_REQUERY_RETRIES = 2


def _dedup_hash(tool_name: str, args: dict[str, Any]) -> str:
    """Return a compact hash for deduplication of identical tool calls.

    Normalizes paths (forward-slash only) and produces a SHA-256 digest
    instead of holding full JSON strings in memory.
    """
    canonical = json.dumps(args, sort_keys=True, default=str)
    canonical = canonical.replace("\\\\", "/")
    raw = f"{tool_name}:{canonical}"
    return hashlib.sha256(raw.encode()).hexdigest()


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
    memory_context: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    initial_history: list[dict[str, Any]] | None = None,
    system_prompt: str | None = None,
    version_group_id: uuid.UUID | None = None,
    version_index: int = 0,
    context_window: int = 0,
) -> tuple[str, str, int, int, str]:
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
        memory_context: Optional pre-formatted memory block to inject
            into the system prompt on each LLM re-query.
        tools: Pre-fetched tool definitions (avoids re-fetching each
            iteration).  When ``None``, tools are fetched from the
            registry on each re-query (legacy fallback).
        initial_history: Conversation history at the start of the tool
            loop.  When provided, the loop maintains an in-memory copy
            instead of re-querying the DB on each iteration.
        system_prompt: Pre-built system prompt.  When provided, it is
            forwarded to ``build_continuation_messages`` and ``llm.chat``
            so the prompt is not rebuilt on every iteration.

    Returns:
        ``(full_content, thinking_content, last_input_tokens,
        last_output_tokens, finish_reason)`` of the final LLM response
        (the one with no further tool calls).
    """
    if ctx.tool_registry is None:
        logger.error("Tool registry not available, cannot execute tool loop")
        return full_content, thinking_content, 0, 0, "stop"

    llm_error_in_requery = False

    # In-memory history: maintained across iterations so we never
    # re-fetch from DB during the loop.  Falls back to None which
    # triggers the legacy DB-based re-fetch path.
    mem_history: list[dict[str, Any]] | None = (
        list(initial_history) if initial_history is not None else None
    )

    # Version metadata applied to every message created in this loop.
    _ver = {
        "version_group_id": version_group_id,
        "version_index": version_index,
    }

    # Tool execution timeout from config.
    tool_exec_timeout: float = ctx.config.llm.tool_execution_timeout

    # Dedup set persists across all iterations to catch duplicates
    # even when LLM re-requests the same tool in a later round.
    seen: set[str] = set()

    # Track usage and finish_reason from the last LLM re-query so
    # the caller can use real token data for context management.
    _loop_last_input_tokens = 0
    _loop_last_output_tokens = 0
    _loop_finish_reason = "stop"

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
        normalized_tcs = [
            {
                "id": tc["id"],
                "type": "function",
                "function": tc["function"],
            }
            for tc in tool_calls_from_llm
        ]
        asst_msg = Message(
            conversation_id=conv_id,
            role="assistant",
            content=full_content,
            tool_calls=normalized_tcs,
            thinking_content=thinking_content or None,
            version_group_id=version_group_id,
            version_index=version_index,
        )
        session.add(asst_msg)
        await session.flush()

        # Append the assistant message to in-memory history.
        if mem_history is not None:
            mem_history.append({
                "role": "assistant",
                "content": full_content or "",
                "tool_calls": normalized_tcs,
            })

        # 2. Build execution tasks — dedup and check confirmation.
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
                    _err_content = "Error: tool call has no function name."
                    session.add(Message(
                        conversation_id=conv_id,
                        role="tool",
                        content=_err_content,
                        tool_call_id=tc_id,
                        **_ver,
                    ))
                    await session.flush()
                    if mem_history is not None:
                        mem_history.append({
                            "role": "tool",
                            "content": _err_content,
                            "tool_call_id": tc_id,
                        })
                continue

            raw_args = fn.get("arguments", "{}") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Invalid JSON args for tool '{}': {}",
                    tool_name, raw_args[:200],
                )
                _parse_err = f"Error: could not parse arguments \u2014 {e}"
                session.add(Message(
                    conversation_id=conv_id,
                    role="tool",
                    content=_parse_err,
                    tool_call_id=tc_id,
                    **_ver,
                ))
                await session.flush()
                if mem_history is not None:
                    mem_history.append({
                        "role": "tool",
                        "content": _parse_err,
                        "tool_call_id": tc_id,
                    })
                await websocket.send_json({
                    "type": "tool_execution_done",
                    "tool_name": tool_name,
                    "result": _parse_err,
                    "execution_id": str(uuid.uuid4()),
                    "success": False,
                })
                continue

            dedup_key = _dedup_hash(tool_name, args)
            if dedup_key in seen:
                logger.warning(
                    "Dedup: skipping duplicate tool call {}(…)", tool_name,
                )
                # OpenAI API requires a tool response for EVERY tool_call_id.
                _dedup_content = "Duplicate call \u2014 see prior result."
                session.add(Message(
                    conversation_id=conv_id,
                    role="tool",
                    content=_dedup_content,
                    tool_call_id=tc_id,
                    **_ver,
                ))
                await session.flush()
                if mem_history is not None:
                    mem_history.append({
                        "role": "tool",
                        "content": _dedup_content,
                        "tool_call_id": tc_id,
                    })
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
                _save_rejected_tool_msg(session, conv_id, tc_id, **_ver)
                await session.flush()
                if mem_history is not None:
                    mem_history.append({
                        "role": "tool",
                        "content": "Tool execution was rejected by user or timed out.",
                        "tool_call_id": tc_id,
                    })
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
                        session, conv_id, tc_id, **_ver,
                    )
                    await session.flush()
                    if mem_history is not None:
                        mem_history.append({
                            "role": "tool",
                            "content": "Tool execution was rejected by user or timed out.",
                            "tool_call_id": tc_id,
                        })
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

        # Release the SQLite write lock held by pending flush()es so that
        # plugin tools can write to the DB on their own connections.
        await session.commit()

        # 3. Execute all tools in parallel (with timeout).
        coros = [
            asyncio.ensure_future(_exec_one(ctx, tc_id, name, a, c))
            for tc_id, name, a, c in tasks
        ]
        if coros:
            done, pending = await asyncio.wait(
                coros, timeout=tool_exec_timeout,
            )
        else:
            done, pending = set(), set()

        # Build a lookup from future to task metadata — used for
        # both pending (timeout) and done (exception) handling.
        future_to_task = dict(zip(coros, tasks))

        if pending:
            logger.error(
                "Tool execution timed out after {}s — {} task(s) still pending",
                tool_exec_timeout, len(pending),
            )
            # Cancel and report timeout only for pending tasks.
            for fut in pending:
                fut.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await fut
            for fut in pending:
                tc_id, tool_name, _, exec_ctx = future_to_task[fut]
                _timeout_content = (
                    f"Tool '{tool_name}' timed out after "
                    f"{tool_exec_timeout}s."
                )
                session.add(Message(
                    conversation_id=conv_id,
                    role="tool",
                    content=_timeout_content,
                    tool_call_id=tc_id,
                    **_ver,
                ))
                if mem_history is not None:
                    mem_history.append({
                        "role": "tool",
                        "content": _timeout_content,
                        "tool_call_id": tc_id,
                    })
                await websocket.send_json({
                    "type": "tool_execution_done",
                    "tool_name": tool_name,
                    "result": _timeout_content,
                    "execution_id": exec_ctx.execution_id,
                    "success": False,
                })
            await session.commit()

        # 4. Process results — persist and notify WS.
        # NOTE: Cancel check is AFTER persistence to avoid orphaned tool_calls
        # in the DB (OpenAI API requires a tool response for every tool_call_id).
        for fut in done:
            exc = fut.exception()
            if exc is not None:
                if not isinstance(exc, Exception):
                    raise exc
                # Look up the correct task metadata via the future,
                # NOT by index — `done` is a set with arbitrary order.
                failed_tc_id, failed_tool_name, _, failed_ctx = future_to_task[fut]
                logger.error(
                    "Tool execution exception for '{}': {}",
                    failed_tool_name, exc,
                )
                _fail_content = f"Tool '{failed_tool_name}' execution failed."
                session.add(Message(
                    conversation_id=conv_id,
                    role="tool",
                    content=_fail_content,
                    tool_call_id=failed_tc_id,
                    **_ver,
                ))
                if mem_history is not None:
                    mem_history.append({
                        "role": "tool",
                        "content": _fail_content,
                        "tool_call_id": failed_tc_id,
                    })
                await websocket.send_json({
                    "type": "tool_execution_done",
                    "tool_name": failed_tool_name,
                    "result": f"Tool '{failed_tool_name}' execution failed.",
                    "execution_id": failed_ctx.execution_id,
                    "success": False,
                })
                continue

            tc_id, tool_name, tool_result, exec_id = fut.result()

            content = _result_to_str(tool_result)
            is_image = (
                tool_result.content_type is not None
                and tool_result.content_type.startswith("image/")
            )

            # For images: persist the base64 data to a file so the
            # frontend can retrieve it on page reload, and store a
            # descriptive placeholder in the DB for the LLM context.
            if is_image:
                image_ref = await _persist_tool_image(
                    conv_id, exec_id, content, tool_result.content_type,
                )
                db_content = (
                    f"[Image captured — ref:{image_ref}]"
                    if image_ref
                    else "[Screenshot captured successfully]"
                )
            else:
                db_content = content

            tool_msg = Message(
                conversation_id=conv_id,
                role="tool",
                content=db_content,
                tool_call_id=tc_id,
                **_ver,
            )
            session.add(tool_msg)

            # Append to in-memory history so DB re-fetch is avoided.
            if mem_history is not None:
                mem_history.append({
                    "role": "tool",
                    "content": db_content,
                    "tool_call_id": tc_id,
                })

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

        await session.commit()

        # Check for cancellation AFTER results are persisted (DB consistent).
        if cancel_event and cancel_event.is_set():
            logger.debug("Tool loop cancelled after tool execution")
            break

        # 5. Sync conversation to JSON file.
        if ctx.conversation_file_manager and sync_fn:
            await sync_fn(session, conv_id, ctx.conversation_file_manager)

        # 6. Build messages for re-query — use in-memory history when
        #    available, otherwise fall back to a DB fetch (legacy path).
        if mem_history is not None:
            updated_history = mem_history
        else:
            from sqlmodel import select as _select
            stmt = (
                _select(Message)
                .where(Message.conversation_id == conv_id)
                .where(Message.context_excluded == False)  # noqa: E712
                .order_by(Message.created_at)
            )
            results_db = await session.exec(stmt)
            updated_history = []
            for m in results_db.all():
                entry: dict[str, Any] = {
                    "role": m.role, "content": m.content or "",
                }
                if m.role == "assistant" and m.tool_calls:
                    entry["tool_calls"] = m.tool_calls
                if m.role == "tool" and m.tool_call_id:
                    entry["tool_call_id"] = m.tool_call_id
                updated_history.append(entry)

        messages = llm.build_continuation_messages(
            history=updated_history,
            memory_context=memory_context,
            system_prompt=system_prompt,
        )

        # Per-iteration context compression check.
        if (
            context_window > 0
            and ctx.context_manager is not None
            and ctx.config.llm.context_compression_enabled
        ):
            # Estimate tool tokens so the compression target budget is accurate.
            _tool_tokens_iter = (
                ctx.context_manager.estimate_tokens(
                    json.dumps(tools, ensure_ascii=False),
                )
                if tools
                else 0
            )
            iter_usage = ctx.context_manager.get_usage_estimated(
                messages, context_window,
            )
            # Add tool tokens to usage estimate before deciding to compress.
            if _tool_tokens_iter > 0:
                iter_usage.used_tokens += _tool_tokens_iter
                iter_usage.available_tokens = max(
                    0, context_window - iter_usage.used_tokens,
                )
                iter_usage.percentage = (
                    round(iter_usage.used_tokens / context_window, 4)
                    if context_window > 0 else 0.0
                )
            if ctx.context_manager.should_compress(iter_usage):
                await websocket.send_json(
                    {"type": "context_compression_start"},
                )
                try:
                    iter_comp = await ctx.context_manager.compress(
                        messages, llm, context_window,
                        ctx.config.llm.context_compression_reserve,
                        tool_tokens=_tool_tokens_iter,
                    )
                    messages = iter_comp.messages
                    if mem_history is not None:
                        mem_history = [
                            m for m in messages if m["role"] != "system"
                        ]

                    # Persist compression to DB so the excluded messages
                    # are not reloaded on page refresh and the next
                    # pre-gen compression check sees up-to-date data.
                    _summary_msg_id: str | None = None
                    try:
                        from sqlmodel import select as _sel
                        _stmt = (
                            _sel(Message)
                            .where(Message.conversation_id == conv_id)
                            .where(
                                Message.context_excluded == False,  # noqa: E712
                            )
                            .order_by(Message.created_at, Message.id)
                        )
                        _res = await session.exec(_stmt)
                        _loop_msgs = _res.all()
                        # Archive the first split_index non-system messages.
                        _archived = 0
                        for _m in _loop_msgs:
                            if _archived >= iter_comp.split_index:
                                break
                            if _m.role == "system":
                                continue
                            if getattr(_m, "is_context_summary", False):
                                continue
                            _m.context_excluded = True
                            session.add(_m)
                            _archived += 1
                        # Persist the summary message.
                        _summary_content = (
                            f"[Context summary of "
                            f"{iter_comp.split_index} earlier "
                            f"messages]:\n{iter_comp.summary_text}"
                        )
                        _summary_msg = Message(
                            conversation_id=conv_id,
                            role="assistant",
                            content=_summary_content,
                            is_context_summary=True,
                        )
                        session.add(_summary_msg)
                        await session.flush()
                        _summary_msg_id = str(_summary_msg.id)
                    except Exception as _db_exc:
                        logger.warning(
                            "Tool loop: failed to persist compression to DB: {}",
                            _db_exc,
                        )

                    # Send updated context_info so the ContextBar reflects
                    # the post-compression state immediately.
                    await websocket.send_json({
                        "type": "context_info",
                        "used": iter_comp.usage.used_tokens,
                        "available": iter_comp.usage.available_tokens,
                        "context_window": context_window,
                        "percentage": iter_comp.usage.percentage,
                        "was_compressed": True,
                        "messages_summarized": (
                            iter_comp.usage.messages_summarized
                        ),
                        "is_estimated": iter_comp.usage.is_estimated,
                        "breakdown": None,
                    })
                    _comp_done_payload: dict[str, Any] = {
                        "type": "context_compression_done",
                        "messages_summarized": (
                            iter_comp.usage.messages_summarized
                        ),
                    }
                    if _summary_msg_id:
                        _comp_done_payload["summary_message_id"] = (
                            _summary_msg_id
                        )
                    await websocket.send_json(_comp_done_payload)
                except Exception as exc:
                    logger.warning(
                        "Tool loop context compression failed: {}", exc,
                    )
                    await websocket.send_json(
                        {"type": "context_compression_failed"},
                    )

        # 7. Re-stream LLM (with retry on empty responses).
        # Local LLMs sometimes return completely empty completions
        # after tool execution.  Retry up to _EMPTY_REQUERY_RETRIES
        # times before accepting an empty result as "final answer".
        # On retries we inject a continuation nudge so the model
        # understands it must produce a response.
        for requery_attempt in range(_EMPTY_REQUERY_RETRIES + 1):
            full_content = ""
            thinking_content = ""
            tool_calls_from_llm = []

            if requery_attempt == 0:
                query_messages = messages
                await websocket.send_json({
                    "type": "llm_requery",
                    "iteration": iteration + 1,
                })
            else:
                logger.info(
                    "Re-query retry {}/{} (iter {}) — LLM returned empty, "
                    "injecting continuation nudge",
                    requery_attempt, _EMPTY_REQUERY_RETRIES,
                    iteration + 1,
                )
                # Add a lightweight user nudge so the model knows it must
                # continue.  This is appended only for this attempt and is
                # never persisted to the DB.
                query_messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            "Please continue and provide your response "
                            "based on the tool results above."
                        ),
                    }
                ]
                await asyncio.sleep(0.3)

            # Spawn a reader task so cancel messages are detected
            # during streaming.
            reader_task = asyncio.create_task(
                _ws_cancel_reader(websocket, cancel_event),
            ) if cancel_event else None

            llm_error_in_requery = False

            try:
                async for event in llm.chat(
                    query_messages, tools=tools,
                    cancel_event=cancel_event,
                    system_prompt=system_prompt,
                ):
                    if event["type"] == "token":
                        full_content += event["content"]
                        await websocket.send_json(event)
                    elif event["type"] == "thinking":
                        thinking_content += event["content"]
                        await websocket.send_json(event)
                    elif event["type"] == "tool_call":
                        tool_calls_from_llm.append(event)
                        await websocket.send_json(event)
                    elif event["type"] == "error":
                        logger.error(
                            "LLM error during tool loop re-query "
                            "(iter {}): {}",
                            iteration + 1,
                            event.get("content", "unknown"),
                        )
                        llm_error_in_requery = True
                    elif event["type"] == "usage":
                        _loop_last_input_tokens = event.get(
                            "input_tokens", 0,
                        )
                        _loop_last_output_tokens = event.get(
                            "output_tokens", 0,
                        )
                    elif event["type"] == "done":
                        _loop_finish_reason = event.get(
                            "finish_reason", "stop",
                        )
            except Exception as exc:
                logger.error(
                    "LLM exception during tool loop re-query "
                    "(iter {}): {}",
                    iteration + 1, exc,
                )
                llm_error_in_requery = True
            finally:
                if reader_task and not reader_task.done():
                    reader_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await reader_task

            # Got content or tool calls or an error — accept the result.
            if (
                full_content.strip()
                or tool_calls_from_llm
                or llm_error_in_requery
            ):
                break

            # Empty response on last attempt — accept as-is.
            if requery_attempt == _EMPTY_REQUERY_RETRIES:
                logger.warning(
                    "LLM returned empty after {} retries (iter {}) "
                    "— accepting empty response",
                    _EMPTY_REQUERY_RETRIES, iteration + 1,
                )

        # If the LLM returned an error during the re-query, stop
        # the loop — do not attempt further tool calls.
        if llm_error_in_requery:
            logger.warning(
                "Aborting tool loop due to LLM error in re-query",
            )
            tool_calls_from_llm.clear()

        logger.info(
            "Tool loop iter {} re-query done: content_len={}, "
            "tool_calls={}, error={}, retries={}",
            iteration + 1,
            len(full_content),
            len(tool_calls_from_llm),
            llm_error_in_requery,
            requery_attempt,
        )

    # Log why the tool loop exited.
    if cancel_event and cancel_event.is_set():
        logger.info("Tool loop finished: cancelled")
    elif tool_calls_from_llm:
        logger.warning(
            "Tool loop hit max iterations ({}) — forcing final answer",
            max_iterations,
        )
        await websocket.send_json({
            "type": "warning",
            "content": f"Tool loop exceeded maximum iterations ({max_iterations}). Returning partial response.",
        })
    else:
        exit_reason = (
            "LLM error in re-query" if llm_error_in_requery
            else "LLM returned final answer (no more tool calls)"
        )
        logger.info("Tool loop finished: {}", exit_reason)

    return (
        full_content,
        thinking_content,
        _loop_last_input_tokens,
        _loop_last_output_tokens,
        _loop_finish_reason,
    )


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


async def _persist_tool_image(
    conv_id: uuid.UUID,
    exec_id: str,
    base64_data: str,
    content_type: str | None,
) -> str | None:
    """Save base64 image data to disk and return a relative reference path.

    The image is stored under ``data/uploads/{conv_id}/tool_images/``
    so chat history reconstruction can serve them via the existing
    ``/uploads/`` static route.

    Args:
        conv_id: Conversation UUID (used for directory partitioning).
        exec_id: Execution ID (used for a unique filename).
        base64_data: Raw base64-encoded image bytes.
        content_type: MIME type (e.g. ``image/png``).

    Returns:
        Relative path from the project root, or ``None`` on failure.
    """
    import base64
    from backend.core.config import PROJECT_ROOT

    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    ext = ext_map.get(content_type or "", ".png")
    rel_dir = f"data/uploads/{conv_id}/tool_images"
    abs_dir = PROJECT_ROOT / rel_dir
    filename = f"{exec_id}{ext}"
    abs_path = abs_dir / filename

    try:
        import asyncio as _aio
        await _aio.to_thread(abs_dir.mkdir, parents=True, exist_ok=True)
        raw = base64.b64decode(base64_data)
        await _aio.to_thread(abs_path.write_bytes, raw)
        logger.debug(
            "Persisted tool image: {} ({} bytes)", abs_path, len(raw),
        )
        return f"{rel_dir}/{filename}"
    except Exception as exc:
        logger.warning("Failed to persist tool image: {}", exc)
        return None


def _save_rejected_tool_msg(
    session: Any,
    conv_id: uuid.UUID,
    tool_call_id: str,
    version_group_id: uuid.UUID | None = None,
    version_index: int = 0,
) -> None:
    """Persist a tool message recording that execution was rejected."""
    msg = Message(
        conversation_id=conv_id,
        role="tool",
        content="Tool execution was rejected by user or timed out.",
        tool_call_id=tool_call_id,
        version_group_id=version_group_id,
        version_index=version_index,
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

    deadline = asyncio.get_running_loop().time() + timeout_s
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=remaining,
            )
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug(
                    "Ignoring non-JSON message during confirmation wait",
                )
                continue
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
    except Exception:
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
