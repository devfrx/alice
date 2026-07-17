"""AL\\CE — Post-turn conversation maintenance and ``done`` emission.

The final assistant message is persisted by the AgentEngine itself
(``engine._finish`` saving matrix via ``PersistencePort.save_final_message``,
carry #2/#3) — this module no longer creates it.  What it owns is the
post-turn pipeline around that fact: emitting the ``done`` event with the
engine-returned ``final_message_id``, refreshing conversation metadata
(``title``/``updated_at``/``context_snapshot``), emitting the real
``context_info`` frame, and running the post-stream context compression
pass.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

from loguru import logger
from sqlmodel import select

from backend.core.context import AppContext
from backend.db.models import Conversation, Message
from backend.services.agent.models import TurnOutcome
from backend.services.context_manager import CompressionResult
from backend.services.llm_service import LLMService

from ._helpers import (
    _archive_messages_in_db,
    _compute_context_breakdown,
    _filter_history_for_llm,
    _msg_to_raw_dict,
)
from ._shared import _utcnow
from ._sink import WSEventSink


def _build_done_event(
    *,
    conv_id: uuid.UUID,
    user_msg_id: uuid.UUID,
    version_group_id: uuid.UUID | None,
    version_index: int,
    asst_msg_id: str,
    finish_reason: str,
) -> dict[str, Any]:
    """Build the standard ``done`` WS event payload.

    Takes primitives instead of the ORM ``Message`` so callers can run
    it after a commit (which expires SQLAlchemy attributes and would
    otherwise trigger a sync lazy-load → ``MissingGreenlet``).
    """
    return {
        "type": "done",
        "conversation_id": str(conv_id),
        "message_id": asst_msg_id,
        "user_message_id": str(user_msg_id),
        "finish_reason": finish_reason,
        "version_group_id": (
            str(version_group_id) if version_group_id else None
        ),
        "version_index": version_index,
    }


async def _persist_final_turn(
    session: Any,
    conv: Conversation,
    conv_id: uuid.UUID,
    user_msg: Message,
    result: TurnOutcome,
    sink: WSEventSink,
    *,
    ctx: AppContext,
    llm: LLMService,
    user_content: str,
    was_compressed: bool,
    pre_comp: CompressionResult | None,
    context_window: int,
    tool_tokens: int,
    messages: list[dict[str, Any]],
    av_map: dict[str, int],
    cached_sys_prompt: str | None,
) -> None:
    """Run post-turn conversation maintenance and emit the ``done`` event.

    The final assistant message is already persisted (or deliberately
    skipped) by the AgentEngine — ``engine._finish`` saving matrix via
    ``PersistencePort.save_final_message`` (carry #2/#3) — so this
    pipeline never creates it; ``result.final_assistant_message_id``
    is relayed as the ``done`` frame's ``message_id``:

    * Fast path ``error``: defensive rollback + ``done`` error frame.
    * Fast path ``cancelled``: refresh ``Conversation.title``/
      ``updated_at`` when the turn produced anything, commit, ``done``.
    * Normal path: emit real ``context_info`` (v2-6), update
      ``Conversation.title``/``updated_at``/``context_snapshot`` (v2-5),
      commit, optionally trigger post-stream compression (v2-1), then
      emit the WS ``done`` event.

    Args:
        session: Active async DB session.
        conv: Conversation ORM instance.
        conv_id: Conversation UUID.
        user_msg: User ORM message that triggered the turn.
        result: Outcome produced by the AgentEngine.
        sink: WebSocket event sink.
        ctx: Application context.
        llm: Active LLM service.
        user_content: Raw user text (used for default title).
        was_compressed: Whether pre-generation compression ran.
        pre_comp: Result of pre-gen compression (``None`` if not run).
        context_window: Effective context window for the active model.
        tool_tokens: Token count of serialized tool definitions.
        messages: Fully-assembled prompt list (used for breakdown).
        av_map: Active version map for archival.
        cached_sys_prompt: Pre-built system prompt for re-compression.
    """
    finish_reason = result.finish_reason

    # Snapshot user_msg primitives ONCE up front.  After ``session.commit()``
    # SQLAlchemy expires loaded attributes; reading them later from this
    # async-session-bound ORM object would trigger a sync lazy-load and
    # raise ``MissingGreenlet``.  Capturing here is safe — these fields
    # are immutable for the lifetime of the turn.
    user_msg_id = user_msg.id
    user_msg_version_group_id = user_msg.version_group_id
    user_msg_version_index = user_msg.version_index

    # ------------------------------------------------------------------
    # Fast path: error.  The AgentEngine already checkpoints intermediate
    # rows as it goes (``PersistencePort.checkpoint()`` after every
    # ``save_assistant_step``/``save_tool_result``, see ``engine.py``) —
    # those are durable regardless of how the turn ends. This rollback
    # only discards whatever uncommitted work this final-persist call
    # itself had started on ``session`` before the error was observed
    # (e.g. a partially-built assistant message), keeping the DB
    # consistent without touching the already-committed checkpoints. The
    # AgentEngine sends ``cost=None`` on the error ``turn.finished``
    # frame, so the frontend live chip never sums a cost this rollback
    # won't back.
    # ------------------------------------------------------------------
    if finish_reason == "error":
        with contextlib.suppress(Exception):
            await session.rollback()
        await sink.send(_build_done_event(
            conv_id=conv_id,
            user_msg_id=user_msg_id,
            version_group_id=user_msg_version_group_id,
            version_index=user_msg_version_index,
            asst_msg_id="", finish_reason="error",
        ))
        return

    # ------------------------------------------------------------------
    # Fast path: cancelled (v3-4).  The AgentEngine already persisted the
    # partial assistant message (matrice ``_finish``: CANCELLED saves when
    # content or thinking is present, including usage) — the persist path
    # only refreshes the conversation metadata and emits ``done`` with the
    # engine-returned ``final_message_id``.
    # ------------------------------------------------------------------
    if finish_reason == "cancelled":
        asst_msg_id = result.final_assistant_message_id or ""
        if result.tool_calls > 0 or result.content or result.thinking:
            conv.updated_at = _utcnow()
            if conv.title is None and user_content:
                conv.title = user_content[:100]
            await session.commit()
        await sink.send(_build_done_event(
            conv_id=conv_id,
            user_msg_id=user_msg_id,
            version_group_id=user_msg_version_group_id,
            version_index=user_msg_version_index,
            asst_msg_id=asst_msg_id, finish_reason="cancelled",
        ))
        return

    # ------------------------------------------------------------------
    # Normal path: the AgentEngine already persisted the final assistant
    # message (matrice ``_finish``: content/token_count/usage all written
    # via ``PersistencePort.save_final_message``).  The persist path now
    # only emits ``context_info`` (v2-6), refreshes conversation metadata
    # (v2-5), commits and runs the post-stream compression.
    # ------------------------------------------------------------------
    asst_msg_id = result.final_assistant_message_id or ""

    try:
        # v2-6: emit context_info with REAL token counts when available.
        if (
            result.input_tokens > 0
            and ctx.context_manager
            and context_window > 0
        ):
            real_usage = ctx.context_manager.get_usage_real(
                result.input_tokens, context_window,
            )
            await sink.send({
                "type": "context_info",
                "used": real_usage.used_tokens,
                "available": real_usage.available_tokens,
                "context_window": context_window,
                "percentage": real_usage.percentage,
                "was_compressed": was_compressed,
                "messages_summarized": (
                    pre_comp.usage.messages_summarized if pre_comp else 0
                ),
                "is_estimated": False,
                "breakdown": _compute_context_breakdown(
                    messages, tool_tokens, ctx.context_manager,
                ),
            })

        conv.updated_at = _utcnow()
        if conv.title is None and user_content:
            conv.title = user_content[:100]

        # v2-5: persist anchor for next-turn token estimate.
        if result.input_tokens > 0 and context_window > 0:
            conv.context_snapshot = {
                "prompt_tokens": result.input_tokens,
                "completion_tokens": result.output_tokens,
                "context_window": context_window,
            }

        await session.commit()

        # v2-1: post-stream compression (truncated output OR token usage
        # over threshold).  Triggers a fresh compression pass so the
        # NEXT turn has room to breathe.
        post_compress = finish_reason == "length"
        if (
            not post_compress
            and result.input_tokens > 0
            and result.output_tokens > 0
            and context_window > 0
        ):
            real_pct = (
                (result.input_tokens + result.output_tokens) / context_window
            )
            if real_pct >= ctx.config.llm.context_compression_threshold:
                post_compress = True
                logger.info(
                    "Token usage {:.1f}% >= threshold {}%, triggering "
                    "post-stream compression",
                    real_pct * 100,
                    ctx.config.llm.context_compression_threshold * 100,
                )

        if (
            post_compress
            and ctx.config.llm.context_compression_enabled
            and ctx.context_manager is not None
            and context_window > 0
        ):
            await _run_post_stream_compression(
                session=session,
                conv=conv,
                conv_id=conv_id,
                ctx=ctx,
                llm=llm,
                sink=sink,
                cached_sys_prompt=cached_sys_prompt,
                tool_tokens=tool_tokens,
                context_window=context_window,
                av_map=av_map,
                finish_reason=finish_reason,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
    except Exception:
        logger.exception("DB commit error after streaming")
        with contextlib.suppress(Exception):
            await session.rollback()
        await sink.send({
            "type": "error", "content": "Failed to save response",
        })
        await sink.send(_build_done_event(
            conv_id=conv_id,
            user_msg_id=user_msg_id,
            version_group_id=user_msg_version_group_id,
            version_index=user_msg_version_index,
            asst_msg_id="", finish_reason="error",
        ))
        return

    await sink.send(_build_done_event(
        conv_id=conv_id,
        user_msg_id=user_msg_id,
        version_group_id=user_msg_version_group_id,
        version_index=user_msg_version_index,
        asst_msg_id=asst_msg_id, finish_reason=finish_reason,
    ))


async def _run_post_stream_compression(
    *,
    session: Any,
    conv: Conversation,
    conv_id: uuid.UUID,
    ctx: AppContext,
    llm: LLMService,
    sink: WSEventSink,
    cached_sys_prompt: str | None,
    tool_tokens: int,
    context_window: int,
    av_map: dict[str, int],
    finish_reason: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Run a compression pass after the final assistant message is saved.

    Mirrors the legacy "post-stream compression" block from ``ws_chat``
    1:1.  Failures are caught and surfaced as a
    ``context_compression_failed`` WS event so the turn still completes.
    """
    try:
        logger.info(
            "Triggering post-stream compression (finish_reason={}, "
            "tokens={}/{})",
            finish_reason,
            input_tokens + output_tokens,
            context_window,
        )
        await sink.send({"type": "context_compression_start"})
        post_stmt = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at, Message.id)
        )
        post_results = await session.exec(post_stmt)
        post_all_msgs = post_results.all()
        post_raw = [
            _msg_to_raw_dict(m, i) for i, m in enumerate(post_all_msgs)
        ]
        post_hist = _filter_history_for_llm(post_raw, av_map)
        post_msgs = llm.build_continuation_messages(
            post_hist, system_prompt=cached_sys_prompt,
        )
        post_comp = await ctx.context_manager.compress(
            post_msgs,
            llm,
            context_window,
            ctx.config.llm.context_compression_reserve,
            tool_tokens=tool_tokens,
        )
        await _archive_messages_in_db(
            session, post_all_msgs, post_raw,
            post_comp.split_index,
            active_versions=av_map,
        )
        post_summary = (
            f"[Context summary of {post_comp.split_index} earlier "
            f"messages]:\n{post_comp.summary_text}"
        )
        post_sum_msg = Message(
            conversation_id=conv_id,
            role="assistant",
            content=post_summary,
            is_context_summary=True,
        )
        session.add(post_sum_msg)
        await session.commit()

        await sink.send({
            "type": "context_compression_done",
            "messages_summarized": post_comp.usage.messages_summarized,
            "summary_message_id": str(post_sum_msg.id),
        })
        await sink.send({
            "type": "context_info",
            "used": post_comp.usage.used_tokens,
            "available": post_comp.usage.available_tokens,
            "context_window": context_window,
            "percentage": post_comp.usage.percentage,
            "was_compressed": True,
            "messages_summarized": post_comp.usage.messages_summarized,
            "is_estimated": True,
            "breakdown": _compute_context_breakdown(
                post_comp.messages, tool_tokens, ctx.context_manager,
            ),
        })
        logger.info(
            "Post-stream compression done: {} messages archived",
            post_comp.split_index,
        )
        conv.context_snapshot = {
            "prompt_tokens": post_comp.usage.used_tokens,
            "completion_tokens": 0,
            "context_window": context_window,
        }
        await session.commit()
    except Exception as exc:
        logger.warning("Post-stream compression failed: {}", exc)
        with contextlib.suppress(Exception):
            await sink.send({"type": "context_compression_failed"})
