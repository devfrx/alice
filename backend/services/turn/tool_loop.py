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

from fastapi import WebSocketDisconnect
from loguru import logger

from backend.core.context import AppContext
from backend.core.plugin_models import ExecutionContext, ToolResult
from backend.db.models import Message, ToolConfirmationAudit
from backend.services.llm_service import LLMService
from backend.services.permission_service import PermissionService
from backend.services.turn import events
from backend.services.turn.channel import InteractionChannel
from backend.services.turn.models import TurnProgress
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
from backend.services.turn.sink import WSEventSink

# Type alias for the sync callback.
SyncFn = Callable[..., Coroutine[Any, Any, None]]

# Max retries when the LLM returns an empty response during re-query.
# Local models occasionally produce empty completions after tool results;
# retrying typically succeeds on the next attempt.
_EMPTY_REQUERY_RETRIES = 2


def _dedup_hash(tool_name: str, args: dict[str, Any]) -> str:
    """Return a compact hash for deduplication of identical tool calls.

    Normalises Windows-style paths to forward slashes so the same call
    with ``C:\\Users\\x`` and ``C:/Users/x`` is treated as a duplicate,
    and produces a SHA-256 digest instead of holding full JSON strings
    in memory.
    """
    canonical = json.dumps(args, sort_keys=True, default=str)
    # JSON encoding of a single backslash produces ``\\`` in the output
    # string — replace those with ``/`` so cross-platform paths collapse
    # to a single canonical form.
    canonical = canonical.replace("\\\\", "/").replace("\\", "/")
    raw = f"{tool_name}:{canonical}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def run_tool_loop(
    *,
    channel: InteractionChannel,
    sink: WSEventSink,
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
    turn_progress: TurnProgress | None = None,
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
        channel: Inbound interaction channel (confirmation / client-tool
            round-trips, cancel signalling) — the single WS reader.
        sink: Outbound event sink for streamed frames.
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
        turn_progress: Optional mutable per-turn counters shared with the
            executor. When provided, the per-iteration ``turn.llm_step`` /
            ``turn.usage`` frames reuse its ``turn_id`` and advance its
            ``steps`` / ``tool_calls``. When ``None`` (direct callers and
            unit tests), a private :class:`TurnProgress` is minted locally
            so the loop's emissions still carry a stable ``turn_id``.
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

    # Resolve a per-turn progress object so the per-iteration lifecycle
    # frames carry a stable turn_id and accurate counters even when the
    # loop is invoked directly (no executor, e.g. unit tests).
    progress = (
        turn_progress
        if turn_progress is not None
        else TurnProgress(turn_id=uuid.uuid4().hex)
    )
    max_steps = max_iterations + 1

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

    # Central permission authority (forbidden risk + by-construction scope
    # confinement). Fall back to a default instance for lightweight test
    # contexts that don't wire one onto the AppContext.
    _ps = getattr(ctx, "permission_service", None)
    permission_service = (
        _ps if isinstance(_ps, PermissionService) else PermissionService()
    )
    # Runtime confirmation toggle (constant for the turn).
    confirmations_on = ctx.config.permissions.confirmations_enabled

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

        # 2. Gate every tool-call through the composable middleware pipeline.
        #    ``seen`` / ``permission_service`` / ``channel`` / ``sink`` are
        #    stable across iterations; the confirmation reasoning is this
        #    iteration's thinking content.
        gate_pipeline = ToolPipeline(
            [
                DedupMiddleware(seen),
                PermissionMiddleware(permission_service),
                ConfirmationMiddleware(
                    sink=sink,
                    channel=channel,
                    permission_service=permission_service,
                    confirmations_enabled=confirmations_on,
                    confirmation_timeout_s=confirmation_timeout_s,
                    reasoning=thinking_content,
                    cancel_event=cancel_event,
                ),
                InteractionMiddleware(
                    sink=sink,
                    channel=channel,
                    seen=seen,
                    tool_exec_timeout=tool_exec_timeout,
                    cancel_event=cancel_event,
                ),
            ],
            ExecuteMiddleware(tool_registry=ctx.tool_registry, sink=sink),
        )
        # Server tools that clear the gate are collected for parallel execution.
        deferred: list[ToolCall] = []

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

            # Count every named tool call dispatched this turn (cumulative
            # across iterations, regardless of the gate disposition).
            progress.tool_calls += 1

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
                await sink.send({
                    "type": "tool_execution_done",
                    "tool_name": tool_name,
                    "result": _parse_err,
                    "execution_id": str(uuid.uuid4()),
                    "success": False,
                })
                continue

            tool_def = (
                ctx.tool_registry.get_tool_definition(tool_name)
                if ctx.tool_registry
                else None
            )
            exec_id = str(uuid.uuid4())
            call = ToolCall(
                tc_id=tc_id,
                tool_name=tool_name,
                args=args,
                tool_def=tool_def,
                exec_id=exec_id,
                conversation_id=str(conv_id),
                context=ExecutionContext(
                    session_id=client_ip,
                    conversation_id=str(conv_id),
                    execution_id=exec_id,
                ),
                dedup_key=_dedup_hash(tool_name, args),
                is_client=bool(tool_def and tool_def.client_execution),
                turn_id=progress.turn_id,
            )

            # Additive canonical frame: announce every well-formed (named +
            # JSON-parsed) tool call exactly once, before the gate decides.
            with contextlib.suppress(Exception):
                await sink.send(events.tool_call(
                    turn_id=progress.turn_id,
                    execution_id=call.exec_id,
                    tool_name=tool_name,
                    args=args,
                ))

            # Decision lives in the pipeline; persistence/audit stays here.
            outcome = await gate_pipeline.gate(call)

            # An audit row is written for any call the pipeline classified:
            # the forbidden block, or a confirmation-requiring tool (whether
            # approved or rejected). Safe tools set no decision, so no audit.
            if call.audit_decision is not None:
                session.add(ToolConfirmationAudit(
                    conversation_id=conv_id,
                    execution_id=exec_id,
                    tool_name=tool_name,
                    args_json=json.dumps(args, default=str),
                    risk_level=call.audit_decision.risk_level,
                    user_approved=call.audit_decision.approved,
                    rejection_reason=call.audit_decision.reason,
                    thinking_content=thinking_content or None,
                ))
                await session.flush()

            if outcome.disposition is Disposition.EXECUTE:
                # Cleared every gate: defer to the parallel execution batch.
                deferred.append(call)
            else:
                await _persist_gate_outcome(
                    outcome,
                    sink=sink,
                    session=session,
                    conv_id=conv_id,
                    mem_history=mem_history,
                    ver=_ver,
                    sync_fn=sync_fn,
                    ctx=ctx,
                    turn_id=progress.turn_id,
                )

        # Release the SQLite write lock held by pending flush()es so that
        # plugin tools can write to the DB on their own connections.
        await session.commit()
        if ctx.conversation_file_manager and sync_fn:
            await sync_fn(session, conv_id, ctx.conversation_file_manager)

        # 3. Execute all tools in parallel (with timeout).
        coros = [
            asyncio.ensure_future(gate_pipeline.execute(call))
            for call in deferred
        ]
        if coros:
            done, pending = await asyncio.wait(
                coros, timeout=tool_exec_timeout,
            )
        else:
            done, pending = set(), set()

        # Build a lookup from future to task metadata — used for
        # both pending (timeout) and done (exception) handling.
        future_to_call = dict(zip(coros, deferred))

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
                call = future_to_call[fut]
                tc_id = call.tc_id
                tool_name = call.tool_name
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
                await sink.send({
                    "type": "tool_execution_done",
                    "tool_name": tool_name,
                    "result": _timeout_content,
                    "execution_id": call.exec_id,
                    "success": False,
                })
                await _emit_tool_result(
                    sink,
                    turn_id=progress.turn_id,
                    execution_id=call.exec_id,
                    tool_name=tool_name,
                    success=False,
                    result=_timeout_content,
                )
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
                call = future_to_call[fut]
                failed_tc_id = call.tc_id
                failed_tool_name = call.tool_name
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
                await sink.send({
                    "type": "tool_execution_done",
                    "tool_name": failed_tool_name,
                    "result": f"Tool '{failed_tool_name}' execution failed.",
                    "execution_id": call.exec_id,
                    "success": False,
                })
                await _emit_tool_result(
                    sink,
                    turn_id=progress.turn_id,
                    execution_id=call.exec_id,
                    tool_name=failed_tool_name,
                    success=False,
                    result=_fail_content,
                )
                continue

            outcome = fut.result()
            call = outcome.call
            assert outcome.result is not None
            tc_id = call.tc_id
            tool_name = call.tool_name
            tool_result = outcome.result
            exec_id = call.exec_id

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
            await session.flush()  # need tool_msg.id for artifact FK
            # Commit immediately to release the SQLite write lock held
            # by the pending transaction.  The artifact registry opens
            # its own connection to insert into ``artifacts`` and would
            # otherwise hit ``database is locked`` (busy_timeout
            # cannot wait for a transaction held by the same process).
            tool_msg_id = tool_msg.id
            await session.commit()

            # Append to in-memory history so DB re-fetch is avoided.
            if mem_history is not None:
                mem_history.append({
                    "role": "tool",
                    "content": db_content,
                    "tool_call_id": tc_id,
                })

            # Optional: register an artifact when the tool produced a
            # binary file (3D model, image, audio, …).  Failures here
            # must never break the tool loop.  We prefer ``raw_content``
            # (pre-sanitisation snapshot) so on-disk paths stay intact
            # even when the tool registry redacts them for the LLM.
            artifact_id: str | None = None
            artifact_payload = (
                tool_result.raw_content
                if isinstance(tool_result.raw_content, dict)
                else tool_result.content
            )
            if (
                tool_result.success
                and isinstance(artifact_payload, dict)
                and getattr(ctx, "artifact_registry", None) is not None
            ):
                # Parsers are keyed by the bare tool name (e.g.
                # ``cad_generate_from_image``) but ``tool_name`` here is
                # the namespaced form exposed to the LLM
                # (``cad_generator_cad_generate_from_image``).  Resolve
                # back to the bare name via the tool registry so the
                # parser lookup succeeds.
                bare_tool_name = tool_name
                if ctx.tool_registry is not None:
                    tool_def = ctx.tool_registry.get_tool_definition(tool_name)
                    if tool_def is not None:
                        bare_tool_name = tool_def.name
                try:
                    artifact = await ctx.artifact_registry.register_from_tool_result(
                        conversation_id=conv_id,
                        message_id=tool_msg_id,
                        tool_call_id=tc_id,
                        tool_name=bare_tool_name,
                        payload=artifact_payload,
                        content_type=tool_result.content_type,
                    )
                    if artifact is not None:
                        artifact_id = str(artifact.id)
                except Exception as exc:
                    logger.warning(
                        "Artifact registration failed for tool '{}': {}",
                        tool_name, exc,
                    )

            ws_payload: dict[str, Any] = {
                "type": "tool_execution_done",
                "tool_name": tool_name,
                "result": content,
                "execution_id": exec_id,
                "success": tool_result.success,
            }
            if tool_result.content_type:
                ws_payload["content_type"] = tool_result.content_type
            if artifact_id:
                ws_payload["artifact_id"] = artifact_id

            try:
                await sink.send(ws_payload)
            except WebSocketDisconnect:
                if ctx.conversation_file_manager and sync_fn:
                    await sync_fn(session, conv_id, ctx.conversation_file_manager)
                raise

            # Additive canonical frame mirrors the legacy done frame above
            # (same content / success / content_type / artifact_id).
            await _emit_tool_result(
                sink,
                turn_id=progress.turn_id,
                execution_id=exec_id,
                tool_name=tool_name,
                success=tool_result.success,
                result=content,
                content_type=tool_result.content_type or None,
                artifact_id=artifact_id,
            )

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
                await sink.send(
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
                    await sink.send({
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
                    await sink.send(_comp_done_payload)
                except Exception as exc:
                    logger.warning(
                        "Tool loop context compression failed: {}", exc,
                    )
                    await sink.send(
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
                await sink.send({
                    "type": "llm_requery",
                    "iteration": iteration + 1,
                })
                # Additive: mark a new LLM step for this iteration.
                progress.steps += 1
                with contextlib.suppress(Exception):
                    await sink.send(events.turn_llm_step(
                        turn_id=progress.turn_id, step=progress.steps,
                    ))
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

            # Cancel during streaming is observed by the channel's single
            # read-pump (it sets ``cancel_event``), which ``llm.chat`` honours
            # per chunk — no dedicated reader here (avoids a second WS reader).
            llm_error_in_requery = False

            try:
                async for event in llm.chat(
                    query_messages, tools=tools,
                    cancel_event=cancel_event,
                    system_prompt=system_prompt,
                ):
                    if event["type"] == "token":
                        full_content += event["content"]
                        await sink.send(event)
                    elif event["type"] == "thinking":
                        thinking_content += event["content"]
                        await sink.send(event)
                    elif event["type"] == "tool_call":
                        tool_calls_from_llm.append(event)
                        await sink.send(event)
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

        # Additive: per-step usage snapshot for this iteration (uses the
        # real token counts captured from the re-query ``usage`` event).
        with contextlib.suppress(Exception):
            await sink.send(events.turn_usage(
                turn_id=progress.turn_id,
                step=progress.steps,
                input_tokens=_loop_last_input_tokens,
                output_tokens=_loop_last_output_tokens,
                tool_calls=progress.tool_calls,
                max_steps=max_steps,
            ))

    # Log why the tool loop exited.
    if cancel_event and cancel_event.is_set():
        logger.info("Tool loop finished: cancelled")
    elif tool_calls_from_llm:
        logger.warning(
            "Tool loop hit max iterations ({}) — forcing final answer",
            max_iterations,
        )
        await sink.send({
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


async def _emit_tool_result(
    sink: WSEventSink,
    *,
    turn_id: str,
    execution_id: str,
    tool_name: str,
    success: bool,
    result: str,
    content_type: str | None = None,
    artifact_id: str | None = None,
) -> None:
    """Best-effort emit of the additive canonical ``tool.result`` frame.

    Wrapped in :func:`contextlib.suppress` so a sink failure never alters the
    surrounding control flow (the legacy ``tool_execution_done`` frame is
    emitted separately and unchanged).
    """
    with contextlib.suppress(Exception):
        await sink.send(events.tool_result(
            turn_id=turn_id,
            execution_id=execution_id,
            tool_name=tool_name,
            success=success,
            result=result,
            content_type=content_type,
            artifact_id=artifact_id,
        ))


async def _persist_gate_outcome(
    outcome: ToolOutcome,
    *,
    sink: WSEventSink,
    session: Any,
    conv_id: uuid.UUID,
    mem_history: list[dict[str, Any]] | None,
    ver: dict[str, Any],
    sync_fn: SyncFn | None,
    ctx: AppContext,
    turn_id: str,
) -> None:
    """Persist a terminal (non-executed) gate outcome.

    Routes a pipeline :class:`ToolOutcome` that did not reach server
    execution to the same DB message / sink frame the legacy inline ladder
    produced: deduped, forbidden, confirmation-rejected, scope-denied, or a
    client-executed result. Audit rows are written by the caller from
    ``call.audit_decision``; this handles only messages and frames.

    ``turn_id`` correlates the additive canonical ``tool.result`` frame this
    emits (alongside each legacy frame) so the timeline entry is closed.
    """
    call = outcome.call

    if outcome.disposition is Disposition.CLIENT_EXECUTED:
        assert outcome.result is not None
        await _persist_client_tool_result(
            sink=sink,
            session=session,
            conv_id=conv_id,
            tc_id=call.tc_id,
            tool_name=call.tool_name,
            exec_id=call.exec_id,
            result=outcome.result,
            mem_history=mem_history,
            ver=ver,
            sync_fn=sync_fn,
            ctx=ctx,
            turn_id=turn_id,
        )
        return

    if outcome.disposition is Disposition.DEDUPED:
        # OpenAI API requires a tool response for EVERY tool_call_id.
        dedup_content = "Duplicate call — see prior result."
        session.add(Message(
            conversation_id=conv_id,
            role="tool",
            content=dedup_content,
            tool_call_id=call.tc_id,
            **ver,
        ))
        await session.flush()
        if mem_history is not None:
            mem_history.append({
                "role": "tool",
                "content": dedup_content,
                "tool_call_id": call.tc_id,
            })
        # Canonical-only: a deduped call has no legacy done frame, but the
        # timeline still needs its entry closed.
        await _emit_tool_result(
            sink,
            turn_id=turn_id,
            execution_id=call.exec_id,
            tool_name=call.tool_name,
            success=True,
            result=dedup_content,
        )
        return

    # FORBIDDEN / REJECTED / SCOPE_DENIED: a rejected tool message plus a
    # failed tool_execution_done frame.
    _save_rejected_tool_msg(session, conv_id, call.tc_id, **ver)
    await session.flush()
    if mem_history is not None:
        mem_history.append({
            "role": "tool",
            "content": "Tool execution was rejected by user or timed out.",
            "tool_call_id": call.tc_id,
        })
    if outcome.disposition is Disposition.FORBIDDEN:
        result_text = "Tool is forbidden and cannot be executed."
    elif outcome.disposition is Disposition.SCOPE_DENIED:
        result_text = "Tool execution denied: path outside the workspace scope."
    else:
        result_text = "Tool execution rejected or timed out."
    await sink.send({
        "type": "tool_execution_done",
        "tool_name": call.tool_name,
        "result": result_text,
        "execution_id": call.exec_id,
        "success": False,
    })
    await _emit_tool_result(
        sink,
        turn_id=turn_id,
        execution_id=call.exec_id,
        tool_name=call.tool_name,
        success=False,
        result=result_text,
    )


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


async def _persist_client_tool_result(
    *,
    sink: WSEventSink,
    session: Any,
    conv_id: uuid.UUID,
    tc_id: str,
    tool_name: str,
    exec_id: str,
    result: ToolResult,
    mem_history: list[dict[str, Any]] | None,
    ver: dict[str, Any],
    sync_fn: SyncFn | None,
    ctx: AppContext,
    turn_id: str,
) -> None:
    """Persist a client-executed tool result and notify the client.

    Mirrors the persistence performed for server-side tool results in the
    main loop (DB ``role="tool"`` message + in-memory history append +
    ``tool_execution_done`` frame), minus the image/artifact handling that
    only applies to server-produced binary payloads.

    ``turn_id`` correlates the additive canonical ``tool.result`` frame
    emitted alongside the legacy ``tool_execution_done`` frame.
    """
    content = _result_to_str(result)
    tool_msg = Message(
        conversation_id=conv_id,
        role="tool",
        content=content,
        tool_call_id=tc_id,
        **ver,
    )
    session.add(tool_msg)
    await session.flush()
    await session.commit()

    if mem_history is not None:
        mem_history.append({
            "role": "tool",
            "content": content,
            "tool_call_id": tc_id,
        })

    if ctx.conversation_file_manager and sync_fn:
        await sync_fn(session, conv_id, ctx.conversation_file_manager)

    await sink.send({
        "type": "tool_execution_done",
        "tool_name": tool_name,
        "result": content,
        "execution_id": exec_id,
        "success": result.success,
    })
    await _emit_tool_result(
        sink,
        turn_id=turn_id,
        execution_id=exec_id,
        tool_name=tool_name,
        success=result.success,
        result=content,
    )
