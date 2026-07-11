"""AL\\CE — Conversation export service (Fase 2, spec §5.2).

SQLite is the single source of truth for conversations. This module is the
ONE implementation of conversation serialization and explicit export/backup:
the REST routes (``api/routes/chat/io.py``) and the ``conversation_backup``
plugin tool both delegate here. There is no automatic mirror.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from loguru import logger
from pydantic import BaseModel, Field
from sqlmodel import select

from backend.core.config import PROJECT_ROOT
from backend.db.models import Attachment, Conversation, Message

# Base path for uploaded files (used to build safe /uploads/… URLs).
_UPLOADS_BASE: Path = (PROJECT_ROOT / "data" / "uploads").resolve()


# ---------------------------------------------------------------------------
# Contract models (response_model of the export endpoint AND file schema)
# ---------------------------------------------------------------------------


class ExportedAttachment(BaseModel):
    """One attachment inside an exported message."""

    file_id: str
    url: str
    filename: str
    content_type: str
    file_path: str


class ExportedMessage(BaseModel):
    """One message inside a conversation export."""

    id: str
    role: str
    content: str
    thinking_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    created_at: str
    attachments: list[ExportedAttachment] | None = None
    version_group_id: str | None = None
    version_index: int = 0
    is_context_summary: bool = False
    context_excluded: bool = False


class ConversationExport(BaseModel):
    """Full conversation export (REST response body and backup file schema)."""

    id: str
    title: str | None
    created_at: str
    updated_at: str
    active_versions: dict[str, int] = Field(default_factory=dict)
    messages: list[ExportedMessage]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def attachment_url(file_path: str) -> str:
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


async def build_conversation_export(
    session: Any, conv_id: uuid.UUID,
) -> dict[str, Any]:
    """Build the full conversation dict (messages + attachments) from DB.

    The returned attachment dicts include **both** ``url`` (for API / frontend
    consumption) and ``file_path`` (for file-level backup / recovery).

    Args:
        session: An active async DB session.
        conv_id: The conversation UUID.

    Returns:
        A dict matching :class:`ConversationExport`, or ``{}`` if the
        conversation does not exist.
    """
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        return {}

    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at, Message.id)  # type: ignore[arg-type]
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
            url = attachment_url(att.file_path)
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


# ---------------------------------------------------------------------------
# Explicit export / backup
# ---------------------------------------------------------------------------


def default_backup_dir() -> Path:
    """Return a fresh timestamped destination under ``data/backups/``.

    Single definition of the default-backup-destination policy shared by
    the REST endpoint and the ``conversation_backup`` plugin tool.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return PROJECT_ROOT / "data" / "backups" / f"conversations-{stamp}"


def _atomic_write(target: Path, payload: str) -> None:
    """Write *payload* to *target* atomically (unique temp file + rename)."""
    tmp = target.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
    try:
        tmp.write_text(payload, encoding="utf-8", newline="\n")
        tmp.replace(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


async def export_conversations_to_dir(
    session_factory: Any,
    dest_dir: Path,
    conversation_ids: Sequence[uuid.UUID] | None = None,
) -> int:
    """Export conversations as ``{id}.json`` files into *dest_dir*.

    Args:
        session_factory: An ``async_sessionmaker`` for creating DB sessions.
        dest_dir: Destination directory (created if missing).
        conversation_ids: Optional subset to export; ``None`` exports all.

    Returns:
        Number of conversations exported (unknown ids are skipped).

    Raises:
        OSError: On write failure the export aborts; files already
            written to *dest_dir* are kept (each file write is atomic,
            the run as a whole is not).
    """
    await asyncio.to_thread(dest_dir.mkdir, parents=True, exist_ok=True)

    exported = 0
    async with session_factory() as session:
        if conversation_ids is None:
            results = await session.exec(select(Conversation.id))
            ids: list[uuid.UUID] = list(results.all())
        else:
            ids = list(dict.fromkeys(conversation_ids))

        for conv_id in ids:
            data = await build_conversation_export(session, conv_id)
            if not data:
                logger.warning("Export: conversation {} not found", conv_id)
                continue
            target = dest_dir / f"{data['id']}.json"
            payload = json.dumps(data, ensure_ascii=False, indent=2)
            await asyncio.to_thread(_atomic_write, target, payload)
            exported += 1

    logger.info("Exported {} conversations to {}", exported, dest_dir)
    return exported
