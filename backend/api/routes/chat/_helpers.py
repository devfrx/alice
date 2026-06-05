"""AL\\CE — Chat internal helpers (serialization, history, context).

Pure-ish helpers extracted verbatim from the legacy ``chat.py`` module:
conversation serialization, version/history filtering, tool-RAG query
building, DB archival, and system-prompt context blocks (MCP, memory,
whiteboards) plus the per-category token breakdown.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlmodel import select

from backend.core.context import AppContext
from backend.db.models import Attachment, Conversation, Message
from backend.services.context_manager import ContextManager
from backend.services.conversation_file_manager import ConversationFileManager

from ._shared import _attachment_url


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

    now = datetime.now(UTC)
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


def _msg_to_raw_dict(m: Message, db_pos: int) -> dict[str, Any]:
    """Build the raw history dict shape used by the compression pipeline."""
    return {
        "role": m.role,
        "content": m.content,
        "tool_calls": m.tool_calls,
        "tool_call_id": m.tool_call_id,
        "version_group_id": (
            str(m.version_group_id) if m.version_group_id else None
        ),
        "version_index": m.version_index,
        "context_excluded": getattr(m, "context_excluded", False),
        "is_context_summary": getattr(m, "is_context_summary", False),
        "_db_pos": db_pos,
    }
