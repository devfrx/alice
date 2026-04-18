"""AL\\CE — Chat endpoints (WebSocket streaming + REST history)."""

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
from pydantic import BaseModel, Field
import sqlalchemy as sa
from sqlalchemy import func as sa_func
from sqlmodel import select

from backend.core.config import PROJECT_ROOT
from backend.core.context import AppContext
from backend.db.models import Attachment, Conversation, Message
from backend.services.conversation_file_manager import ConversationFileManager
from backend.services.context_manager import (
    CompressionError,
    CompressionResult,
    ContextManager,
    ContextUsage,
)
from backend.services.llm_service import LLMService
from backend.api.routes._tool_loop import run_tool_loop

router = APIRouter(tags=["chat"])

# Base path for uploaded files.
_UPLOADS_BASE: Path = (PROJECT_ROOT / "data" / "uploads").resolve()

# Magic byte signatures for allowed image types.
# Each value is a list of (offset, signature) tuples that must all match.
_MAGIC_BYTES: dict[str, list[tuple[int, bytes]]] = {
    "image/jpeg": [(0, b"\xff\xd8")],
    "image/png": [(0, b"\x89PNG\r\n\x1a\n")],
    "image/gif": [(0, b"GIF87a")],
    # GIF89a is the second accepted signature; handled by the second list below.
    "image/webp": [(0, b"RIFF"), (8, b"WEBP")],
}

# Extra alternative signatures (any-of for the same MIME type).
_MAGIC_ALT: dict[str, list[list[tuple[int, bytes]]]] = {
    "image/gif": [[(0, b"GIF89a")]],
}

# Canonical extension per validated MIME type — used to build upload paths.
# Filenames from the client are NEVER used to derive the extension served
# back, so an attacker cannot trick a static-file server into executing a
# disguised file (e.g. ``foo.png.html``).
_EXT_BY_TYPE: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
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
        # Use POSIX-style separators so the URL works on Windows where
        # ``Path.__str__`` would otherwise yield backslashes (which the
        # static-file mount at ``/uploads`` does not match).
        return f"/uploads/{quote(relative.as_posix(), safe='/')}"
    except ValueError:
        logger.warning("Attachment path outside uploads base: {}", file_path)
        return ""


def _verify_magic_bytes(
    data: bytes, claimed_type: str,
) -> bool:
    """Return ``True`` if the file's magic bytes match *claimed_type*.

    Each MIME type defines a primary list of ``(offset, signature)`` tuples
    that must ALL match.  Optional alternative signature sets in
    :data:`_MAGIC_ALT` are also accepted (any-of).  This catches multi-part
    formats such as ``RIFF????WEBP`` that a single-prefix check would miss.
    """
    primary = _MAGIC_BYTES.get(claimed_type)
    if primary is None:
        return False

    def _matches(checks: list[tuple[int, bytes]]) -> bool:
        return all(
            data[offset:offset + len(sig)] == sig for offset, sig in checks
        )

    if _matches(primary):
        return True
    for alt in _MAGIC_ALT.get(claimed_type, []):
        if _matches(alt):
            return True
    return False


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
        .order_by(Message.created_at, Message.id)
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
        "active_versions": conv.active_versions or {},
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
                "version_group_id": str(m.version_group_id)
                if m.version_group_id
                else None,
                "version_index": m.version_index,
                "is_context_summary": getattr(m, "is_context_summary", False),
                "context_excluded": getattr(m, "context_excluded", False),
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


def _filter_messages_by_active_versions(
    messages: list[dict[str, Any]],
    active_versions: dict[str, int],
) -> list[dict[str, Any]]:
    """Filter a message list to include only active-version messages.

    Messages without a ``version_group_id`` pass through unchanged.
    Versioned messages are included only if their ``version_index``
    matches the active index for their group.

    Args:
        messages: Ordered list of message dicts.
        active_versions: Mapping of version_group_id → active index.

    Returns:
        Filtered list preserving original order.
    """
    result: list[dict[str, Any]] = []
    for m in messages:
        vg = m.get("version_group_id")
        if vg is None:
            result.append(m)
            continue
        active_idx = active_versions.get(vg, 0)
        if m.get("version_index", 0) == active_idx:
            result.append(m)
    return result


def _build_tool_rag_query(
    user_content: str,
    history: list[dict[str, Any]],
) -> str:
    """Build an enriched query for tool RAG from user message + recent context.

    When the user sends a short follow-up like "si" or "ok", the bare
    message has near-zero semantic value for tool retrieval.  This helper
    augments the query with:
    * names of tools called in recent assistant messages,
    * the last substantive user message (>20 chars).

    This way the embedding still matches relevant tools even for terse
    confirmations.

    Args:
        user_content: The current user message.
        history: Filtered conversation history (list of dicts).

    Returns:
        A combined query string for the tool RAG embedding search.
    """
    # Short messages benefit the most from augmentation.
    if len(user_content.strip()) > 60:
        return user_content

    parts: list[str] = [user_content]

    # Walk history backwards (skip last entry = current user msg).
    recent_tools: list[str] = []
    last_user_msg: str = ""
    for m in reversed(history[:-1] if history else []):
        # Collect tool names from recent assistant tool_calls.
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                if name and name not in recent_tools:
                    recent_tools.append(name)

        # Find last substantive user message.
        if (
            m.get("role") == "user"
            and not last_user_msg
            and len((m.get("content") or "").strip()) > 20
        ):
            last_user_msg = (m.get("content") or "").strip()

        # Don't scan too far back.
        if len(recent_tools) >= 6 or (recent_tools and last_user_msg):
            break

    if recent_tools:
        parts.append("tools: " + " ".join(recent_tools))
    if last_user_msg:
        parts.append(last_user_msg)

    return " | ".join(parts)


