"""O.M.N.I.A. — Chat endpoints (WebSocket streaming + REST history)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from loguru import logger
import sqlalchemy as sa
from sqlalchemy import func as sa_func
from sqlmodel import select

from backend.core.config import PROJECT_ROOT
from backend.core.context import AppContext
from backend.db.models import Attachment, Conversation, Message
from backend.services.conversation_file_manager import ConversationFileManager
from backend.services.llm_service import LLMService
from backend.api.routes._tool_loop import run_tool_loop

router = APIRouter(tags=["chat"])

# Base path for uploaded files.
_UPLOADS_BASE: Path = (PROJECT_ROOT / "data" / "uploads").resolve()

# Magic byte signatures for allowed image types.
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "image/jpeg": [b"\xff\xd8"],
    "image/png": [b"\x89PNG"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],
}

# Active WebSocket connections per IP (for rate limiting).
_ws_connections: dict[str, int] = defaultdict(int)
# Per-loop WS locks: maps event-loop id → asyncio.Lock.  This allows tests
# that run in multiple event loops (e.g. threads with TestClient) to each
# get a lock bound to the correct loop.
_ws_locks: dict[int, asyncio.Lock] = {}


def _get_ws_lock() -> asyncio.Lock:
    """Return an ``asyncio.Lock`` bound to the *current* event loop."""
    loop = asyncio.get_running_loop()
    lock = _ws_locks.get(id(loop))
    if lock is None:
        lock = asyncio.Lock()
        _ws_locks[id(loop)] = lock
    return lock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ctx(ws_or_request: Any) -> AppContext:
    """Extract the ``AppContext`` from the ASGI app state."""
    return ws_or_request.app.state.context


def _attachment_url(file_path: str) -> str:
    """Build a safe ``/uploads/…`` URL from an attachment's file_path.

    Uses :meth:`pathlib.Path.relative_to` instead of string splitting
    to avoid path-traversal issues.  Components are percent-encoded.
    """
    try:
        relative = Path(file_path).resolve().relative_to(_UPLOADS_BASE)
        return f"/uploads/{quote(str(relative), safe='/')}"
    except ValueError:
        logger.warning("Attachment path outside uploads base: {}", file_path)
        return ""


def _verify_magic_bytes(
    data: bytes, claimed_type: str,
) -> bool:
    """Return ``True`` if the file's magic bytes match *claimed_type*."""
    signatures = _MAGIC_BYTES.get(claimed_type)
    if signatures is None:
        return False
    return any(data[:len(sig)] == sig for sig in signatures)


async def _build_conversation_data(
    session: Any, conv_id: uuid.UUID,
) -> dict[str, Any]:
    """Build the full conversation dict (with messages + attachments) from DB.

    The returned attachment dicts include **both** ``url`` (for API / frontend
    consumption) and ``file_path`` (for file-level backup / recovery).

    Args:
        session: An active async DB session.
        conv_id: The conversation UUID.

    Returns:
        A dict matching the JSON file schema.
    """
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        return {}

    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
    )
    results = await session.exec(msg_stmt)
    messages = results.all()

    msg_ids = [m.id for m in messages]
    att_map: dict[uuid.UUID, list[dict[str, str]]] = {}
    if msg_ids:
        att_stmt = select(Attachment).where(
            Attachment.message_id.in_(msg_ids)  # type: ignore[union-attr]
        )
        att_results = await session.exec(att_stmt)
        for att in att_results.all():
            url = _attachment_url(att.file_path)
            att_map.setdefault(att.message_id, []).append(
                {
                    "file_id": str(att.id),
                    "url": url,
                    "filename": att.filename,
                    "content_type": att.content_type,
                    "file_path": att.file_path,
                }
            )

    return {
        "id": str(conv.id),
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "thinking_content": m.thinking_content,
                "tool_calls": m.tool_calls,
                "tool_call_id": m.tool_call_id,
                "created_at": m.created_at.isoformat(),
                "attachments": att_map.get(m.id) or None,
            }
            for m in messages
        ],
    }


