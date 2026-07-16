"""AL\\CE — Artifact registry (DB persistence + event emission)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from backend.core.config import PROJECT_ROOT
from backend.db.models import Artifact, ArtifactKind
from backend.services.artifacts.blob_store import ArtifactBlobStore
from backend.services.artifacts.parsers import (
    ArtifactDescriptor,
    parse_tool_payload,
)

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Awaitable callback invoked after an artifact is created."""


def _whiteboard_metadata(content: dict[str, Any]) -> dict[str, Any]:
    """Derive list-display metadata from a whiteboard blob (tldraw spec)."""
    snapshot = content.get("snapshot")
    store = snapshot.get("store", {}) if isinstance(snapshot, dict) else {}
    count = sum(
        1
        for v in store.values()
        if isinstance(v, dict) and v.get("typeName") == "shape"
    )
    return {"shape_count": count}


_JSON_METADATA_HOOKS: dict[
    ArtifactKind, Callable[[dict[str, Any]], dict[str, Any]]
] = {
    ArtifactKind.WHITEBOARD: _whiteboard_metadata,
}


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(UTC)


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
        blob_store: ArtifactBlobStore | None = None,
    ) -> None:
        """Build a new registry.

        Args:
            session_factory: An async SQLModel session factory (the same
                one stored on :attr:`AppContext.db`).
            event_callback: Optional coroutine invoked once per created
                artifact.  See :meth:`set_event_callback`.
            blob_store: JSON blob store for chart/whiteboard content.
                Defaults to :class:`ArtifactBlobStore` with the standard
                ``data/artifacts/`` root.
        """
        self._session_factory = session_factory
        self._event_callback: EventCallback | None = event_callback
        self._blob_store = blob_store or ArtifactBlobStore()

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
    # JSON-kind artifacts (chart, whiteboard, ...)
    # ------------------------------------------------------------------

    async def create_json_artifact(
        self,
        *,
        kind: ArtifactKind,
        title: str,
        content: dict[str, Any],
        conversation_id: uuid.UUID | str | None = None,
        message_id: uuid.UUID | str | None = None,
        tool_call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        artifact_id: uuid.UUID | None = None,
    ) -> Artifact:
        """Persist a JSON-content artifact: blob on disk + row + event.

        Args:
            kind: Target :class:`ArtifactKind` (blob lives in
                ``data/artifacts/<kind>/``).
            title: Human-readable label (clipped to 256 chars).
            content: JSON-serialisable blob content.
            conversation_id: Optional source conversation.
            message_id: Optional producing tool message.
            tool_call_id: Optional producing tool-call id.
            metadata: Free-form metadata; merged with the per-kind hook
                output (hook wins on key collisions).
            artifact_id: Pre-generated id, so callers can embed it in
                *content* before persisting.  Generated when omitted.

        Note: the blob is written before the row commit; a commit
        failure may leave an orphan blob on disk (acceptable for the
        single-user local app).
        """
        aid = artifact_id or uuid.uuid4()
        path, size = await self._blob_store.write(kind, aid, content)
        meta = dict(metadata or {})
        hook = _JSON_METADATA_HOOKS.get(kind)
        if hook is not None:
            meta.update(hook(content))
        artifact = Artifact(
            id=aid,
            conversation_id=_to_uuid_or_none(conversation_id),
            message_id=_to_uuid_or_none(message_id),
            tool_call_id=tool_call_id,
            kind=kind,
            title=title[:256],
            file_path=_normalize_path(str(path)),
            mime="application/json",
            size_bytes=size,
            artifact_metadata=meta,
        )
        async with self._session_factory() as session:
            session.add(artifact)
            await session.commit()
            await session.refresh(artifact)

        logger.info(
            "JSON artifact created: id={} kind={} title={!r}",
            artifact.id, artifact.kind.value, artifact.title,
        )
        await self._emit_event({
            "type": "artifact.created",
            "artifact_id": str(artifact.id),
            "kind": artifact.kind.value,
            "conversation_id": (
                str(artifact.conversation_id)
                if artifact.conversation_id else None
            ),
            "title": artifact.title,
        })
        return artifact

    async def read_json_content(
        self, artifact_id: uuid.UUID | str,
    ) -> tuple[Artifact, dict[str, Any]] | None:
        """Return ``(row, blob content)`` for a JSON-kind artifact.

        ``None`` when the artifact is missing, is not JSON-mime, or the
        blob is unreadable.
        Callers cannot distinguish the unreadable-blob case (data
        corruption) from not-found.
        """
        artifact = await self.get_artifact(artifact_id)
        if artifact is None or artifact.mime != "application/json":
            return None
        content = await self._blob_store.read(artifact.file_path)
        if content is None:
            return None
        return artifact, content

    async def update_json_artifact(
        self,
        artifact_id: uuid.UUID | str,
        *,
        content_patch: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> Artifact | None:
        """Merge *content_patch* into the blob and/or retitle the row.

        Top-level merge semantics: ``blob.update(content_patch)``.  When
        the blob carries an ``updated_at`` key it is refreshed; per-kind
        metadata hooks re-run on the merged content.  Emits
        ``artifact.updated``.  Returns ``None`` when the artifact is
        missing or has no JSON content.
        Note: the merged blob is rewritten before the row commit; a
        commit failure may leave blob and row out of sync.
        """
        artifact = await self.get_artifact(artifact_id)
        if artifact is None or artifact.mime != "application/json":
            return None
        size: int | None = None
        meta = dict(artifact.artifact_metadata)
        if content_patch:
            content = await self._blob_store.read(artifact.file_path)
            if content is None:
                return None
            content.update(content_patch)
            if "updated_at" in content:
                content["updated_at"] = _utcnow().isoformat()
            _path, size = await self._blob_store.write(
                artifact.kind, artifact.id, content,
            )
            hook = _JSON_METADATA_HOOKS.get(artifact.kind)
            if hook is not None:
                meta.update(hook(content))
        async with self._session_factory() as session:
            row = await session.get(Artifact, artifact.id)
            if row is None:
                return None
            if title is not None:
                row.title = title[:256]
            if size is not None:
                row.size_bytes = size
            row.artifact_metadata = meta
            row.updated_at = _utcnow()
            session.add(row)
            await session.commit()
            await session.refresh(row)

        await self._emit_event({
            "type": "artifact.updated", "artifact_id": str(row.id),
        })
        return row

    async def count_artifacts(
        self,
        *,
        kind: ArtifactKind | None = None,
        conversation_id: uuid.UUID | str | None = None,
    ) -> int:
        """Count artifacts, optionally filtered by kind/conversation."""
        from sqlalchemy import func

        async with self._session_factory() as session:
            stmt = select(func.count()).select_from(Artifact)
            if kind is not None:
                stmt = stmt.where(Artifact.kind == kind)
            if conversation_id is not None:
                stmt = stmt.where(
                    Artifact.conversation_id == _to_uuid(conversation_id),
                )
            total = (await session.exec(stmt)).one()
        return int(total)

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
        await self._emit_event({
            "type": "artifact.updated", "artifact_id": str(artifact.id),
        })
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
        await self._emit_event({
            "type": "artifact.deleted", "artifact_id": str(artifact_uuid),
        })
        return True

    async def delete_for_conversation(
        self, conversation_id: uuid.UUID | str,
    ) -> int:
        """Conversation-deletion cleanup (single implementation).

        Pinned artifacts survive detached (``conversation_id=NULL``,
        preserved on the board); unpinned rows are deleted together with
        their on-disk files.  Emits a single ``artifact.bulk_deleted``
        event (no per-row events) whenever rows were deleted OR pinned
        rows were detached.  Returns the number of deleted rows.
        """
        conv_uuid = _to_uuid(conversation_id)
        async with self._session_factory() as session:
            unpinned_q = await session.exec(
                select(Artifact.id, Artifact.file_path).where(
                    Artifact.conversation_id == conv_uuid,
                    Artifact.pinned == False,  # noqa: E712 (SQL boolean)
                )
            )
            unpinned: list[tuple[uuid.UUID, str]] = list(unpinned_q.all())
            conn = await session.connection()
            if unpinned:
                await conn.execute(
                    sa.delete(Artifact).where(
                        Artifact.id.in_(  # type: ignore[attr-defined]
                            [aid for aid, _ in unpinned],
                        )
                    )
                )
            detach_result = await conn.execute(
                sa.update(Artifact)
                .where(
                    Artifact.conversation_id == conv_uuid,
                    Artifact.pinned == True,  # noqa: E712
                )
                .values(conversation_id=None)
            )
            detached = int(detach_result.rowcount or 0)
            await session.commit()

        # Best-effort file cleanup AFTER commit (a transient FS failure
        # must not roll back the row deletion).
        for _aid, file_path in unpinned:
            await asyncio.to_thread(_unlink_quietly, _resolve_path(file_path))
        if unpinned or detached:
            await self._emit_event({
                "type": "artifact.bulk_deleted",
                "conversation_id": str(conv_uuid),
                "artifact_ids": [str(aid) for aid, _ in unpinned],
            })
        return len(unpinned)

    async def delete_all(self) -> int:
        """Delete EVERY artifact row and on-disk file (full wipe).

        Used by "delete all conversations"; pinned status is irrelevant
        because the user asked to delete everything.  Emits a single
        ``artifact.bulk_deleted`` event with ``conversation_id=None``.
        """
        async with self._session_factory() as session:
            paths_q = await session.exec(
                select(Artifact.id, Artifact.file_path),
            )
            rows: list[tuple[uuid.UUID, str]] = list(paths_q.all())
            conn = await session.connection()
            await conn.execute(sa.delete(Artifact))
            await session.commit()

        for _aid, file_path in rows:
            await asyncio.to_thread(_unlink_quietly, _resolve_path(file_path))
        if rows:
            await self._emit_event({
                "type": "artifact.bulk_deleted",
                "conversation_id": None,
                "artifact_ids": [str(aid) for aid, _ in rows],
            })
        return len(rows)

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