def _filter_history_for_llm(
    raw_history: list[dict[str, Any]],
    active_versions: dict[str, int],
) -> list[dict[str, Any]]:
    """Filter message history for LLM consumption.

    Applies active-version filtering, then removes context-excluded
    messages (except context summaries which must remain).
    Internal metadata fields are stripped before returning.

    Args:
        raw_history: Message dicts with version and context metadata.
        active_versions: Map of version_group_id to active version_index.

    Returns:
        Clean message dicts ready for LLM message building.
    """
    # Step 1: apply version filtering (reuse existing logic).
    filtered = _filter_messages_by_active_versions(raw_history, active_versions)

    # Step 2: remove context-excluded messages (keep summaries).
    result: list[dict[str, Any]] = []
    for m in filtered:
        if m.get("context_excluded") and not m.get("is_context_summary"):
            continue
        result.append(m)

    # Step 3: truncate oversized tool results.
    # Tool/function messages from web scrapes or searches can be
    # thousands of tokens.  Keep full content only for the last
    # few tool results; truncate older ones to save context.
    _TOOL_TRUNC_CHARS = 1500
    _TOOL_RECENT_KEEP = 4  # keep last N tool messages untruncated
    tool_indices = [
        i for i, m in enumerate(result)
        if m.get("role") == "tool"
    ]
    old_tool_indices = set(tool_indices[:-_TOOL_RECENT_KEEP]) if (
        len(tool_indices) > _TOOL_RECENT_KEEP
    ) else set()
    for idx in old_tool_indices:
        content = result[idx].get("content") or ""
        if len(content) > _TOOL_TRUNC_CHARS:
            result[idx] = {
                **result[idx],
                "content": (
                    content[:_TOOL_TRUNC_CHARS]
                    + "\n... [truncated for context]"
                ),
            }

    # Step 4: neutralize truncated/degraded assistant responses.
    # When the model produces very short or cut-off output, those
    # messages stay in history and cause the model to mimic the
    # pattern.  Replace them with a neutral marker so the LLM does
    # not learn to reproduce truncated answers.
    _TRUNC_MAX_CHARS = 80
    _SENTENCE_ENDERS = frozenset(".!?。…»\"')`")
    cleaned: list[dict[str, Any]] = []
    for m in result:
        if (
            m.get("role") == "assistant"
            and not m.get("tool_calls")
            and not m.get("is_context_summary")
        ):
            content = (m.get("content") or "").strip()
            if not content:
                continue  # drop empty assistant messages
            if (
                len(content) < _TRUNC_MAX_CHARS
                and content[-1] not in _SENTENCE_ENDERS
            ):
                cleaned.append({**m, "content": "[Incomplete response]"})
                continue
        cleaned.append(m)
    result = cleaned

    # Step 5: strip internal metadata fields.
    clean: list[dict[str, Any]] = []
    for m in result:
        entry = {
            k: v for k, v in m.items()
            if k not in ("_db_pos", "context_excluded", "is_context_summary",
                         "version_group_id", "version_index")
        }
        clean.append(entry)
    return clean


async def _archive_messages_in_db(
    session: Any,
    all_messages: list[Any],
    raw_history: list[dict[str, Any]],
    split_index: int,
    active_versions: dict[str, int] | None = None,
) -> None:
    """Mark the first *split_index* non-system messages as context-excluded.

    Uses ``_db_pos`` from raw_history to map back to ORM objects.

    Args:
        session: Active async DB session.
        all_messages: ORM Message objects fetched from DB.
        raw_history: Message dicts with ``_db_pos`` metadata.
        split_index: Number of conversation messages to archive.
        active_versions: Map of version_group_id to active index.
            Non-active version messages are skipped so they don't
            count against *split_index*.
    """
    archived = 0
    for entry in raw_history:
        if archived >= split_index:
            break
        if entry.get("role") == "system":
            continue
        if entry.get("context_excluded"):
            continue
        # Skip non-active version messages so they don't consume
        # split_index slots meant for active-branch messages.
        if active_versions is not None:
            vg = entry.get("version_group_id")
            if vg is not None:
                active_idx = active_versions.get(vg, 0)
                if entry.get("version_index", 0) != active_idx:
                    continue
        db_pos = entry.get("_db_pos")
        if db_pos is not None and db_pos < len(all_messages):
            msg_obj = all_messages[db_pos]
            if hasattr(msg_obj, "context_excluded"):
                msg_obj.context_excluded = True
                session.add(msg_obj)
            archived += 1
    if archived > 0:
        await session.flush()


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
                if arg and ((arg[0].isalpha() and len(arg) > 1 and arg[1] == ":") or arg.startswith("/"))
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