async def _sync_conversation_to_file(
    session: Any, conv_id: uuid.UUID, file_manager: ConversationFileManager,
) -> None:
    """Build the conversation data from DB and persist it to a JSON file.

    Args:
        session: An active async DB session (post-commit so data is flushed).
        conv_id: The conversation UUID.
        file_manager: The file manager instance.
    """
    data = await _build_conversation_data(session, conv_id)
    if data:
        await file_manager.save(data)


def _build_mcp_context(ctx: AppContext) -> str | None:
    """Build a brief context block listing active MCP servers and their roots.

    Injected into the system prompt so the LLM knows which MCP servers are
    available and what directories (for filesystem) are accessible.

    Args:
        ctx: Application context with config.

    Returns:
        A markdown context block, or None if no MCP servers are configured.
    """
    enabled = [s for s in ctx.config.mcp.servers if s.enabled]
    if not enabled:
        return None

    lines = ["[MCP SERVERS ATTIVI]"]
    for srv in enabled:
        if srv.transport == "stdio" and srv.command:
            # Extract path args (anything starting with a drive letter or /)
            roots = [
                arg for arg in srv.command[1:]
                if arg and (arg[0].isalpha() and len(arg) > 1 and arg[1] == ":" or arg.startswith("/"))
            ]
            root_info = f"  root permessa: {', '.join(roots)}" if roots else ""
            lines.append(f"- {srv.name} (stdio){root_info}")
        else:
            url_info = f"  url: {srv.url}" if srv.url else ""
            lines.append(f"- {srv.name} (sse){url_info}")
    lines.append("[/MCP SERVERS ATTIVI]")
    return "\n".join(lines)


def _format_memory_context(
    memories: list[dict[str, Any]], max_chars: int,
) -> str:
    """Serialize relevant memories into a text block for the system prompt."""
    lines = ["[RELEVANT MEMORIES]"]
    total = 0
    for m in memories:
        entry = m.get("entry")
        if entry is None:
            continue
        cat = getattr(entry, "category", None) or "general"
        content = getattr(entry, "content", "")
        line = f"- [{cat}] {content}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WebSocket — streaming chat
