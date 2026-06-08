"""AL\\CE — Conversation-plan persistence service (Fase 5).

Persists the model-owned todo-list (``update_plan``) as a single
:class:`~backend.db.models.ConversationPlan` row per conversation so the
plan survives reloads and can be re-injected into the next turn.  Mirrors
:class:`~backend.services.artifacts.registry.ArtifactRegistry`: it owns a
session factory for DB access and an optional event callback for broadcast.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import ConversationPlan

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Awaitable callback invoked after a plan is updated."""


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def _to_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce *value* to ``uuid.UUID`` (accepts an existing UUID or a str)."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class PlanService:
    """Persist and retrieve the per-conversation plan (todo-list).

    There is exactly one :class:`ConversationPlan` row per conversation
    (the conversation id is the primary key), so :meth:`set_plan` performs
    an idempotent UPSERT.  The service is the single integration point used
    by the ``agent`` plugin's ``update_plan`` meta-tool and by the turn
    engine's plan re-injection.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        event_callback: EventCallback | None = None,
    ) -> None:
        """Build a new plan service.

        Args:
            session_factory: An async SQLModel session factory (the same
                one stored on :attr:`AppContext.db`).
            event_callback: Optional coroutine invoked once per
                :meth:`set_plan` call.  See :meth:`set_event_callback`.
        """
        self._session_factory = session_factory
        self._event_callback: EventCallback | None = event_callback

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Register the coroutine called after each :meth:`set_plan`.

        The payload is a JSON dict::

            {
                "type": "plan.updated",
                "conversation_id": str,
                "steps": list[dict],
            }
        """
        self._event_callback = callback

    # ------------------------------------------------------------------
    # Mutate
    # ------------------------------------------------------------------

    async def set_plan(
        self,
        conversation_id: uuid.UUID | str,
        steps: list[dict[str, Any]],
    ) -> None:
        """Store *steps* as the plan for *conversation_id* (idempotent UPSERT).

        If a row already exists it is updated in place (``steps`` +
        ``updated_at``); otherwise a new :class:`ConversationPlan` is
        inserted.  Calling this twice for the same conversation leaves
        exactly one row carrying the latest steps.  After the commit the
        registered event callback (if any) is invoked best-effort.

        Args:
            conversation_id: The owning conversation id.
            steps: Ordered list of ``{"step": str, "status": str}`` items.
        """
        conv_uuid = _to_uuid(conversation_id)
        async with self._session_factory() as session:
            row = await session.get(ConversationPlan, conv_uuid)
            if row is None:
                row = ConversationPlan(
                    conversation_id=conv_uuid,
                    steps=list(steps),
                )
                session.add(row)
            else:
                row.steps = list(steps)
                row.updated_at = _utcnow()
            await session.commit()

        logger.debug(
            "Plan persisted: conversation_id={} steps={}",
            conv_uuid, len(steps),
        )

        await self._emit_event({
            "type": "plan.updated",
            "conversation_id": str(conversation_id),
            "steps": steps,
        })

    async def clear(self, conversation_id: uuid.UUID | str) -> None:
        """Delete the plan row for *conversation_id* if it exists.

        A no-op when no plan is stored.  Emits no event.

        Args:
            conversation_id: The owning conversation id.
        """
        conv_uuid = _to_uuid(conversation_id)
        async with self._session_factory() as session:
            row = await session.get(ConversationPlan, conv_uuid)
            if row is None:
                return
            await session.delete(row)
            await session.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_plan(
        self, conversation_id: uuid.UUID | str,
    ) -> list[dict[str, Any]]:
        """Return the stored plan steps for *conversation_id*.

        Returns an empty list when no plan row exists (or the stored value
        is not a list).

        Args:
            conversation_id: The owning conversation id.

        Returns:
            The ordered list of step dicts, or ``[]``.
        """
        conv_uuid = _to_uuid(conversation_id)
        async with self._session_factory() as session:
            row = await session.get(ConversationPlan, conv_uuid)
            if row is None:
                return []
            steps = row.steps
        if isinstance(steps, list):
            return steps
        return []

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
            logger.warning("Plan event callback failed: {}", exc)
