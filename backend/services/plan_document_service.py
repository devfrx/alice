"""AL\\CE — Conversation plan-document persistence service (Task T2).

Persists the free-form markdown *plan document* for a conversation as a single
:class:`~backend.db.models.ConversationPlanDocument` row (one per conversation)
so the write-up survives reloads and can be re-injected into the next turn.
Mirrors :class:`~backend.services.plan_service.PlanService` for persistence
(a session factory plus an optional event callback) and, like
:class:`~backend.services.scope_service.ScopeService`, keeps an in-memory mirror
populated at startup via :meth:`PlanDocumentService.load_all`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import ConversationPlanDocument

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Awaitable callback invoked after the plan document is updated or cleared."""


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def _to_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce *value* to ``uuid.UUID`` (accepts an existing UUID or a str)."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def render_plan_document(doc: dict[str, Any]) -> str:
    """Render a persisted plan document as a context block for re-injection.

    Produces a model-readable markdown block (empty string when the document
    has neither a title nor a body) so the model can CONTINUE refining the
    in-progress plan document across turns instead of starting over.  Mirrors
    the tone of :func:`backend.services.plan_service.render_task_steps`.

    Args:
        doc: The persisted document as a ``{"title", "body", "updated_at"}``
            dict (the shape returned by
            :meth:`PlanDocumentService.get_document`).  Keys are read
            defensively.

    Returns:
        A heading-plus-body block, or ``""`` when the document is empty.
    """
    if not doc:
        return ""
    title = str(doc.get("title", "") or "").strip()
    body = str(doc.get("body", "") or "").strip()
    if not title and not body:
        return ""
    block = "# Current plan document\n\n"
    block += (
        "You are maintaining this plan document. Continue refining it in place "
        "and keep it up to date. Do not discard it."
    )
    if title:
        block += f"\n\n## {title}"
    if body:
        block += f"\n\n{body}"
    return block


class PlanDocumentService:
    """Persist and serve the per-conversation free-form plan document.

    There is exactly one :class:`ConversationPlanDocument` row per conversation
    (the conversation id is the primary key), so :meth:`set_document` performs
    an idempotent UPSERT that replaces the document wholesale.  An in-memory
    ``uuid -> {"title", "body", "updated_at"}`` mirror is kept (populated by
    :meth:`load_all` at startup and updated on every mutation) so
    :meth:`get_document` answers without a DB round-trip.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[SQLModelAsyncSession],
        event_callback: EventCallback | None = None,
    ) -> None:
        """Build a new plan-document service.

        Args:
            session_factory: An async SQLModel session factory (the same one
                stored on :attr:`AppContext.db`).
            event_callback: Optional coroutine invoked once per
                :meth:`set_document` / :meth:`clear_document` call.  See
                :meth:`set_event_callback`.
        """
        self._session_factory = session_factory
        self._event_callback: EventCallback | None = event_callback
        # In-memory mirror: conversation id -> {"title", "body", "updated_at"}.
        self._documents: dict[uuid.UUID, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Register the coroutine called after each document mutation.

        The payload is a JSON dict::

            {
                "type": "plan_document.updated",
                "conversation_id": str,
                "title": str,
                "body": str,
                "updated_at": str | None,
            }
        """
        self._event_callback = callback

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    async def load_all(self) -> None:
        """Populate the in-memory mirror from every persisted document row.

        Called once at startup so :meth:`get_document` is correct without any
        async round-trip.
        """
        documents: dict[uuid.UUID, dict[str, Any]] = {}
        async with self._session_factory() as session:
            result = await session.exec(select(ConversationPlanDocument))
            rows = result.all()
        for row in rows:
            documents[row.conversation_id] = {
                "title": row.title,
                "body": row.body,
                "updated_at": row.updated_at,
            }
        self._documents = documents
        logger.debug(
            "Loaded {} conversation plan document(s) into memory",
            len(documents),
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_document(
        self, conversation_id: uuid.UUID | str,
    ) -> dict[str, Any] | None:
        """Return the stored plan document for *conversation_id*.

        Reads the in-memory mirror (kept in sync by :meth:`set_document`,
        :meth:`clear_document` and :meth:`load_all`), so this never hits the DB.

        Args:
            conversation_id: The owning conversation id.

        Returns:
            A ``{"title", "body", "updated_at"}`` dict, or ``None`` when no
            document is set for the conversation.
        """
        conv_uuid = _to_uuid(conversation_id)
        doc = self._documents.get(conv_uuid)
        if doc is None:
            return None
        return dict(doc)

    # ------------------------------------------------------------------
    # Mutate
    # ------------------------------------------------------------------

    async def set_document(
        self,
        conversation_id: uuid.UUID | str,
        title: str,
        body: str,
    ) -> None:
        """Store *title* / *body* as the plan document (idempotent UPSERT).

        Replaces the document wholesale: if a row already exists it is updated
        in place (``title`` + ``body`` + ``updated_at``); otherwise a new
        :class:`ConversationPlanDocument` is inserted.  Calling this twice for
        the same conversation leaves exactly one row carrying the latest
        content.  After the commit the in-memory mirror is updated and the
        registered event callback (if any) is invoked best-effort.

        Args:
            conversation_id: The owning conversation id.
            title: The optional short heading for the document.
            body: The markdown body text.
        """
        conv_uuid = _to_uuid(conversation_id)
        now = _utcnow()
        async with self._session_factory() as session:
            row = await session.get(ConversationPlanDocument, conv_uuid)
            if row is None:
                row = ConversationPlanDocument(
                    conversation_id=conv_uuid,
                    title=title,
                    body=body,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.title = title
                row.body = body
                row.updated_at = now
            await session.commit()

        self._documents[conv_uuid] = {
            "title": title,
            "body": body,
            "updated_at": now,
        }
        logger.debug(
            "Plan document persisted: conversation_id={} body_len={}",
            conv_uuid, len(body),
        )

        await self._emit_event({
            "type": "plan_document.updated",
            "conversation_id": str(conversation_id),
            "title": title,
            "body": body,
            "updated_at": now.isoformat(),
        })

    async def clear_document(
        self, conversation_id: uuid.UUID | str,
    ) -> None:
        """Delete the conversation's plan document and drop the mirror entry.

        A no-op on the DB side when no row exists, but the
        ``plan_document.updated`` event (with an empty title/body) is still
        emitted so listeners learn the document was cleared.

        Args:
            conversation_id: The owning conversation id.
        """
        conv_uuid = _to_uuid(conversation_id)
        async with self._session_factory() as session:
            row = await session.get(ConversationPlanDocument, conv_uuid)
            if row is not None:
                await session.delete(row)
                await session.commit()

        self._documents.pop(conv_uuid, None)

        await self._emit_event({
            "type": "plan_document.updated",
            "conversation_id": str(conversation_id),
            "title": "",
            "body": "",
            "updated_at": None,
        })

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
            logger.warning("Plan document event callback failed: {}", exc)