async def _build_whiteboard_context(
    ctx: AppContext, conversation_id: str
) -> str | None:
    """Build a brief context block listing whiteboards for the current conversation.

    Injected into the system prompt so the LLM knows which boards already
    exist and can reference or update them instead of creating duplicates.

    Args:
        ctx: Application context with plugin_manager.
        conversation_id: The current conversation's UUID as a string.

    Returns:
        A markdown context block, or None if no whiteboards or plugin unavailable.
    """
    if not ctx.plugin_manager:
        return None
    wb_plugin = ctx.plugin_manager.get_plugin("whiteboard")
    if not wb_plugin:
        return None
    store = getattr(wb_plugin, "store", None)
    if not store:
        return None
    try:
        items = await store.list(conversation_id=conversation_id)
    except Exception as exc:
        logger.warning("Whiteboard context fetch failed for conv={}: {}", conversation_id, exc)
        return None
    if not items:
        return None

    now = datetime.now(timezone.utc)
    lines = ["[LAVAGNE ASSOCIATE A QUESTA CONVERSAZIONE]"]
    for item in items:
        if item.updated_at:
            delta = now - item.updated_at
            hours = int(delta.total_seconds() // 3600)
            if hours < 1:
                age = "aggiornata poco fa"
            elif hours < 24:
                age = f"aggiornata {hours}h fa"
            else:
                days = hours // 24
                age = f"aggiornata {days}g fa"
        else:
            age = ""
        shape_info = f"{item.shape_count} shape" if item.shape_count else "vuota"
        extra = f", {age}" if age else ""
        lines.append(
            f'- "{item.title}" (id: {item.board_id}) — {shape_info}{extra}'
        )
    lines.append("[/LAVAGNE ASSOCIATE]")
    return "\n".join(lines)


def _compute_context_breakdown(
    messages: list[dict[str, Any]],
    tool_tokens: int,
    ctx_manager: ContextManager,
) -> dict[str, int]:
    """Estimate per-category token breakdown from an assembled message list.

    Categories:
    - system: system-prompt messages (``role == "system"``)
    - tools: tool-definition JSON (pre-computed as *tool_tokens*)
    - messages: user/assistant conversation turns
    - files: vision image parts (estimated at ~256 tokens each)
    - tool_results: tool-result messages (``role == "tool"``)
    - other: anything not matched above

    Args:
        messages: The fully-assembled list of message dicts sent to the LLM.
        tool_tokens: Pre-computed token count for tool-definition JSON.
        ctx_manager: Used for ``estimate_tokens()``.

    Returns:
        Dict with keys ``system``, ``tools``, ``messages``, ``files``,
        ``tool_results``, ``other``.
    """
    system = 0
    messages_tok = 0
    files = 0
    tool_results = 0
    other = 0
    _OVERHEAD = 4  # role/metadata overhead per message

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role == "system":
            text = content if isinstance(content, str) else ""
            system += _OVERHEAD + ctx_manager.estimate_tokens(text)

        elif role == "tool":
            text = content if isinstance(content, str) else ""
            tool_results += _OVERHEAD + ctx_manager.estimate_tokens(text)

        elif role in ("user", "assistant"):
            tok = _OVERHEAD
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        tok += ctx_manager.estimate_tokens(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        # Vision tokens cannot be estimated with char÷4;
                        # use a conservative flat estimate per image tile.
                        files += 256
            elif isinstance(content, str):
                tok += ctx_manager.estimate_tokens(content)
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                try:
                    tc_str = (
                        json.dumps(tool_calls)
                        if not isinstance(tool_calls, str)
                        else tool_calls
                    )
                    tok += ctx_manager.estimate_tokens(tc_str)
                except (TypeError, ValueError):
                    pass
            messages_tok += tok

        else:
            text = content if isinstance(content, str) else ""
            other += _OVERHEAD + ctx_manager.estimate_tokens(text)

    return {
        "system": system,
        "tools": tool_tokens,
        "messages": messages_tok,
        "files": files,
        "tool_results": tool_results,
        "other": other,
    }


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


class BranchConversationResponse(BaseModel):
    """Response from the branch-conversation endpoint.

    Args:
        id: UUID of the newly created conversation.
        title: Title of the new conversation.
        created_at: ISO 8601 timestamp of creation.
        updated_at: ISO 8601 timestamp of last update.
        message_count: Number of messages copied into the new conversation.
    """

    id: str
    title: str | None
    created_at: str
    updated_at: str
    message_count: int


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
            await websocket.accept()
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
                await asyncio.sleep(0)  # yield to event loop
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
            edit_message_id: str | None = data.get("edit_message_id")

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
                if edit_message_id:
                    # --- handle edit-message flow -------------------------
                    try:
                        original_msg_id = uuid.UUID(edit_message_id)
                    except ValueError:
                        await websocket.send_json(
                            {"type": "error", "content": "Invalid edit_message_id"},
                        )
                        continue
                    original_msg = await session.get(Message, original_msg_id)
                    if (
                        original_msg is None
                        or original_msg.conversation_id != conv_id
                        or original_msg.role != "user"
                    ):
                        await websocket.send_json(
                            {"type": "error", "content": "Invalid edit target"},
                        )
                        continue

                    # Assign a version_group_id to the original if it
                    # doesn't have one yet, and tag all subsequent messages
                    # in the same conversation with the same group+index.
                    if original_msg.version_group_id is None:
                        vg_id = uuid.uuid4()
                        original_msg.version_group_id = vg_id
                        original_msg.version_index = 0
                        # Tag all messages from the original onward.
                        after_stmt = (
                            select(Message)
                            .where(
                                Message.conversation_id == conv_id,
                                sa.or_(
                                    Message.created_at > original_msg.created_at,
                                    (Message.created_at == original_msg.created_at)
                                    & (Message.id > original_msg.id),
                                ),
                                Message.id != original_msg.id,
                                Message.version_group_id.is_(None),  # type: ignore[union-attr]
                            )
                        )
                        after_results = await session.exec(after_stmt)
                        for m in after_results.all():
                            m.version_group_id = vg_id
                            m.version_index = 0
                        await session.flush()
                    else:
                        vg_id = original_msg.version_group_id

                    # Determine the next version index.
                    max_idx_result = await session.scalar(
                        sa.select(sa.func.max(Message.version_index)).where(
                            Message.version_group_id == vg_id,
                        )
                    )
                    new_version_idx = (max_idx_result or 0) + 1

                    user_msg = Message(
                        conversation_id=conv_id,
                        role="user",
                        content=user_content,
                        version_group_id=vg_id,
                        version_index=new_version_idx,
                    )
                    session.add(user_msg)
                    await session.flush()

                    # Update active_versions on the conversation.
                    av = dict(conv.active_versions or {})
                    av[str(vg_id)] = new_version_idx
                    conv.active_versions = av
                    await session.flush()
                else:
                    # Inherit version context from the active branch
                    # so new messages belong to the currently viewed branch.
                    inherit_vg: uuid.UUID | None = None
                    inherit_vi: int = 0
                    av = dict(conv.active_versions or {})
                    if av:
                        conds = [
                            sa.and_(
                                Message.version_group_id == uuid.UUID(vg),
                                Message.version_index == idx,
                            )
                            for vg, idx in av.items()
                        ]
                        latest = (
                            await session.exec(
                                select(Message)
                                .where(
                                    Message.conversation_id == conv_id,
                                    sa.or_(*conds),
                                )
                                .order_by(Message.created_at.desc())
                                .limit(1)
                            )
                        ).first()
                        if latest:
                            inherit_vg = latest.version_group_id
                            inherit_vi = latest.version_index

                    user_msg = Message(
                        conversation_id=conv_id,
                        role="user",
                        content=user_content,
                        version_group_id=inherit_vg,
                        version_index=inherit_vi,
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
                    .order_by(Message.created_at, Message.id)
                )
                results = await session.exec(stmt)
                all_messages = results.all()

                # Build active_versions map for filtering.
                av_map: dict[str, int] = dict(conv.active_versions or {})
                raw_history: list[dict[str, Any]] = [
                    {
                        "role": m.role,
                        "content": m.content,
                        "tool_calls": m.tool_calls,
                        "tool_call_id": m.tool_call_id,
                        "version_group_id": str(m.version_group_id)
                        if m.version_group_id
                        else None,
                        "version_index": m.version_index,
                        "context_excluded": getattr(m, "context_excluded", False),
                        "is_context_summary": getattr(m, "is_context_summary", False),
                        "_db_pos": i,
                    }
                    for i, m in enumerate(all_messages)
                ]
                history = _filter_history_for_llm(
                    raw_history, av_map,
                )

                # --- fetch available tools for LLM ------------------------
                tools: list[dict[str, Any]] | None = None
                if ctx.tool_registry and ctx.config.llm.tools_enabled:
                    if (
                        ctx.config.llm.tool_rag_enabled
                        and ctx.qdrant_service is not None
                    ):
                        tool_query = _build_tool_rag_query(
                            user_content, history,
                        )
                        tools = await ctx.tool_registry.get_relevant_tools(
                            tool_query,
                            ctx.config.llm.tool_rag_top_k,
                        )
                    else:
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

                # --- inject whiteboards for current conversation ----------
                wb_ctx = await _build_whiteboard_context(ctx, str(conv_id))
                if wb_ctx:
                    memory_context = (
                        f"{memory_context}\n\n{wb_ctx}"
                        if memory_context
                        else wb_ctx
                    )

                # --- call LLM (streaming) ---------------------------------
                # Build system prompt once for the entire request — reused
                # in build_messages, build_continuation_messages, and the
                # native API path.
                cached_sys_prompt = llm.get_system_prompt(
                    memory_context=memory_context,
                )

                messages = llm.build_messages(
                    user_content,
                    history=history[:-1],  # history already has user msg
                    attachments=attachment_info or None,
                    system_prompt=cached_sys_prompt,
                )

                # -- Context management ---------------------------------------
                comp: CompressionResult | None = None
                context_window = 0
                last_input_tokens = 0
                last_output_tokens = 0

                if ctx.context_manager is not None:
                    context_window = await llm.get_active_context_window(
                        ctx.lmstudio_manager,
                    )

                if context_window > 0 and ctx.context_manager is not None:
                    # Compute tool tokens for compression regardless
                    # of estimation path — compress() needs them.
                    _tool_tokens = 0
                    if tools:
                        _tool_tokens = (
                            ctx.context_manager.estimate_tokens(
                                json.dumps(tools, ensure_ascii=False),
                            )
                        )

                    # Prefer anchor+delta over full estimation.
                    snap = getattr(conv, "context_snapshot", None)
                    if (
                        snap
                        and isinstance(snap, dict)
                        and snap.get("prompt_tokens", 0) > 0
                    ):
                        # Real tokens from last exchange — already
                        # include system prompt + tools + all messages.
                        anchor = (
                            snap["prompt_tokens"]
                            + snap.get("completion_tokens", 0)
                        )
                        # Estimate only the new user message.
                        delta = ctx.context_manager.estimate_tokens(
                            user_content or "",
                        )
                        used = anchor + delta
                        available = max(0, context_window - used)
                        pct = (
                            round(used / context_window, 4)
                            if context_window > 0 else 0.0
                        )
                        usage_est = ContextUsage(
                            used_tokens=used,
                            available_tokens=available,
                            context_window=context_window,
                            percentage=pct,
                            was_compressed=False,
                            messages_summarized=0,
                            is_estimated=False,
                        )
                    else:
                        # Fallback: full char/4 estimation.
                        usage_est = (
                            ctx.context_manager.get_usage_estimated(
                                messages, context_window,
                            )
                        )
                        # Add tool tokens (not in the messages array).
                        if _tool_tokens > 0:
                            usage_est.used_tokens += _tool_tokens
                            usage_est.available_tokens = max(
                                0,
                                context_window - usage_est.used_tokens,
                            )
                            usage_est.percentage = (
                                round(
                                    usage_est.used_tokens
                                    / context_window,
                                    4,
                                )
                                if context_window > 0 else 0.0
                            )

                    # Pre-generation compression check.
                    if (
                        ctx.config.llm.context_compression_enabled
                        and ctx.context_manager.should_compress(usage_est)
                    ):
                        await websocket.send_json(
                            {"type": "context_compression_start"},
                        )
                        try:
                            comp = await ctx.context_manager.compress(
                                messages,
                                llm,
                                context_window,
                                ctx.config.llm.context_compression_reserve,
                                tool_tokens=_tool_tokens
                                if tools else 0,
                            )
                            messages = comp.messages

                            # Archive messages in DB.
                            await _archive_messages_in_db(
                                session, all_messages, raw_history,
                                comp.split_index,
                                active_versions=av_map,
                            )
                            # Save summary message.
                            summary_content = (
                                f"[Context summary of "
                                f"{comp.split_index} earlier "
                                f"messages]:\n{comp.summary_text}"
                            )
                            summary_msg = Message(
                                conversation_id=conv_id,
                                role="assistant",
                                content=summary_content,
                                is_context_summary=True,
                            )
                            session.add(summary_msg)
                            await session.flush()

                            await websocket.send_json({
                                "type": "context_compression_done",
                                "messages_summarized": (
                                    comp.usage.messages_summarized
                                ),
                                "summary_message_id": str(summary_msg.id),
                            })
                            # Re-estimate after compression.
                            usage_est = comp.usage
                        except Exception as exc:
                            logger.warning(
                                "Context compression failed: {}", exc,
                            )
                            await websocket.send_json(
                                {"type": "context_compression_failed"},
                            )
                            comp = None

                    # Send initial context_info.
                    await websocket.send_json({
                        "type": "context_info",
                        "used": usage_est.used_tokens,
                        "available": usage_est.available_tokens,
                        "context_window": context_window,
                        "percentage": usage_est.percentage,
                        "was_compressed": comp is not None,
                        "messages_summarized": (
                            comp.usage.messages_summarized if comp else 0
                        ),
                        "is_estimated": usage_est.is_estimated,
                        "breakdown": _compute_context_breakdown(
                            messages, _tool_tokens, ctx.context_manager,
                        ),
                    })

                full_content = ""
                thinking_content = ""
                tool_calls_collected: list[dict[str, Any]] = []
                finish_reason = "stop"
                cancel_event = asyncio.Event()

                async def _stream_and_collect() -> None:
                    """Consume LLM stream, accumulate content and relay to WS."""
                    nonlocal full_content, thinking_content, finish_reason
                    nonlocal last_input_tokens, last_output_tokens
                    # When compression happened, force OAI-compat
                    # path — the native API uses response_id chaining
                    # which bypasses our compressed messages list.
                    effective_user_content = (
                        None if comp is not None else user_content
                    )

                    # When max_tokens is unset (-1), calculate the
                    # available output budget from context info so
                    # LM Studio doesn't silently cap at a small default.
                    resolved_max: int | None = None
                    if (
                        ctx.config.llm.max_tokens <= 0
                        and context_window > 0
                        and ctx.context_manager is not None
                    ):
                        resolved_max = max(
                            1024,
                            usage_est.available_tokens
                            - ctx.config.llm.context_compression_reserve,
                        )

                    async for event in llm.chat(
                        messages,
                        tools=tools,
                        cancel_event=cancel_event,
                        user_content=effective_user_content,
                        conversation_id=str(conv_id),
                        attachments=attachment_info or None,
                        system_prompt=cached_sys_prompt,
                        max_output_tokens=resolved_max,
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
                        elif etype == "usage":
                            last_input_tokens = event.get(
                                "input_tokens", 0,
                            )
                            last_output_tokens = event.get(
                                "output_tokens", 0,
                            )
                        elif etype == "error":
                            logger.error(
                                "LLM error during initial stream: {}",
                                event.get("content", "unknown"),
                            )
                            await websocket.send_json(event)
                            finish_reason = "error"
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
                                websocket.receive_text(), timeout=2.0,
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
                except Exception as exc:
                    logger.exception("LLM streaming error")
                    finish_reason = "error"
                    # Surface the server's error message to the user
                    err_detail = "LLM error"
                    if hasattr(exc, "response"):
                        err_detail = (
                            f"LLM returned {exc.response.status_code}"
                        )
                    await websocket.send_json(
                        {"type": "error", "content": err_detail},
                    )
                    await websocket.send_json({
                        "type": "done",
                        "conversation_id": str(conv_id),
                        "message_id": "",
                        "user_message_id": str(user_msg.id),
                        "finish_reason": "error",
                        "version_group_id": str(user_msg.version_group_id)
                        if user_msg.version_group_id
                        else None,
                        "version_index": user_msg.version_index,
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
                            version_group_id=user_msg.version_group_id,
                            version_index=user_msg.version_index,
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
                        "user_message_id": str(user_msg.id),
                        "finish_reason": "cancelled",
                        "version_group_id": str(user_msg.version_group_id)
                        if user_msg.version_group_id
                        else None,
                        "version_index": user_msg.version_index,
                    })
                    continue

                # --- tool calling loop (if LLM requested tools) -----------
                if tool_calls_collected and finish_reason not in ("cancelled", "error"):
                    try:
                        (
                            full_content,
                            thinking_content,
                            loop_in_tokens,
                            loop_out_tokens,
                            loop_finish,
                        ) = await run_tool_loop(
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
                            tools=tools,
                            # When pre-gen compression ran, the in-memory
                            # history passed to the tool loop must reflect
                            # the compressed state, not the pre-compression
                            # history — otherwise the loop would re-trigger
                            # compression on every iteration.
                            initial_history=(
                                [
                                    m for m in comp.messages
                                    if m.get("role") != "system"
                                ]
                                if comp is not None
                                else history
                            ),
                            system_prompt=cached_sys_prompt,
                            version_group_id=user_msg.version_group_id,
                            version_index=user_msg.version_index,
                            context_window=context_window,
                        )
                        # Use token data from the final tool-loop
                        # re-query when available (the initial
                        # stream values are stale after tool calls).
                        if loop_in_tokens > 0:
                            last_input_tokens = loop_in_tokens
                            last_output_tokens = loop_out_tokens
                        finish_reason = loop_finish
                    except WebSocketDisconnect:
                        # Save any pending assistant content before propagating.
                        logger.debug("WS disconnected during tool loop")
                        if full_content:
                            recovery_msg = Message(
                                conversation_id=conv_id,
                                role="assistant",
                                content=full_content,
                                thinking_content=thinking_content or None,
                                version_group_id=user_msg.version_group_id,
                                version_index=user_msg.version_index,
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
                            "user_message_id": str(user_msg.id),
                            "finish_reason": "error",
                            "version_group_id": str(user_msg.version_group_id)
                            if user_msg.version_group_id
                            else None,
                            "version_index": user_msg.version_index,
                        })
                        await session.rollback()
                        continue

                # --- handle cancellation during tool loop -----------------
                if cancel_event.is_set():
                    asst_msg_id = ""
                    if full_content or thinking_content:
                        cancel_asst_msg = Message(
                            conversation_id=conv_id,
                            role="assistant",
                            content=full_content,
                            thinking_content=thinking_content or None,
                            version_group_id=user_msg.version_group_id,
                            version_index=user_msg.version_index,
                        )
                        session.add(cancel_asst_msg)
                        asst_msg_id = str(cancel_asst_msg.id)
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
                        "message_id": asst_msg_id,
                        "user_message_id": str(user_msg.id),
                        "finish_reason": "cancelled",
                        "version_group_id": str(user_msg.version_group_id)
                        if user_msg.version_group_id
                        else None,
                        "version_index": user_msg.version_index,
                    })
                    continue

                # --- save assistant message --------------------------------
                try:
                    asst_msg_id = ""
                    asst_msg = None

                    # Only save a final assistant message if there is actual
                    # content.  When tool_calls were executed, intermediate
                    # messages are already persisted by the tool loop.
                    if full_content.strip() or not tool_calls_collected:
                        asst_msg = Message(
                            conversation_id=conv_id,
                            role="assistant",
                            content=full_content,
                            thinking_content=thinking_content or None,
                            version_group_id=user_msg.version_group_id,
                            version_index=user_msg.version_index,
                        )
                        session.add(asst_msg)
                        asst_msg_id = str(asst_msg.id)

                    # Update context_info with real tokens (if available).
                    if (
                        last_input_tokens > 0
                        and ctx.context_manager
                        and context_window > 0
                    ):
                        real_usage = ctx.context_manager.get_usage_real(
                            last_input_tokens, context_window,
                        )
                        await websocket.send_json({
                            "type": "context_info",
                            "used": real_usage.used_tokens,
                            "available": real_usage.available_tokens,
                            "context_window": context_window,
                            "percentage": real_usage.percentage,
                            "was_compressed": comp is not None,
                            "messages_summarized": (
                                comp.usage.messages_summarized
                                if comp else 0
                            ),
                            "is_estimated": False,
                            "breakdown": _compute_context_breakdown(
                                messages, _tool_tokens, ctx.context_manager,
                            ),
                        })
                        # Persist token count on assistant message.
                        if asst_msg is not None:
                            asst_msg.token_count = last_input_tokens
                            session.add(asst_msg)
                            await session.flush()

                    # --- update conversation timestamp -------------------------
                    conv.updated_at = _utcnow()
                    if conv.title is None and user_content:
                        conv.title = user_content[:100]

                    # Persist real token snapshot for accurate GET
                    # estimates.  Only overwrite when we have real data.
                    if last_input_tokens > 0 and context_window > 0:
                        conv.context_snapshot = {
                            "prompt_tokens": last_input_tokens,
                            "completion_tokens": last_output_tokens,
                            "context_window": context_window,
                        }

                    await session.commit()

                    # Sync conversation to JSON file.
                    if ctx.conversation_file_manager:
                        await _sync_conversation_to_file(
                            session, conv_id,
                            ctx.conversation_file_manager,
                        )

                    # --- Post-stream compression on truncated output ------
                    # When the LLM hit max_tokens / context limit, the
                    # response was truncated.  Compress now so the NEXT
                    # turn has enough room.
                    # Determine whether post-stream compression
                    # is needed.  Two triggers:
                    # 1) finish_reason=="length" (OAI-compat path)
                    # 2) Real token usage above threshold (covers
                    #    native LM Studio path which always returns
                    #    finish_reason="stop" even when truncated).
                    post_compress = finish_reason == "length"
                    if (
                        not post_compress
                        and last_input_tokens > 0
                        and last_output_tokens > 0
                        and context_window > 0
                    ):
                        total_tokens = (
                            last_input_tokens + last_output_tokens
                        )
                        real_pct = total_tokens / context_window
                        if real_pct >= (
                            ctx.config.llm
                            .context_compression_threshold
                        ):
                            post_compress = True
                            logger.info(
                                "Token usage {:.1f}% >= threshold "
                                "{}%, triggering post-stream "
                                "compression",
                                real_pct * 100,
                                ctx.config.llm
                                .context_compression_threshold
                                * 100,
                            )
                    if (
                        post_compress
                        and ctx.config.llm.context_compression_enabled
                        and ctx.context_manager is not None
                        and context_window > 0
                    ):
                        try:
                            logger.info(
                                "Triggering post-stream compression"
                                " (finish_reason={}, tokens={}/{})",
                                finish_reason,
                                last_input_tokens + last_output_tokens,
                                context_window,
                            )
                            await websocket.send_json(
                                {"type": "context_compression_start"},
                            )
                            # Re-query messages including the
                            # just-saved assistant response.
                            post_stmt = (
                                select(Message)
                                .where(
                                    Message.conversation_id == conv_id,
                                )
                                .order_by(
                                    Message.created_at, Message.id,
                                )
                            )
                            post_results = await session.exec(
                                post_stmt,
                            )
                            post_all_msgs = post_results.all()
                            post_raw = [
                                {
                                    "role": m.role,
                                    "content": m.content,
                                    "tool_calls": m.tool_calls,
                                    "tool_call_id": m.tool_call_id,
                                    "version_group_id": (
                                        str(m.version_group_id)
                                        if m.version_group_id
                                        else None
                                    ),
                                    "version_index": m.version_index,
                                    "context_excluded": getattr(
                                        m, "context_excluded", False,
                                    ),
                                    "is_context_summary": getattr(
                                        m, "is_context_summary", False,
                                    ),
                                    "_db_pos": i,
                                }
                                for i, m in enumerate(post_all_msgs)
                            ]
                            post_hist = _filter_history_for_llm(
                                post_raw, av_map,
                            )
                            post_msgs = (
                                llm.build_continuation_messages(
                                    post_hist,
                                    system_prompt=cached_sys_prompt,
                                )
                            )
                            post_comp = (
                                await ctx.context_manager.compress(
                                    post_msgs,
                                    llm,
                                    context_window,
                                    ctx.config.llm
                                    .context_compression_reserve,
                                    tool_tokens=_tool_tokens
                                    if tools else 0,
                                )
                            )
                            await _archive_messages_in_db(
                                session,
                                post_all_msgs,
                                post_raw,
                                post_comp.split_index,
                                active_versions=av_map,
                            )
                            post_summary = (
                                f"[Context summary of "
                                f"{post_comp.split_index} earlier "
                                f"messages]:\n"
                                f"{post_comp.summary_text}"
                            )
                            post_sum_msg = Message(
                                conversation_id=conv_id,
                                role="assistant",
                                content=post_summary,
                                is_context_summary=True,
                            )
                            session.add(post_sum_msg)
                            await session.commit()

                            if ctx.conversation_file_manager:
                                await _sync_conversation_to_file(
                                    session, conv_id,
                                    ctx.conversation_file_manager,
                                )

                            await websocket.send_json({
                                "type": "context_compression_done",
                                "messages_summarized": (
                                    post_comp.usage
                                    .messages_summarized
                                ),
                                "summary_message_id": str(
                                    post_sum_msg.id,
                                ),
                            })
                            # Send updated context_info after
                            # compression so ContextBar refreshes.
                            await websocket.send_json({
                                "type": "context_info",
                                "used": (
                                    post_comp.usage.used_tokens
                                ),
                                "available": (
                                    post_comp.usage.available_tokens
                                ),
                                "context_window": context_window,
                                "percentage": (
                                    post_comp.usage.percentage
                                ),
                                "was_compressed": True,
                                "messages_summarized": (
                                    post_comp.usage
                                    .messages_summarized
                                ),
                                "is_estimated": True,
                                "breakdown": _compute_context_breakdown(
                                    post_comp.messages,
                                    _tool_tokens,
                                    ctx.context_manager,
                                ),
                            })
                            logger.info(
                                "Post-stream compression done: "
                                "{} messages archived",
                                post_comp.split_index,
                            )
                            # Update snapshot with compressed data.
                            conv.context_snapshot = {
                                "prompt_tokens": (
                                    post_comp.usage.used_tokens
                                ),
                                "completion_tokens": 0,
                                "context_window": context_window,
                            }
                            await session.commit()
                        except Exception as exc:
                            logger.warning(
                                "Post-stream compression failed: "
                                "{}",
                                exc,
                            )
                            await websocket.send_json(
                                {
                                    "type":
                                    "context_compression_failed",
                                },
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
                        "user_message_id": str(user_msg.id),
                        "finish_reason": "error",
                        "version_group_id": str(user_msg.version_group_id)
                        if user_msg.version_group_id
                        else None,
                        "version_index": user_msg.version_index,
                    })
                    continue

                await websocket.send_json(
                    {
                        "type": "done",
                        "conversation_id": str(conv_id),
                        "message_id": asst_msg_id,
                        "user_message_id": str(user_msg.id),
                        "finish_reason": finish_reason,
                        "version_group_id": str(user_msg.version_group_id)
                        if user_msg.version_group_id
                        else None,
                        "version_index": user_msg.version_index,
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
                        "url": _attachment_url(att.file_path),
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
                try:
                    cw = await ctx.llm_service.get_active_context_window(
                        ctx.lmstudio_manager,
                    )
                except Exception:
                    pass
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
                            if avail_tools:
                                if ctx.config.llm.max_tools > 0:
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

        return {
            "id": str(conv.id),
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "active_versions": conv.active_versions or {},
            "context_info": context_info,
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
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

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


@router.post("/chat/conversations/{conversation_id}/switch-version")
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
        raise HTTPException(status_code=400, detail="Invalid JSON body")

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
        )

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

        if ctx.conversation_file_manager:
            await _sync_conversation_to_file(
                session, conversation_id, ctx.conversation_file_manager,
            )

        return {
            "id": str(conv.id),
            "active_versions": conv.active_versions,
            "updated_at": conv.updated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# REST — branch conversation
# ---------------------------------------------------------------------------


@router.post("/chat/conversations/{conversation_id}/branch")
async def branch_conversation(
    conversation_id: str,
    body: BranchConversationRequest,
    request: Request,
) -> BranchConversationResponse:
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
        raise HTTPException(status_code=400, detail="Invalid conversation_id")

    try:
        from_msg_id = uuid.UUID(body.from_message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid from_message_id")

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

        if ctx.conversation_file_manager:
            await _sync_conversation_to_file(
                session, new_conv.id, ctx.conversation_file_manager
            )

        return BranchConversationResponse(
            id=str(new_conv.id),
            title=new_conv.title,
            created_at=new_conv.created_at.isoformat(),
            updated_at=new_conv.updated_at.isoformat(),
            message_count=len(sliced_dicts),
        )


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
                )
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

    # Verify the conversation actually exists \u2014 otherwise the frontend
    # would open a non-existent path in the system explorer.
    async with ctx.db() as session:
        if await session.get(Conversation, conversation_id) is None:
            raise HTTPException(
                status_code=404, detail="Conversation not found",
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
    _ALLOWED_ROLES = ("user", "assistant", "system", "tool")
    for idx, msg_data in enumerate(body.get("messages", [])):
        for required in ("id", "role"):
            if required not in msg_data:
                raise HTTPException(
                    status_code=400,
                    detail=f"Message {idx}: missing '{required}'",
                )
        if msg_data["role"] not in _ALLOWED_ROLES:
            raise HTTPException(
                status_code=400,
                detail=f"Message {idx}: invalid role '{msg_data['role']}'",
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
            active_versions=body.get("active_versions"),
        )
        session.add(conv)
        await session.flush()

        allowed_base = (PROJECT_ROOT / "data" / "uploads").resolve()

        msg_count = 0
        for msg_data in body.get("messages", []):
            vg_raw = msg_data.get("version_group_id")
            msg = Message(
                id=uuid.UUID(msg_data["id"]),
                conversation_id=conv_id,
                role=msg_data["role"],
                content=msg_data.get("content", ""),
                tool_calls=msg_data.get("tool_calls"),
                tool_call_id=msg_data.get("tool_call_id"),
                thinking_content=msg_data.get("thinking_content"),
                version_group_id=uuid.UUID(vg_raw) if vg_raw else None,
                version_index=msg_data.get("version_index", 0),
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
                    if not resolved.is_relative_to(allowed_base):
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
    try:
        content_length_int = int(content_length) if content_length else 0
    except (ValueError, TypeError):
        content_length_int = 0
    if content_length_int > max_bytes:
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
    # Derive extension from the validated MIME type \u2014 NEVER from the
    # client-supplied filename \u2014 to prevent extension-confusion attacks
    # (e.g. ``foo.png.html`` being served with an HTML content-type by a
    # naive static-file server).  ``content_type`` is already whitelisted.
    ext = _EXT_BY_TYPE[file.content_type]  # type: ignore[index]
    relative_path = (
        f"data/uploads/{conv_uuid}/{file_id}.{ext}"
    )
    abs_path = PROJECT_ROOT / relative_path

    # Ensure the upload directory exists (off-loop to keep async safe).
    await asyncio.to_thread(
        abs_path.parent.mkdir, parents=True, exist_ok=True,
    )
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
        # Cleanup orphan file if DB transaction fails (off-loop).
        await asyncio.to_thread(abs_path.unlink, True)
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