# ---------------------------------------------------------------------------


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """Accept a WebSocket, stream LLM responses token-by-token.

    Incoming JSON::

        {"content": "user message", "conversation_id": "optional-uuid"}

    Outgoing JSON (one per frame)::

        {"type": "token", "content": "..."} | {"type": "done",
         "conversation_id": "...", "message_id": "..."}
    """
    ctx = _ctx(websocket)
    max_ws = ctx.config.server.ws_max_connections_per_ip

    # Track per-IP WebSocket connections.
    client_ip = (
        websocket.client.host if websocket.client else "unknown"
    )
    ws_lock = _get_ws_lock()
    async with ws_lock:
        if _ws_connections.get(client_ip, 0) >= max_ws:
            await websocket.close(
                code=1008, reason="Too many connections",
            )
            logger.warning(
                "WS rejected for {} — {} active connections",
                client_ip, _ws_connections[client_ip],
            )
            return
        await websocket.accept()
        _ws_connections[client_ip] += 1

    llm: LLMService = ctx.llm_service  # type: ignore[assignment]
    session_factory = ctx.db

    if llm is None or session_factory is None:
        await websocket.send_json(
            {"type": "error", "content": "Server not ready \u2014 services not initialized"}
        )
        await websocket.close(code=1011)
        async with ws_lock:
            _ws_connections[client_ip] = max(0, _ws_connections[client_ip] - 1)
            if _ws_connections[client_ip] <= 0:
                _ws_connections.pop(client_ip, None)
        return

    try:
        message_buffer: list[str] = []

        while True:
            if message_buffer:
                raw = message_buffer.pop(0)
            else:
                raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {"type": "error", "content": "Invalid JSON"}
                )
                continue

            user_content: str = data.get("content", "").strip()
            if not user_content:
                await websocket.send_json(
                    {"type": "error", "content": "Empty message"}
                )
                continue

            MAX_USER_MESSAGE_LENGTH = 50_000  # 50K characters
            if len(user_content) > MAX_USER_MESSAGE_LENGTH:
                await websocket.send_json(
                    {"type": "error", "content": "Message too long"}
                )
                continue

            conv_id_raw: str | None = data.get("conversation_id")
            attachment_ids: list[str] = data.get("attachments", [])

            async with session_factory() as session:
                # --- resolve or create conversation -----------------------
                if conv_id_raw:
                    try:
                        conv_id = uuid.UUID(conv_id_raw)
                    except ValueError:
                        await websocket.send_json(
                            {"type": "error", "content": "Invalid conversation_id"}
                        )
                        continue
                    conv = await session.get(Conversation, conv_id)
                    if conv is None:
                        conv = Conversation(id=conv_id)
                        session.add(conv)
                        await session.flush()
                else:
                    conv = Conversation()
                    session.add(conv)
                    await session.flush()
                    conv_id = conv.id

                # --- save user message ------------------------------------
                user_msg = Message(
                    conversation_id=conv_id,
                    role="user",
                    content=user_content,
                )
                session.add(user_msg)
                await session.flush()

                # --- link uploaded attachments to the user message --------
                attachment_info: list[dict[str, str]] = []
                for att_id_str in attachment_ids:
                    try:
                        att_id = uuid.UUID(att_id_str)
                    except ValueError:
                        logger.warning("Invalid attachment id: {}", att_id_str)
                        continue
                    att = await session.get(Attachment, att_id)
                    if att is None:
                        logger.warning("Attachment {} not found", att_id_str)
                        continue
                    att.message_id = user_msg.id
                    attachment_info.append(
                        {
                            "file_path": str(PROJECT_ROOT / att.file_path),
                            "content_type": att.content_type,
                        }
                    )
                if attachment_info:
                    await session.flush()

                # Commit conversation + user message so they are visible to
                # other sessions (REST endpoints) immediately.  The session
                # uses expire_on_commit=False so `conv` stays usable.
                await session.commit()

                # --- fetch history for context ----------------------------
                stmt = (
                    select(Message)
                    .where(Message.conversation_id == conv_id)
                    .order_by(Message.created_at)
                )
                results = await session.exec(stmt)
                history: list[dict[str, Any]] = [
                    {
                        "role": m.role,
                        "content": m.content,
                        "tool_calls": m.tool_calls,
                        "tool_call_id": m.tool_call_id,
                    }
                    for m in results.all()
                ]

                # --- fetch available tools for LLM ------------------------
                tools: list[dict[str, Any]] | None = None
                if ctx.tool_registry and ctx.config.llm.tools_enabled:
                    tools = await ctx.tool_registry.get_available_tools()
                    if tools and ctx.config.llm.max_tools > 0:
                        tools = ctx.tool_registry.limit_tools(
                            tools,
                            max_tools=ctx.config.llm.max_tools,
                            priority_plugins=ctx.config.llm.priority_plugins,
                        )
                    if not tools:
                        tools = None  # empty list confuses some LLMs

                # --- pre-read attachment bytes async (avoid blocking I/O) --
                if attachment_info:
                    for att in attachment_info:
                        fp = Path(att["file_path"])
                        att["_bytes"] = await asyncio.to_thread(fp.read_bytes)

                # --- retrieve relevant memories (Phase 9) -----------------
                memory_context: str | None = None
                if (
                    ctx.memory_service
                    and ctx.config.memory.inject_in_context
                ):
                    try:
                        relevant = await ctx.memory_service.search(
                            query=user_content,
                            k=ctx.config.memory.top_k,
                            filter={"scope": "long_term"},
                        )
                        if relevant:
                            memory_context = _format_memory_context(
                                relevant,
                                ctx.config.memory.context_max_chars,
                            )
                    except Exception as exc:
                        logger.warning(
                            "Memory retrieval failed: {}", exc,
                        )

                # --- inject active MCP server list (Phase 11) -------------
                mcp_ctx = _build_mcp_context(ctx)
                if mcp_ctx:
                    memory_context = (
                        f"{memory_context}\n\n{mcp_ctx}"
                        if memory_context
                        else mcp_ctx
                    )

                # --- call LLM (streaming) ---------------------------------
                messages = llm.build_messages(
                    user_content,
                    history=history[:-1],  # history already has user msg
                    attachments=attachment_info or None,
                    memory_context=memory_context,
                )

                full_content = ""
                thinking_content = ""
                tool_calls_collected: list[dict[str, Any]] = []
                finish_reason = "stop"
                cancel_event = asyncio.Event()

                async def _stream_and_collect() -> None:
                    """Consume LLM stream, accumulate content and relay to WS."""
                    nonlocal full_content, thinking_content, finish_reason
                    async for event in llm.chat(
                        messages,
                        tools=tools,
                        cancel_event=cancel_event,
                        user_content=user_content,
                        conversation_id=str(conv_id),
                        attachments=attachment_info or None,
                        memory_context=memory_context,
                    ):
                        etype = event["type"]
                        if etype == "token":
                            full_content += event["content"]
                            await websocket.send_json(event)
                        elif etype == "thinking":
                            thinking_content += event["content"]
                            await websocket.send_json(event)
                        elif etype == "tool_call":
                            tool_calls_collected.append(event)
                            await websocket.send_json(event)
                        elif etype == "done":
                            finish_reason = event.get(
                                "finish_reason", "stop",
                            )

                async def _listen_for_cancel(
                    stream_task: asyncio.Task[None],
                    msg_buffer: list[str],
                ) -> None:
                    """Read WS messages while streaming; set cancel on request.

                    When the client sends ``{"type": "cancel"}`` or disconnects,
                    we set *cancel_event* **and** cancel the *stream_task* so that
                    even a blocked ``httpx.stream()`` call (waiting for response
                    headers from a slow reasoning model) is interrupted immediately.
                    Non-cancel messages are buffered in *msg_buffer* for later
                    processing by the main loop.
                    """
                    while not stream_task.done():
                        try:
                            raw_cancel = await asyncio.wait_for(
                                websocket.receive_text(), timeout=0.5,
                            )
                            cancel_data = json.loads(raw_cancel)
                            if cancel_data.get("type") == "cancel":
                                cancel_event.set()
                                stream_task.cancel()
                                logger.debug("Client requested stream cancel")
                                return
                            else:
                                msg_buffer.append(raw_cancel)
                                logger.debug("Buffered non-cancel message during streaming")
                        except asyncio.TimeoutError:
                            continue
                        except WebSocketDisconnect:
                            cancel_event.set()
                            stream_task.cancel()
                            return
                        except Exception:
                            logger.warning(
                                "Non-fatal error in cancel listener, ignoring"
                            )
                            continue

                stream_task = asyncio.create_task(_stream_and_collect())
                cancel_task = asyncio.create_task(
                    _listen_for_cancel(stream_task, message_buffer),
                )

                try:
                    await stream_task
                except asyncio.CancelledError:
                    # Task was cancelled by _listen_for_cancel (user
                    # pressed stop or disconnected while the LLM was
                    # still preparing its response).  Treat as cancel.
                    logger.debug("LLM stream task cancelled")
                    cancel_event.set()
                except Exception:
                    logger.exception("LLM streaming error")
                    finish_reason = "error"
                    await websocket.send_json(
                        {"type": "error", "content": "LLM error"},
                    )
                    await websocket.send_json({
                        "type": "done",
                        "conversation_id": str(conv_id),
                        "message_id": "",
                        "finish_reason": "error",
                    })
                    await session.rollback()
                    continue
                finally:
                    cancel_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await cancel_task

                # --- handle cancellation before tool loop -----------------
                if cancel_event.is_set():
                    asst_msg_id = ""
                    if full_content or thinking_content:
                        asst_msg = Message(
                            conversation_id=conv_id,
                            role="assistant",
                            content=full_content,
                            thinking_content=thinking_content or None,
                        )
                        session.add(asst_msg)
                        conv.updated_at = _utcnow()
                        if conv.title is None and user_content:
                            conv.title = user_content[:100]
                        await session.commit()
                        asst_msg_id = str(asst_msg.id)
                        if ctx.conversation_file_manager:
                            await _sync_conversation_to_file(
                                session, conv_id,
                                ctx.conversation_file_manager,
                            )
                    await websocket.send_json({
                        "type": "done",
                        "conversation_id": str(conv_id),
                        "message_id": asst_msg_id,
                        "finish_reason": "cancelled",
                    })
                    continue

                # --- tool calling loop (if LLM requested tools) -----------
                if tool_calls_collected and finish_reason != "cancelled":
                    try:
                        full_content, thinking_content = await run_tool_loop(
                            websocket=websocket,
                            ctx=ctx,
                            session=session,
                            conv_id=conv_id,
                            llm=llm,
                            tool_calls_from_llm=tool_calls_collected,
                            full_content=full_content,
                            thinking_content=thinking_content,
                            max_iterations=ctx.config.llm.max_tool_iterations,
                            confirmation_timeout_s=ctx.config.pc_automation.confirmation_timeout_s,
                            client_ip=client_ip,
                            sync_fn=_sync_conversation_to_file,
                            cancel_event=cancel_event,
                            memory_context=memory_context,
                        )
                    except WebSocketDisconnect:
                        # Save any pending assistant content before propagating.
                        logger.debug("WS disconnected during tool loop")
                        if full_content:
                            recovery_msg = Message(
                                conversation_id=conv_id,
                                role="assistant",
                                content=full_content,
                                thinking_content=thinking_content or None,
                            )
                            session.add(recovery_msg)
                            conv.updated_at = _utcnow()
                            await session.commit()
                            if ctx.conversation_file_manager:
                                await _sync_conversation_to_file(
                                    session, conv_id,
                                    ctx.conversation_file_manager,
                                )
                        raise
                    except Exception:
                        logger.exception("Tool loop error")
                        await websocket.send_json(
                            {"type": "error", "content": "Tool execution error"}
                        )
                        await websocket.send_json({
                            "type": "done",
                            "conversation_id": str(conv_id),
                            "message_id": "",
                            "finish_reason": "error",
                        })
                        await session.rollback()
                        continue

                # --- handle cancellation during tool loop -----------------
                if cancel_event.is_set():
                    conv.updated_at = _utcnow()
                    if conv.title is None and user_content:
                        conv.title = user_content[:100]
                    await session.commit()
                    if ctx.conversation_file_manager:
                        await _sync_conversation_to_file(
                            session, conv_id,
                            ctx.conversation_file_manager,
                        )
                    await websocket.send_json({
                        "type": "done",
                        "conversation_id": str(conv_id),
                        "message_id": "",
                        "finish_reason": "cancelled",
                    })
                    continue

                # --- save assistant message --------------------------------
                try:
                    asst_msg_id = ""

                    # Only save a final assistant message if there is actual
                    # content.  When tool_calls were executed, intermediate
                    # messages are already persisted by the tool loop.
                    if full_content.strip() or not tool_calls_collected:
                        asst_msg = Message(
                            conversation_id=conv_id,
                            role="assistant",
                            content=full_content,
                            thinking_content=thinking_content or None,
                        )
                        session.add(asst_msg)
                        asst_msg_id = str(asst_msg.id)

                    # --- update conversation timestamp -------------------------
                    conv.updated_at = _utcnow()
                    if conv.title is None and user_content:
                        conv.title = user_content[:100]

                    await session.commit()

                    # Sync conversation to JSON file.
                    if ctx.conversation_file_manager:
                        await _sync_conversation_to_file(
                            session, conv_id,
                            ctx.conversation_file_manager,
                        )
                except Exception:
                    logger.exception("DB commit error after streaming")
                    await session.rollback()
                    await websocket.send_json(
                        {"type": "error", "content": "Failed to save response"}
                    )
                    await websocket.send_json({
                        "type": "done",
                        "conversation_id": str(conv_id),
                        "message_id": "",
                        "finish_reason": "error",
                    })
                    continue

                await websocket.send_json(
                    {
                        "type": "done",
                        "conversation_id": str(conv_id),
                        "message_id": asst_msg_id,
                        "finish_reason": finish_reason,
                    }
                )

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception:
        logger.exception("WebSocket unexpected error")
    finally:
        async with ws_lock:
            _ws_connections[client_ip] = max(
                0, _ws_connections[client_ip] - 1,
            )
            if _ws_connections[client_ip] <= 0:
                _ws_connections.pop(client_ip, None)


