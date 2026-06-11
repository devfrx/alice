"""AL\\CE — Chat file I/O endpoints (export / import / upload).

Conversation export and import (JSON), the conversation file-path lookup
used by the Electron shell, and the vision image upload endpoint with
magic-byte validation.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import File, Form, HTTPException, Request, UploadFile
from loguru import logger

from backend.core.config import PROJECT_ROOT
from backend.db.models import Attachment, Conversation, Message
from backend.services.conversation_export import build_conversation_export
from backend.services.conversation_file_manager import ConversationFileManager

from ._helpers import _sync_conversation_to_file
from ._shared import _ctx, _utcnow, router

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

# Allowed MIME types for image uploads.
_ALLOWED_IMAGE_TYPES: set[str] = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}


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
    return any(_matches(alt) for alt in _MAGIC_ALT.get(claimed_type, []))


# ---------------------------------------------------------------------------
# REST — export / import conversations
# ---------------------------------------------------------------------------


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
        data = await build_conversation_export(session, conversation_id)
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
        raise HTTPException(
            status_code=400, detail="Invalid JSON body",
        ) from None

    if "id" not in body:
        raise HTTPException(status_code=400, detail="Missing 'id' field")

    try:
        conv_id = uuid.UUID(body["id"])
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid conversation id",
        ) from None

    # Validate top-level timestamps if present.
    for ts_field in ("created_at", "updated_at"):
        if body.get(ts_field):
            try:
                datetime.fromisoformat(body[ts_field])
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid '{ts_field}' timestamp",
                ) from None

    # Validate messages before touching the DB.
    allowed_roles = ("user", "assistant", "system", "tool")
    for idx, msg_data in enumerate(body.get("messages", [])):
        for required in ("id", "role"):
            if required not in msg_data:
                raise HTTPException(
                    status_code=400,
                    detail=f"Message {idx}: missing '{required}'",
                )
        if msg_data["role"] not in allowed_roles:
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
            ) from None
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
                    # Always allocate a fresh UUID for the imported row.
                    # Re-using the exported ``file_id`` as a primary key
                    # would collide on the second import of the same
                    # export (Attachment.id is the PK).
                    id=uuid.uuid4(),
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
        ) from None

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
        ) from None

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
