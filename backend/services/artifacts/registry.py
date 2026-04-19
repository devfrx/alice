"""AL\\CE — Artifact registry (DB persistence + event emission)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from backend.core.config import PROJECT_ROOT
from backend.db.models import Artifact, ArtifactKind
from backend.services.artifacts.parsers import (
    ArtifactDescriptor,
    parse_tool_payload,
)

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Awaitable callback invoked after an artifact is created."""


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


def _normalize_path(file_path: str) -> str:
    """Return *file_path* relative to ``PROJECT_ROOT`` when possible.

    Falls back to the original (absolute) string when the path lives
    outside of the project tree.
    """
    try:
        candidate = Path(file_path).resolve()
        return str(candidate.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except (ValueError, OSError):
        return file_path


def _resolve_path(file_path: str) -> Path:
    """Return an absolute :class:`Path` for *file_path*.

    Relative paths are resolved against ``PROJECT_ROOT``.
    """
    p = Path(file_path)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


class ArtifactRegistry:
    """Service that persists tool outputs as :class:`Artifact` rows.

    The registry is the single integration point used by the chat
    tool-loop to record generated files.  It owns nothing else: the
    underlying tools remain responsible for *producing* the file on
    disk; the registry only records its existence.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        event_callback: EventCallback | None = None,
    ) -> None:
        """Build a new registry.

        Args:
            session_factory: An async SQLModel session factory (the same
                one stored on :attr:`AppContext.db`).
            event_callback: Optional coroutine invoked once per created
                artifact.  See :meth:`set_event_callback`.
        """
        self._session_factory = session_factory
        self._event_callback: EventCallback | None = event_callback

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Register the coroutine called after each ``register_*`` call.

        The payload is a JSON dict::

            {
                "type": "artifact.created",
                "artifact_id": str,
                "kind": str,
                "conversation_id": str,
                "title": str,
            }
        """
        self._event_callback = callback

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def register_from_tool_result(
        self,
        *,
        conversation_id: uuid.UUID | str,
        message_id: uuid.UUID | str | None,
        tool_call_id: str | None,
        tool_name: str,
        payload: dict[str, Any],
        content_type: str | None,
    ) -> Artifact | None:
        """Persist an artifact for a tool result, when the tool is known.

        Returns the created :class:`Artifact` row, or ``None`` if no
        parser is registered for *tool_name* (i.e. the tool does not
        produce artifacts) or the payload is malformed.
        """
        descriptor = parse_tool_payload(tool_name, payload, content_type)
        if descriptor is None:
            return None

        return await self._persist_descriptor(
            descriptor=descriptor,
            conversation_id=_to_uuid(conversation_id),
            message_id=_to_uuid_or_none(message_id),
            tool_call_id=tool_call_id,
        )

    async def _persist_descriptor(
        self,
        *,
        descriptor: ArtifactDescriptor,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID | None,
        tool_call_id: str | None,
    ) -> Artifact:
        """Insert *descriptor* as an ``artifacts`` row and emit the event."""
        rel_path = _normalize_path(descriptor.file_path)
        artifact = Artifact(
            conversation_id=conversation_id,
            message_id=message_id,
            tool_call_id=tool_call_id,
            kind=descriptor.kind,
            title=descriptor.title[:256],
            file_path=rel_path,
            mime=descriptor.mime,
            size_bytes=descriptor.size_bytes,
            artifact_metadata=dict(descriptor.metadata),
        )

        async with self._session_factory() as session:
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)

        logger.info(
            "Artifact registered: id={} kind={} title={!r}",
            artifact.id, artifact.kind.value, artifact.title,
        )

        await self._emit_event({
            "type": "artifact.created",
            "artifact_id": str(artifact.id),
            "kind": artifact.kind.value,
            "conversation_id": str(artifact.conversation_id),
            "title": artifact.title,
        })
        return artifact

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_artifacts(
        self,
        *,
        conversation_id: uuid.UUID | str | None = None,
        kind: ArtifactKind | None = None,
        pinned_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Artifact], int]:
        """List artifacts, optionally filtered.

        Returns a tuple ``(items, total)`` where *total* is the unpaged
        count for the same filter combination.
        """
        from sqlalchemy import func

        async with self._session_factory() as session:
            stmt = select(Artifact)
            count_stmt = select(func.count()).select_from(Artifact)

            if conversation_id is not None:
                conv_uuid = _to_uuid(conversation_id)
                stmt = stmt.where(Artifact.conversation_id == conv_uuid)
                count_stmt = count_stmt.where(
                    Artifact.conversation_id == conv_uuid,
                )
            if kind is not None:
                stmt = stmt.where(Artifact.kind == kind)
                count_stmt = count_stmt.where(Artifact.kind == kind)
            if pinned_only:
                stmt = stmt.where(Artifact.pinned == True)  # noqa: E712
                count_stmt = count_stmt.where(Artifact.pinned == True)  # noqa: E712

            stmt = (
                stmt.order_by(Artifact.created_at.desc())
                .limit(limit)
                .offset(offset)
            )

            items = list((await session.exec(stmt)).all())
            total = (await session.exec(count_stmt)).one()
        return items, int(total)

    async def get_artifact(
        self, artifact_id: uuid.UUID | str,
    ) -> Artifact | None:
        """Return a single artifact by id (``None`` if missing)."""
        artifact_uuid = _to_uuid(artifact_id)
        async with self._session_factory() as session:
            return await session.get(Artifact, artifact_uuid)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def set_pinned(
        self, artifact_id: uuid.UUID | str, pinned: bool,
    ) -> Artifact | None:
        """Toggle the ``pinned`` flag and bump ``updated_at``."""
        artifact_uuid = _to_uuid(artifact_id)
        async with self._session_factory() as session:
            artifact = await session.get(Artifact, artifact_uuid)
            if artifact is None:
                return None
            artifact.pinned = pinned
            artifact.updated_at = _utcnow()
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)
        return artifact

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_artifact(
        self,
        artifact_id: uuid.UUID | str,
        *,
        delete_file: bool = False,
    ) -> bool:
        """Delete an artifact row.  Optionally remove the on-disk file.

        Returns ``True`` if the row was found and deleted.
        """
        artifact_uuid = _to_uuid(artifact_id)
        async with self._session_factory() as session:
            artifact = await session.get(Artifact, artifact_uuid)
            if artifact is None:
                return False
            file_path = artifact.file_path
            await session.delete(artifact)
            await session.commit()

        if delete_file:
            await asyncio.to_thread(_unlink_quietly, _resolve_path(file_path))
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _emit_event(self, event: dict[str, Any]) -> None:
        """Invoke the registered callback (best-effort, never raises)."""
        cb = self._event_callback
        if cb is None:
            return
        try:
            await cb(event)
        except Exception as exc:
            logger.warning("Artifact event callback failed: {}", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce *value* to ``uuid.UUID``."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _to_uuid_or_none(
    value: uuid.UUID | str | None,
) -> uuid.UUID | None:
    """Coerce *value* to ``uuid.UUID`` or pass through ``None``."""
    if value is None:
        return None
    return _to_uuid(value)


def _unlink_quietly(path: Path) -> None:
    """Best-effort ``Path.unlink`` — log and swallow filesystem errors."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Failed to unlink artifact file {}: {}", path, exc)