# ---------------------------------------------------------------------------
# REST — conversation history
# ---------------------------------------------------------------------------


@router.get("/chat/conversations")
async def list_conversations(request: Request) -> list[dict[str, Any]]:
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

        return [
            {
                "id": str(conv.id),
                "title": conv.title,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "message_count": msg_count,
            }
            for conv, msg_count in rows
        ]


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
            .order_by(Message.created_at)
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
                        "url": _attachment_url(att.file_path),
                        "filename": att.filename,
                        "content_type": att.content_type,
                    }
                )

        return {
            "id": str(conv.id),
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "thinking_content": m.thinking_content,
                    "tool_calls": m.tool_calls,
                    "tool_call_id": m.tool_call_id,
                    "created_at": m.created_at.isoformat(),
                    "attachments": att_map.get(m.id, []) or None,
                }
                for m in messages
            ],
        }


@router.delete("/chat/conversations")
async def delete_all_conversations(request: Request) -> dict[str, Any]:
    """Delete ALL conversations, messages, attachments, and associated files."""
    ctx = _ctx(request)
    async with ctx.db() as session:
        # Use the underlying SA connection for DML (avoids SQLModel exec() warning).
        conn = await session.connection()
        await conn.execute(sa.delete(Attachment))
        await conn.execute(sa.delete(Message))
        await conn.execute(sa.delete(Conversation))
        await session.commit()

    # Remove all JSON conversation files.
    file_manager: ConversationFileManager | None = ctx.conversation_file_manager
    deleted_files = 0
    if file_manager:
        deleted_files = await file_manager.delete_all()

    # Remove all upload directories.
    uploads_base = PROJECT_ROOT / "data" / "uploads"
    if uploads_base.exists():
        removed_dirs = 0
        for child in uploads_base.iterdir():
            if child.is_dir():
                await asyncio.to_thread(shutil.rmtree, child, True)
                removed_dirs += 1
        logger.debug("Removed {} upload directories", removed_dirs)

    logger.info("Deleted all conversations ({} files)", deleted_files)
    return {"status": "deleted", "deleted_files": deleted_files}


