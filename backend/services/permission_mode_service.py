"""AL\\CE — Per-conversation permission-tier service (Fase 7).

Persists the **permission mode** (authorization tier) for each conversation as
a single :class:`~backend.db.models.ConversationPermissionMode` row and keeps an
in-memory mirror so the **synchronous** :meth:`PermissionModeService.get_mode`
can answer the turn engine's permission gate without awaiting.  Mirrors
:class:`~backend.services.scope_service.ScopeService` (a session factory plus an
optional event callback + sync read path) with two deliberate differences:

* :meth:`get_mode` never returns ``None`` — an unset conversation resolves to
  the configured default (``strict``), so the gate never special-cases "no
  mode".
* the mode is **settable at any time** (including mid-turn), because the engine
  reads it synchronously *per tool-call*; the REST layer therefore applies **no
  idle guard** (unlike scope).  Only the user may mutate it — the service is
  never reachable from a tool (anti-privilege-escalation).

The four tiers are:

``strict``      prompt for every confirmation-required / write / exec tool;
                reads inside scope are auto-allowed.  (Pre-Fase-7 behaviour.)
``auto_edits``  auto-approve safe filesystem writes/edits **inside scope**; still
                prompt for dangerous / process-exec tools.
``plan``        read-only — block every write / exec.
``autopilot``   full autonomy, no prompts; circuit-breakers (forbidden risk,
                out-of-scope path, no-scope-set) still hold.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import ConversationPermissionMode

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Awaitable callback invoked after a mode is set or changed."""


class PermissionMode(StrEnum):
    """The authorization tier governing a conversation's tool-calls."""

    STRICT = "strict"
    AUTO_EDITS = "auto_edits"
    PLAN = "plan"
    AUTOPILOT = "autopilot"

    @classmethod
    def coerce(cls, value: object, default: PermissionMode) -> PermissionMode:
        """Best-effort coerce *value* to a member, falling back to *default*.

        Load-bearing for behaviour preservation: the turn engine resolves the
        mode from a possibly-``MagicMock`` test context, so anything that is not
        a valid tier string must degrade to *default* (``strict``) rather than
        raise.

        Args:
            value: A candidate mode (a member, a tier string, or junk).
            default: The mode to return when *value* is not a valid tier.

        Returns:
            A valid :class:`PermissionMode`.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except (ValueError, TypeError):
            return default


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def _to_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce *value* to ``uuid.UUID`` (accepts an existing UUID or a str)."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class PermissionModeService:
    """Persist and serve the per-conversation permission tier.

    There is exactly one :class:`ConversationPermissionMode` row per
    conversation (the conversation id is the primary key), so :meth:`set_mode`
    performs an idempotent UPSERT.  An in-memory ``str -> PermissionMode`` mirror
    is kept so :meth:`get_mode` — read by the turn engine's permission gate —
    can answer synchronously without touching the DB.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[SQLModelAsyncSession],
        default_mode: PermissionMode,
        event_callback: EventCallback | None = None,
    ) -> None:
        """Build a new permission-mode service.

        Args:
            session_factory: An async SQLModel session factory (the same one
                stored on :attr:`AppContext.db`).
            default_mode: The tier returned for a conversation with no row.
            event_callback: Optional coroutine invoked once per :meth:`set_mode`
                call.  See :meth:`set_event_callback`.
        """
        self._session_factory = session_factory
        self._default_mode = default_mode
        self._event_callback: EventCallback | None = event_callback
        # In-memory mirror: conversation id (str) -> resolved tier.
        self._modes: dict[str, PermissionMode] = {}

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    @property
    def default_mode(self) -> PermissionMode:
        """The tier used when a conversation has no explicit mode."""
        return self._default_mode

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Register the coroutine called after each mode mutation.

        The payload is a JSON dict::

            {
                "type": "permission_mode.updated",
                "conversation_id": str,
                "mode": str,
            }
        """
        self._event_callback = callback

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    async def load_all(self) -> None:
        """Populate the in-memory mirror from every persisted mode row.

        Called once at startup so :meth:`get_mode` is correct without any async
        round-trip.  A row carrying an unknown tier string degrades to the
        configured default rather than poisoning the mirror.
        """
        modes: dict[str, PermissionMode] = {}
        async with self._session_factory() as session:
            result = await session.exec(select(ConversationPermissionMode))
            rows = result.all()
        for row in rows:
            modes[str(row.conversation_id)] = PermissionMode.coerce(
                row.mode, self._default_mode,
            )
        self._modes = modes
        logger.debug("Loaded {} conversation permission-mode(s)", len(modes))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_mode(self, conversation_id: uuid.UUID | str) -> PermissionMode:
        """Return the conversation's tier (**SYNC**); default when unset.

        This is the callable read by the turn engine's permission gate; it must
        be synchronous and must never return ``None`` (an unset conversation
        resolves to the configured default tier).

        Args:
            conversation_id: The conversation id (keyed in memory by its str).

        Returns:
            The resolved :class:`PermissionMode`.
        """
        return self._modes.get(str(conversation_id), self._default_mode)

    # ------------------------------------------------------------------
    # Mutate
    # ------------------------------------------------------------------

    async def set_mode(
        self,
        conversation_id: uuid.UUID | str,
        mode: PermissionMode,
    ) -> None:
        """Persist *mode* as the conversation tier and broadcast the change.

        The :class:`ConversationPermissionMode` row is UPSERTed (one row per
        conversation), the in-memory mirror is updated, and the
        ``permission_mode.updated`` event is emitted best-effort.

        Args:
            conversation_id: The owning conversation id.
            mode: The new permission tier.
        """
        conv_uuid = _to_uuid(conversation_id)
        conv_key = str(conversation_id)

        async with self._session_factory() as session:
            row = await session.get(ConversationPermissionMode, conv_uuid)
            if row is None:
                row = ConversationPermissionMode(
                    conversation_id=conv_uuid,
                    mode=mode.value,
                )
                session.add(row)
            else:
                row.mode = mode.value
                row.updated_at = _utcnow()
            await session.commit()

        self._modes[conv_key] = mode
        logger.debug("Permission mode persisted: conversation_id={} mode={}", conv_key, mode.value)

        await self._emit_event({
            "type": "permission_mode.updated",
            "conversation_id": conv_key,
            "mode": mode.value,
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
            logger.warning("Permission-mode event callback failed: {}", exc)
