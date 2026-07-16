"""AL\\CE — Chat REST endpoints (conversation history & lifecycle).

CRUD and lifecycle operations for conversations: list, get (with
context-usage estimation), delete (one / all), title update, version
switching, branching, and idempotent creation.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlmodel import select

from backend.core.config import PROJECT_ROOT
from backend.db.models import Attachment, Conversation, Message
from backend.services.conversation_export import attachment_url

from ._helpers import (
    _build_mcp_context,
    _build_whiteboard_context,
    _filter_history_for_llm,
    _filter_messages_by_active_versions,
)
from ._shared import _ctx, _utcnow, router

# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class BranchConversationRequest(BaseModel):
    """Request body for branching a conversation.

    Args:
        from_message_id: UUID of the message to branch from (inclusive).
            All messages up through this one are copied to the new conversation.
        title: Optional title override for the new conversation.
            Defaults to "{original_title} (diramazione)".
    """

    from_message_id: str
    title: str | None = Field(None, max_length=500)


class ConversationSummaryResponse(BaseModel):
    """Summary of a conversation (list items, create/import/branch responses)."""

    id: str
    title: str | None
    created_at: str
    updated_at: str
    message_count: int


class ConversationListResponse(BaseModel):
    """List-endpoint envelope (convention: ``{items, total}``, spec §6)."""

    items: list[ConversationSummaryResponse]
    total: int


class TitleUpdateResponse(BaseModel):
    """Response of the title-update endpoint."""

    id: str
    title: str
    updated_at: str


class SwitchVersionResponse(BaseModel):
    """Response of the switch-version endpoint."""

    id: str
    active_versions: dict[str, int]
    updated_at: str


class DeleteConversationResponse(BaseModel):
    """Response of the single-conversation delete endpoint."""

    status: str


class DeleteAllConversationsResponse(BaseModel):
    """Response of the delete-all endpoint."""

    status: str


def _sum_usage_cost(messages: Sequence[Any]) -> float:
    """Sum provider-credit costs from the usage payloads persisted on messages."""
    total = 0.0
    for m in messages:
        usage = getattr(m, "usage", None)
        if not isinstance(usage, dict):
            continue
        try:
            total += float(usage.get("cost") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


# ---------------------------------------------------------------------------
# REST — conversation history
# ---------------------------------------------------------------------------


@router.get("/chat/conversations", response_model=ConversationListResponse)
async def list_conversations(request: Request) -> dict[str, Any]:
    """List all conversations ordered by most recently updated."""
    ctx = _ctx(request)
    async with ctx.db() as session:
        # Single query: conversation data + message count via LEFT JOIN.
        stmt = (
            select(
                Conversation,
                sa_func.count(Message.id).label("msg_count"),
            )
            .outerjoin(
                Message,
                Message.conversation_id == Conversation.id,
            )
            .group_by(Conversation.id)
            .order_by(Conversation.updated_at.desc())  # type: ignore[union-attr]
        )
        results = await session.exec(stmt)
        rows = results.all()

        items = [
            {
                "id": str(conv.id),
                "title": conv.title,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "message_count": msg_count,
            }
            for conv, msg_count in rows
        ]
        return {"items": items, "total": len(items)}


@router.get("/chat/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, request: Request
) -> dict[str, Any]:
    """Get a single conversation with all its messages."""
    ctx = _ctx(request)
    async with ctx.db() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        msg_stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
        results = await session.exec(msg_stmt)
        messages = results.all()

        # Pre-fetch attachments for all messages in one query.
        msg_ids = [m.id for m in messages]
        att_map: dict[uuid.UUID, list[dict[str, str]]] = {}
        if msg_ids:
            att_stmt = select(Attachment).where(
                Attachment.message_id.in_(msg_ids)  # type: ignore[union-attr]
            )
            att_results = await session.exec(att_stmt)
            for att in att_results.all():
                att_map.setdefault(att.message_id, []).append(
                    {
                        "file_id": str(att.id),
                        "url": attachment_url(att.file_path),
                        "filename": att.filename,
                        "content_type": att.content_type,
                    }
                )

        # Compute context usage for the ContextBar.
        # Prefer persisted real token data (from last stream) over
        # pure char/4 estimation.
        context_info: dict[str, Any] | None = None
        av_map: dict[str, int] = dict(conv.active_versions or {})
        if ctx.context_manager is not None and messages:
            # --- current context window ---
            cw = 0
            if ctx.llm_service and ctx.lmstudio_manager:
                with contextlib.suppress(Exception):
                    cw = ctx.llm_service.get_cached_context_window(
                        ctx.lmstudio_manager,
                    )
            if cw <= 0:
                cw = 32768

            has_summaries = any(
                getattr(m, "is_context_summary", False)
                for m in messages
            )

            snap = getattr(conv, "context_snapshot", None)
            if snap and isinstance(snap, dict) and snap.get("prompt_tokens"):
                # Use persisted real token counts as anchor.
                # prompt_tokens already includes system prompt + tools
                # + all messages that were in context during streaming.
                used = (
                    snap["prompt_tokens"]
                    + snap.get("completion_tokens", 0)
                )
                # Recalculate percentage against *current* context
                # window (may have changed if user swapped models).
                available = max(0, cw - used)
                pct = round(used / cw, 4) if cw > 0 else 0.0
                context_info = {
                    "used": used,
                    "available": available,
                    "context_window": cw,
                    "percentage": pct,
                    "was_compressed": has_summaries,
                    "messages_summarized": 0,
                    "is_estimated": False,
                }
            else:
                # Fallback: pure estimation (first message in new conv
                # or conversations created before snapshot feature).
                raw_hist = [
                    {
                        "role": m.role,
                        "content": m.content,
                        "tool_calls": m.tool_calls,
                        "tool_call_id": m.tool_call_id,
                        "version_group_id": (
                            str(m.version_group_id)
                            if m.version_group_id else None
                        ),
                        "version_index": m.version_index,
                        "context_excluded": getattr(
                            m, "context_excluded", False,
                        ),
                        "is_context_summary": getattr(
                            m, "is_context_summary", False,
                        ),
                    }
                    for m in messages
                ]
                filtered = _filter_history_for_llm(raw_hist, av_map)
                sys_prompt_tokens = 0
                if ctx.llm_service is not None:
                    try:
                        aux_ctx: str | None = None
                        mcp_ctx = _build_mcp_context(ctx)
                        wb_ctx = await _build_whiteboard_context(
                            ctx, str(conv.id),
                        )
                        for blk in (mcp_ctx, wb_ctx):
                            if blk:
                                aux_ctx = (
                                    f"{aux_ctx}\n\n{blk}"
                                    if aux_ctx else blk
                                )
                        sp = ctx.llm_service.get_system_prompt(
                            memory_context=aux_ctx,
                        )
                        if sp:
                            sys_prompt_tokens = (
                                ctx.context_manager.estimate_tokens(sp)
                            )
                    except Exception:
                        pass
                usage = ctx.context_manager.get_usage_estimated(
                    filtered, cw,
                )
                tool_tokens = 0
                if ctx.tool_registry and ctx.config.llm.tools_enabled:
                    try:
                        if (
                            ctx.config.llm.tool_rag_enabled
                            and ctx.qdrant_service is not None
                        ):
                            # For context estimation use top_k tools
                            # as a representative sample.
                            avail_tools = (
                                await ctx.tool_registry
                                .get_relevant_tools(
                                    "",
                                    ctx.config.llm.tool_rag_top_k,
                                )
                            )
                        else:
                            avail_tools = (
                                await ctx.tool_registry
                                .get_available_tools()
                            )
                            if avail_tools and ctx.config.llm.disabled_tools:
                                avail_tools = (
                                    ctx.tool_registry.exclude_disabled(
                                        avail_tools,
                                        set(ctx.config.llm.disabled_tools),
                                    )
                                )
                            if avail_tools and ctx.config.llm.max_tools > 0:
                                avail_tools = (
                                    ctx.tool_registry.limit_tools(
                                        avail_tools,
                                        max_tools=(
                                            ctx.config.llm.max_tools
                                        ),
                                        priority_plugins=(
                                            ctx.config.llm
                                            .priority_plugins
                                        ),
                                    )
                                )
                        # Estimate tool-definition tokens for BOTH the
                        # tool-RAG and the full-toolset paths.  Keeping this
                        # outside the if/else ensures the RAG branch does not
                        # silently undercount context usage (the sample of
                        # ``tool_rag_top_k`` tools still costs tokens).
                        if avail_tools:
                            tool_tokens = (
                                ctx.context_manager.estimate_tokens(
                                    json.dumps(
                                        avail_tools,
                                        ensure_ascii=False,
                                    )
                                )
                            )
                    except Exception:
                        pass
                extra_tokens = sys_prompt_tokens + tool_tokens
                if extra_tokens > 0:
                    usage.used_tokens += extra_tokens
                    usage.available_tokens = max(
                        0, cw - usage.used_tokens,
                    )
                    usage.percentage = round(
                        usage.used_tokens / cw, 4,
                    ) if cw > 0 else 0.0

                # Per-category breakdown for ContextBar tooltip.
                _rest_bd: dict[str, int] = {
                    "system": sys_prompt_tokens,
                    "tools": tool_tokens,
                    "messages": 0,
                    "files": 0,
                    "tool_results": 0,
                    "other": 0,
                }
                for _msg in filtered:
                    _role = _msg.get("role", "")
                    _content = _msg.get("content") or ""
                    _tok = 4  # role/metadata overhead
                    if isinstance(_content, str):
                        _tok += ctx.context_manager.estimate_tokens(_content)
                    _tc = _msg.get("tool_calls")
                    if _tc:
                        try:
                            _tc_s = (
                                json.dumps(_tc)
                                if not isinstance(_tc, str)
                                else _tc
                            )
                            _tok += ctx.context_manager.estimate_tokens(_tc_s)
                        except (TypeError, ValueError):
                            pass
                    if _role == "tool":
                        _rest_bd["tool_results"] += _tok
                    elif _role in ("user", "assistant"):
                        _rest_bd["messages"] += _tok
                    else:
                        _rest_bd["other"] += _tok

                context_info = {
                    "used": usage.used_tokens,
                    "available": usage.available_tokens,
                    "context_window": usage.context_window,
                    "percentage": usage.percentage,
                    "was_compressed": has_summaries,
                    "messages_summarized": 0,
                    "is_estimated": True,
                    "breakdown": _rest_bd,
                }

        total_cost = _sum_usage_cost(messages)

        return {
            "id": str(conv.id),
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "active_versions": conv.active_versions or {},
            "context_info": context_info,
            "total_cost": round(total_cost, 6) if total_cost > 0 else None,
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "thinking_content": m.thinking_content,
                    "tool_calls": m.tool_calls,
                    "tool_call_id": m.tool_call_id,
                    "usage": m.usage,
                    "created_at": m.created_at.isoformat(),
                    "attachments": att_map.get(m.id, []) or None,
                    "version_group_id": str(m.version_group_id)
                    if m.version_group_id
                    else None,
                    "version_index": m.version_index,
                    "is_context_summary": getattr(
                        m, "is_context_summary", False,
                    ),
                    "context_excluded": getattr(
                        m, "context_excluded", False,
                    ),
                }
                for m in messages
            ],
        }


@router.delete("/chat/conversations", response_model=DeleteAllConversationsResponse)
async def delete_all_conversations(request: Request) -> dict[str, Any]:
    """Delete ALL conversations, messages, attachments, and associated files."""
    ctx = _ctx(request)

    # Artifacts first: rows + on-disk blobs die in one place (the
    # unified registry — fase 3); pinned status is irrelevant because
    # the user explicitly asked to delete EVERYTHING.
    registry = getattr(ctx, "artifact_registry", None)
    if registry is not None:
        await registry.delete_all()

    async with ctx.db() as session:
        # Use the underlying SA connection for DML (avoids SQLModel exec() warning).
        conn = await session.connection()
        await conn.execute(sa.delete(Attachment))
        await conn.execute(sa.delete(Message))
        await conn.execute(sa.delete(Conversation))
        await session.commit()

    # Remove all upload directories.
    uploads_base = PROJECT_ROOT / "data" / "uploads"
    if uploads_base.exists():
        removed_dirs = 0
        for child in uploads_base.iterdir():
            if child.is_dir():
                await asyncio.to_thread(shutil.rmtree, child, True)
                removed_dirs += 1
        logger.debug("Removed {} upload directories", removed_dirs)

    logger.info("Deleted all conversations")
    return {"status": "deleted"}


@router.delete("/chat/conversations/{conversation_id}", response_model=DeleteConversationResponse)
async def delete_conversation(
    conversation_id: uuid.UUID, request: Request
) -> dict[str, str]:
    """Delete a conversation and all its messages.

    Uses bulk SQL DELETE statements to avoid async lazy-loading issues
    with SQLAlchemy ORM relationships.  Artifact cleanup (detach pinned,
    delete unpinned rows + blobs) is delegated to the unified registry.
    """
    ctx = _ctx(request)
    async with ctx.db() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # ── Artifacts (single implementation in the registry) ──────────────
    # Separate transaction: on partial failure re-issuing the delete is safe (idempotent).
    registry = getattr(ctx, "artifact_registry", None)
    if registry is not None:
        await registry.delete_for_conversation(conversation_id)

    async with ctx.db() as session:
        # Collect message IDs for attachment cleanup.
        msg_stmt = select(Message.id).where(
            Message.conversation_id == conversation_id
        )
        results = await session.exec(msg_stmt)
        msg_ids: list[uuid.UUID] = list(results.all())

        # Use the underlying SA connection for DML (avoids SQLModel exec() warning).
        conn = await session.connection()

        # Bulk-delete attachments for those messages.
        if msg_ids:
            await conn.execute(
                sa.delete(Attachment).where(
                    Attachment.message_id.in_(msg_ids)  # type: ignore[union-attr]
                )
            )

        # Bulk-delete messages.
        await conn.execute(
            sa.delete(Message).where(
                Message.conversation_id == conversation_id
            )
        )

        # Bulk-delete conversation (avoids ORM relationship lazy-load).
        await conn.execute(
            sa.delete(Conversation).where(
                Conversation.id == conversation_id
            )
        )

        await session.commit()

    # Clean up uploaded files for this conversation.
    upload_dir = PROJECT_ROOT / "data" / "uploads" / str(conversation_id)
    if upload_dir.exists():
        await asyncio.to_thread(shutil.rmtree, upload_dir, True)
        logger.debug("Removed upload dir {}", upload_dir)

    # Kill any live interactive terminal sessions (PTYs + process trees)
    # for this conversation — they have no DB row to cascade-delete.
    terminal_manager = getattr(ctx, "terminal_session_manager", None)
    if terminal_manager is not None:
        try:
            await terminal_manager.cleanup_conversation(str(conversation_id))
        except Exception as exc:
            logger.warning(
                "Terminal cleanup failed for {}: {}", conversation_id, exc,
            )

    return {"status": "deleted"}


@router.post("/chat/conversations/{conversation_id}/title", response_model=TitleUpdateResponse)
async def update_conversation_title(
    conversation_id: uuid.UUID,
    request: Request,
) -> dict[str, Any]:
    """Update the title of a conversation.

    Body: ``{"title": "new title"}``
    """
    ctx = _ctx(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400, detail="Invalid JSON body",
        ) from None

    raw_title = body.get("title")
    if raw_title is None:
        raw_title = ""
    if not isinstance(raw_title, str):
        raise HTTPException(
            status_code=400, detail="title must be a string",
        )
    new_title = raw_title.strip()
    if len(new_title) > 500:
        raise HTTPException(status_code=400, detail="Title too long (max 500 chars)")

    async with ctx.db() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conv.title = new_title
        conv.updated_at = _utcnow()
        await session.commit()

        return {
            "id": str(conv.id),
            "title": conv.title,
            "updated_at": conv.updated_at.isoformat(),
        }


@router.post(
    "/chat/conversations/{conversation_id}/switch-version",
    response_model=SwitchVersionResponse,
)
async def switch_version(
    conversation_id: uuid.UUID,
    request: Request,
) -> dict[str, Any]:
    """Switch the active version for a message version group.

    Body::

        {"version_group_id": "uuid", "version_index": 0}

    Returns:
        Updated ``active_versions`` map and ``updated_at`` timestamp.
    """
    ctx = _ctx(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(
            status_code=400, detail="Invalid JSON body",
        ) from None

    vg_id_raw: str | None = body.get("version_group_id")
    version_idx: int | None = body.get("version_index")

    if not vg_id_raw or version_idx is None:
        raise HTTPException(
            status_code=400,
            detail="Missing version_group_id or version_index",
        )

    try:
        vg_id = uuid.UUID(vg_id_raw)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid version_group_id",
        ) from None

    if isinstance(version_idx, bool) or not isinstance(version_idx, int) or version_idx < 0:
        raise HTTPException(
            status_code=400, detail="version_index must be a non-negative integer",
        )

    async with ctx.db() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(
                status_code=404, detail="Conversation not found",
            )

        # Verify the requested version exists.
        exists = await session.scalar(
            sa.select(sa.func.count(Message.id)).where(
                Message.conversation_id == conversation_id,
                Message.version_group_id == vg_id,
                Message.version_index == version_idx,
            )
        )
        if not exists:
            raise HTTPException(
                status_code=404,
                detail="Version not found",
            )

        av = dict(conv.active_versions or {})
        av[str(vg_id)] = version_idx
        conv.active_versions = av
        conv.updated_at = _utcnow()
        await session.commit()

        return {
            "id": str(conv.id),
            "active_versions": conv.active_versions,
            "updated_at": conv.updated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# REST — branch conversation
# ---------------------------------------------------------------------------


@router.post(
    "/chat/conversations/{conversation_id}/branch",
    response_model=ConversationSummaryResponse,
)
async def branch_conversation(
    conversation_id: str,
    body: BranchConversationRequest,
    request: Request,
) -> ConversationSummaryResponse:
    """Create a new conversation by branching from a specific message.

    Copies all messages from the beginning of the source conversation
    up through ``from_message_id`` (following the active version branch)
    into a new independent conversation.  File attachments are physically
    copied under a new upload directory.

    Args:
        conversation_id: UUID of the source conversation.
        body: Branch parameters — from_message_id and optional title.
        request: FastAPI request (used to extract AppContext).

    Returns:
        Metadata for the newly created conversation.

    Raises:
        HTTPException 400: ``from_message_id`` is not a valid UUID.
        HTTPException 404: Source conversation or target message not found.
        HTTPException 422: Target message is not in the active version branch.
    """
    try:
        src_conv_id = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid conversation_id",
        ) from None

    try:
        from_msg_id = uuid.UUID(body.from_message_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid from_message_id",
        ) from None

    ctx = _ctx(request)
    async with ctx.db() as session:
        conv = await session.get(Conversation, src_conv_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Load all messages ordered by (created_at, id).
        msg_stmt = (
            select(Message)
            .where(Message.conversation_id == src_conv_id)
            .order_by(Message.created_at, Message.id)
        )
        msg_results = await session.exec(msg_stmt)
        raw_orm_messages = msg_results.all()

        # Build dicts for the filter helper (same shape as _build_conversation_data).
        raw_message_dicts = [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "thinking_content": m.thinking_content,
                "tool_calls": m.tool_calls,
                "tool_call_id": m.tool_call_id,
                "created_at": m.created_at.isoformat(),
                "version_group_id": str(m.version_group_id) if m.version_group_id else None,
                "version_index": m.version_index,
            }
            for m in raw_orm_messages
        ]

        av_map: dict[str, int] = dict(conv.active_versions or {})
        filtered_dicts = _filter_messages_by_active_versions(raw_message_dicts, av_map)

        from_msg_id_str = str(from_msg_id)
        target_idx: int | None = None
        for i, md in enumerate(filtered_dicts):
            if md["id"] == from_msg_id_str:
                target_idx = i
                break

        if target_idx is None:
            # Check whether message exists but is on an inactive branch.
            all_ids = {md["id"] for md in raw_message_dicts}
            if from_msg_id_str in all_ids:
                raise HTTPException(
                    status_code=422,
                    detail="Message belongs to an inactive version branch",
                )
            raise HTTPException(
                status_code=404, detail="Message not found in this conversation"
            )

        sliced_dicts = filtered_dicts[: target_idx + 1]

        # Build new conversation.
        new_title = body.title or (
            f"{conv.title} (diramazione)" if conv.title else "Diramazione"
        )
        new_conv = Conversation(title=new_title)
        session.add(new_conv)
        await session.flush()  # obtain new_conv.id

        # Copy messages and their attachments.
        for msg_dict in sliced_dicts:
            src_msg = await session.get(Message, uuid.UUID(msg_dict["id"]))
            if src_msg is None:
                # Should never happen — we just loaded these from the same session.
                logger.warning("Branch: source message {} missing, skipping", msg_dict["id"])
                continue

            new_msg = Message(
                conversation_id=new_conv.id,
                role=src_msg.role,
                content=src_msg.content,
                tool_calls=src_msg.tool_calls,
                tool_call_id=src_msg.tool_call_id,
                thinking_content=src_msg.thinking_content,
                version_group_id=None,
                version_index=0,
                created_at=src_msg.created_at,
            )
            session.add(new_msg)
            await session.flush()  # obtain new_msg.id

            att_stmt = select(Attachment).where(Attachment.message_id == src_msg.id)
            att_results = await session.exec(att_stmt)
            for src_att in att_results.all():
                old_path = PROJECT_ROOT / src_att.file_path
                ext = Path(src_att.file_path).suffix
                new_att_id = uuid.uuid4()
                new_file_id_str = str(uuid.uuid4())
                new_rel_path = (
                    Path("data") / "uploads" / str(new_conv.id) / f"{new_file_id_str}{ext}"
                )
                new_abs_path = PROJECT_ROOT / new_rel_path

                if await asyncio.to_thread(old_path.exists):
                    await asyncio.to_thread(
                        new_abs_path.parent.mkdir, parents=True, exist_ok=True
                    )
                    await asyncio.to_thread(shutil.copy2, old_path, new_abs_path)
                else:
                    logger.warning("Branch: source attachment missing: {}", old_path)

                new_att = Attachment(
                    id=new_att_id,
                    message_id=new_msg.id,
                    filename=src_att.filename,
                    content_type=src_att.content_type,
                    file_path=str(new_rel_path),
                )
                session.add(new_att)

        new_conv.updated_at = _utcnow()
        await session.commit()

        return ConversationSummaryResponse(
            id=str(new_conv.id),
            title=new_conv.title,
            created_at=new_conv.created_at.isoformat(),
            updated_at=new_conv.updated_at.isoformat(),
            message_count=len(sliced_dicts),
        )


# ---------------------------------------------------------------------------
# REST — create conversation
# ---------------------------------------------------------------------------


@router.post("/chat/conversations", response_model=ConversationSummaryResponse)
async def create_conversation(request: Request) -> dict[str, Any]:
    """Create a new empty conversation and persist it immediately.

    Accepts an optional JSON body::

        {"id": "uuid", "title": "optional title"}

    If ``id`` is provided the frontend's UUID is used; otherwise a new one
    is generated server-side.

    Returns:
        A ``ConversationSummary``-shaped dict.
    """
    ctx = _ctx(request)

    body: dict[str, Any] = {}
    # An empty / absent body is fine — fall back to server-side defaults.
    with contextlib.suppress(Exception):
        body = await request.json()

    if body.get("id"):
        try:
            conv_id = uuid.UUID(body["id"])
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400, detail="Invalid conversation id",
            ) from None
    else:
        conv_id = uuid.uuid4()
    title: str | None = body.get("title")
    if title is not None:
        if not isinstance(title, str):
            raise HTTPException(status_code=400, detail="title must be a string")
        if len(title) > 500:
            raise HTTPException(status_code=400, detail="Title too long (max 500 chars)")

    async with ctx.db() as session:
        existing = await session.get(Conversation, conv_id)
        if existing is not None:
            # Idempotent: return the existing conversation instead of erroring.
            # This prevents spurious 409 errors when the frontend retries creation
            # on reconnect or when two concurrent calls race.
            message_count: int = await session.scalar(
                sa.select(sa.func.count(Message.id)).where(
                    Message.conversation_id == existing.id
                )
            ) or 0
            return {
                "id": str(existing.id),
                "title": existing.title,
                "created_at": existing.created_at.isoformat(),
                "updated_at": existing.updated_at.isoformat(),
                "message_count": message_count,
            }

        conv = Conversation(id=conv_id, title=title)
        session.add(conv)
        try:
            await session.commit()
        except sa.exc.IntegrityError:
            # Race condition: another concurrent request already inserted
            # this id between our GET check and the INSERT.  Roll back and
            # return the existing row (idempotent).
            await session.rollback()
            existing = await session.get(Conversation, conv_id)
            if existing is None:
                raise HTTPException(
                    status_code=409,
                    detail="Conversation id conflict",
                ) from None
            message_count: int = await session.scalar(
                sa.select(sa.func.count(Message.id)).where(
                    Message.conversation_id == existing.id
                )
            ) or 0
            return {
                "id": str(existing.id),
                "title": existing.title,
                "created_at": existing.created_at.isoformat(),
                "updated_at": existing.updated_at.isoformat(),
                "message_count": message_count,
            }
        await session.refresh(conv)

        return {
            "id": str(conv.id),
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "message_count": 0,
        }