@router.delete("/chat/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID, request: Request
) -> dict[str, str]:
    """Delete a conversation and all its messages.

    Uses bulk SQL DELETE statements to avoid async lazy-loading issues
    with SQLAlchemy ORM relationships.
    """
    ctx = _ctx(request)
    async with ctx.db() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

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

        # Remove JSON conversation file.
        file_manager: ConversationFileManager | None = (
            ctx.conversation_file_manager
        )
        if file_manager:
            await file_manager.delete(str(conversation_id))

        # Clean up uploaded files for this conversation.
        upload_dir = PROJECT_ROOT / "data" / "uploads" / str(conversation_id)
        if upload_dir.exists():
            await asyncio.to_thread(shutil.rmtree, upload_dir, True)
            logger.debug("Removed upload dir {}", upload_dir)

        return {"status": "deleted"}


@router.post("/chat/conversations/{conversation_id}/title")
async def update_conversation_title(
    conversation_id: uuid.UUID,
    request: Request,
) -> dict[str, Any]:
    """Update the title of a conversation.

    Body: ``{"title": "new title"}``
    """
    ctx = _ctx(request)
    body = await request.json()
    new_title: str = body.get("title", "")

    async with ctx.db() as session:
        conv = await session.get(Conversation, conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        conv.title = new_title
        conv.updated_at = _utcnow()
        await session.commit()

        # Sync to JSON file.
        if ctx.conversation_file_manager:
            await _sync_conversation_to_file(
                session, conversation_id, ctx.conversation_file_manager,
            )

        return {
            "id": str(conv.id),
            "title": conv.title,
            "updated_at": conv.updated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# REST — create / export / import conversations
# ---------------------------------------------------------------------------


@router.post("/chat/conversations")
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
    try:
        body = await request.json()
    except Exception:
        pass  # empty body is fine

    if body.get("id"):
        try:
            conv_id = uuid.UUID(body["id"])
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid conversation id")
    else:
        conv_id = uuid.uuid4()
    title: str | None = body.get("title")

    async with ctx.db() as session:
        existing = await session.get(Conversation, conv_id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="Conversation already exists",
            )

        conv = Conversation(id=conv_id, title=title)
        session.add(conv)
        await session.commit()
        await session.refresh(conv)

        if ctx.conversation_file_manager:
            await _sync_conversation_to_file(
                session, conv.id, ctx.conversation_file_manager,
            )

        return {
            "id": str(conv.id),
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "message_count": 0,
        }


@router.get("/chat/conversations/{conversation_id}/export")
async def export_conversation(
    conversation_id: uuid.UUID, request: Request,
) -> dict[str, Any]:
    """Export a full conversation with all messages and metadata.

    Args:
        conversation_id: UUID of the conversation to export.

    Returns:
        The complete conversation JSON including messages and attachments.
    """
    ctx = _ctx(request)
    async with ctx.db() as session:
        data = await _build_conversation_data(session, conversation_id)
        if not data:
            raise HTTPException(
                status_code=404, detail="Conversation not found",
            )
        return data


@router.get("/chat/conversations/{conversation_id}/file-path")
async def get_conversation_file_path(
    conversation_id: uuid.UUID, request: Request,
) -> dict[str, str]:
    """Return the absolute filesystem path of the conversation JSON file.

    Used by the Electron frontend to open the file in the system explorer.
    """
    ctx = _ctx(request)
    fm: ConversationFileManager | None = ctx.conversation_file_manager
    if fm is None:
        raise HTTPException(
            status_code=503,
            detail="File manager not available",
        )

    file_path = fm.base_dir / f"{conversation_id}.json"
    return {"path": str(file_path)}


@router.post("/chat/conversations/import")
async def import_conversation(request: Request) -> dict[str, Any]:
    """Import a conversation from a JSON export.

    Expects the full conversation JSON (same schema as export) in the
    request body.  If a conversation with the same ``id`` already exists
    the request is rejected with 409.

    Returns:
        A ``ConversationSummary``-shaped dict for the imported conversation.
    """
    ctx = _ctx(request)

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if "id" not in body:
        raise HTTPException(status_code=400, detail="Missing 'id' field")

    try:
        conv_id = uuid.UUID(body["id"])
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation id")

    # Validate top-level timestamps if present.
    for ts_field in ("created_at", "updated_at"):
        if body.get(ts_field):
            try:
                datetime.fromisoformat(body[ts_field])
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid '{ts_field}' timestamp",
                )

    # Validate messages before touching the DB.
    for idx, msg_data in enumerate(body.get("messages", [])):
        for required in ("id", "role"):
            if required not in msg_data:
                raise HTTPException(
                    status_code=400,
                    detail=f"Message {idx}: missing '{required}'",
                )
        try:
            uuid.UUID(msg_data["id"])
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"Message {idx}: invalid 'id'",
            )
        for att_data in msg_data.get("attachments") or []:
            for required in ("file_id", "filename", "content_type"):
                if required not in att_data:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Message {idx} attachment: "
                            f"missing '{required}'"
                        ),
                    )

    async with ctx.db() as session:
        if await session.get(Conversation, conv_id) is not None:
            raise HTTPException(
                status_code=409,
                detail="Conversation already exists",
            )

        conv = Conversation(
            id=conv_id,
            title=body.get("title"),
            created_at=datetime.fromisoformat(body["created_at"])
            if body.get("created_at")
            else _utcnow(),
            updated_at=datetime.fromisoformat(body["updated_at"])
            if body.get("updated_at")
            else _utcnow(),
        )
        session.add(conv)
        await session.flush()

        allowed_base = (PROJECT_ROOT / "data" / "uploads").resolve()

        msg_count = 0
        for msg_data in body.get("messages", []):
            msg = Message(
                id=uuid.UUID(msg_data["id"]),
                conversation_id=conv_id,
                role=msg_data["role"],
                content=msg_data.get("content", ""),
                tool_calls=msg_data.get("tool_calls"),
                tool_call_id=msg_data.get("tool_call_id"),
                thinking_content=msg_data.get("thinking_content"),
                created_at=datetime.fromisoformat(msg_data["created_at"])
                if msg_data.get("created_at")
                else _utcnow(),
            )
            session.add(msg)
            await session.flush()

            for att_data in msg_data.get("attachments") or []:
                file_path = att_data.get("file_path", "")
                # Sanitise: reject paths that escape the uploads directory.
                if file_path:
                    resolved = (PROJECT_ROOT / file_path).resolve()
                    if not str(resolved).startswith(str(allowed_base)):
                        logger.warning(
                            "Import: rejecting path traversal: {}",
                            file_path,
                        )
                        file_path = ""
                    elif not resolved.exists():
                        logger.warning(
                            "Import: attachment file missing: {}",
                            file_path,
                        )
                att = Attachment(
                    id=uuid.UUID(att_data["file_id"]),
                    message_id=msg.id,
                    filename=att_data["filename"],
                    content_type=att_data["content_type"],
                    file_path=file_path,
                )
                session.add(att)

            msg_count += 1

        await session.commit()

        if ctx.conversation_file_manager:
            await _sync_conversation_to_file(
                session, conv_id, ctx.conversation_file_manager,
            )

        return {
            "id": str(conv.id),
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "message_count": msg_count,
        }


# ---------------------------------------------------------------------------
# REST — file upload for vision models
# ---------------------------------------------------------------------------

# Allowed MIME types for image uploads.
_ALLOWED_IMAGE_TYPES: set[str] = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}


@router.post("/chat/upload")
async def upload_image(
    request: Request,
    conversation_id: str = Form(..., description="Target conversation UUID"),
    file: UploadFile = File(..., description="Image file (jpg/png/gif/webp)"),
) -> dict[str, Any]:
    """Upload an image for use with vision-capable models.

    Saves the file to ``data/uploads/{conversation_id}/`` and creates a
    pending :class:`Attachment` record (``message_id`` is set later when the
    WebSocket message referencing this file is sent).

    Returns:
        A dict with ``file_id``, ``url``, ``filename``, and ``content_type``.

    Raises:
        HTTPException 400: If the file type is not an allowed image format.
        HTTPException 413: If the file exceeds the configured size limit.
    """
    # Validate conversation_id as UUID (anti path-traversal).
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid conversation_id",
        )

    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: {file.content_type}. "
                f"Allowed: {', '.join(sorted(_ALLOWED_IMAGE_TYPES))}"
            ),
        )

    ctx = _ctx(request)
    max_bytes = ctx.config.server.max_upload_size_mb * 1024 * 1024

    # Check Content-Length header as an early rejection.
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large. Maximum allowed: "
                f"{ctx.config.server.max_upload_size_mb} MB"
            ),
        )

    content = await file.read()

    # Enforce actual file size after reading.
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({len(content)} bytes). Maximum: "
                f"{ctx.config.server.max_upload_size_mb} MB"
            ),
        )

    # Verify magic bytes match the claimed MIME type.
    if not _verify_magic_bytes(content, file.content_type or ""):
        raise HTTPException(
            status_code=400,
            detail="File content does not match claimed MIME type",
        )

    file_id = uuid.uuid4()
    ext = (
        Path(file.filename).suffix.lstrip(".") if file.filename else "bin"
    )
    relative_path = (
        f"data/uploads/{conv_uuid}/{file_id}.{ext}"
    )
    abs_path = PROJECT_ROOT / relative_path

    # Ensure the upload directory exists.
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(abs_path.write_bytes, content)

    # Persist an attachment record (message_id linked later via WS handler).
    try:
        async with ctx.db() as session:
            attachment = Attachment(
                id=file_id,
                filename=file.filename or f"{file_id}.{ext}",
                content_type=file.content_type or "application/octet-stream",
                file_path=relative_path,
            )
            session.add(attachment)
            await session.commit()
    except Exception:
        # Cleanup orphan file if DB transaction fails.
        abs_path.unlink(missing_ok=True)
        logger.exception("DB error during upload — cleaned up {}", abs_path)
        raise HTTPException(
            status_code=500, detail="Failed to save attachment record",
        )

    logger.info(
        "Uploaded {} ({}) for conversation {}",
        file.filename,
        file.content_type,
        conv_uuid,
    )

    return {
        "file_id": str(file_id),
        "url": f"/uploads/{conv_uuid}/{file_id}.{ext}",
        "filename": file.filename,
        "content_type": file.content_type,
    }
