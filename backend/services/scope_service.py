"""AL\\CE — Per-conversation workspace-scope service (Fase 6).

Persists the workspace folder scope for each conversation as a single
:class:`~backend.db.models.ConversationScope` row and keeps an in-memory
mirror so the **synchronous** :meth:`ScopeService.scope_roots` can answer the
turn engine's :class:`~backend.services.permission_service.PermissionService`
without awaiting.  Mirrors :class:`~backend.services.plan_service.PlanService`
for persistence (a session factory plus an optional event callback) and adds
the in-memory dict for the sync read path.

``scope_roots`` returns the *explicit* folders only (``None`` when none are
set).  The sandbox / disabled fallback for an unset scope is deliberately
**not** applied here — it belongs to the terminal plugin (a later task).
Keeping ``scope_roots`` explicit-only is exactly what makes wiring it into the
permission layer behaviour-preserving: no scope set ⇒ ``None`` ⇒ no
confinement.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.config import WorkspaceScopeConfig
from backend.db.models import ConversationScope

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Awaitable callback invoked after a scope is created, changed or cleared."""

# Windows system roots that are always out of scope.  Replicated (not
# imported) from ``backend.plugins.pc_automation.constants.FORBIDDEN_PATHS``
# — and matching the system-dir check in
# ``backend.plugins.pc_automation.security.validate_path`` — so the service
# stays decoupled from plugin internals.  ``WorkspaceScopeConfig.forbidden_paths``
# is layered on top of these at validation time.
_SYSTEM_ROOTS: tuple[str, ...] = (
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
    r"C:\$Recycle.Bin",
    r"C:\System Volume Information",
    r"C:\Recovery",
    r"C:\Boot",
)


def _utcnow() -> datetime:
    """Return the current UTC time (timezone-aware)."""
    return datetime.now(UTC)


def _to_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Coerce *value* to ``uuid.UUID`` (accepts an existing UUID or a str)."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _is_relative_to(target: Path, root: Path) -> bool:
    """Return ``True`` iff *target* is at or under *root* (never raises)."""
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


class ScopeService:
    """Persist and serve the per-conversation workspace folder scope.

    There is exactly one :class:`ConversationScope` row per conversation (the
    conversation id is the primary key), so :meth:`set_scope` performs an
    idempotent UPSERT.  An in-memory ``str -> list[Path]`` mirror is kept so
    :meth:`scope_roots` — the
    :class:`~backend.services.permission_service.PermissionService` scope
    provider — can answer synchronously without touching the DB.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[SQLModelAsyncSession],
        config: WorkspaceScopeConfig,
        event_callback: EventCallback | None = None,
    ) -> None:
        """Build a new scope service.

        Args:
            session_factory: An async SQLModel session factory (the same one
                stored on :attr:`AppContext.db`).
            config: The workspace-scope policy (forbidden roots, fallback).
            event_callback: Optional coroutine invoked once per
                :meth:`set_scope` / :meth:`clear_scope` call.  See
                :meth:`set_event_callback`.
        """
        self._session_factory = session_factory
        self._config = config
        self._event_callback: EventCallback | None = event_callback
        # In-memory mirror: conversation id (str) -> resolved scope folders.
        self._scopes: dict[str, list[Path]] = {}

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Register the coroutine called after each scope mutation.

        The payload is a JSON dict::

            {
                "type": "scope.updated",
                "conversation_id": str,
                "folders": list[str],
            }
        """
        self._event_callback = callback

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    async def load_all(self) -> None:
        """Populate the in-memory mirror from every persisted scope row.

        Called once at startup so :meth:`scope_roots` is correct without any
        async round-trip.  The stored folder strings are already absolute and
        resolved (written by :meth:`set_scope`); they are wrapped back into
        :class:`~pathlib.Path` objects as-is.
        """
        scopes: dict[str, list[Path]] = {}
        async with self._session_factory() as session:
            result = await session.exec(select(ConversationScope))
            rows = result.all()
        for row in rows:
            folders = row.folders if isinstance(row.folders, list) else []
            scopes[str(row.conversation_id)] = [Path(str(f)) for f in folders]
        self._scopes = scopes
        logger.debug("Loaded {} conversation scope(s) into memory", len(scopes))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def scope_roots(self, conversation_id: str) -> list[Path] | None:
        """Return the resolved scope folders for *conversation_id* (**SYNC**).

        This is the callable handed to
        :class:`~backend.services.permission_service.PermissionService` as its
        ``scope_provider``; it must be synchronous and must return ``None``
        when no explicit scope is set (so the permission layer imposes *no*
        confinement — the behaviour-preserving default).  The sandbox /
        disabled fallback for an unset scope is intentionally not applied here.

        Args:
            conversation_id: The conversation id (keyed in memory by its str).

        Returns:
            A copy of the resolved scope roots, or ``None`` when none are set.
        """
        roots = self._scopes.get(str(conversation_id))
        if not roots:
            return None
        return list(roots)

    async def get_scope(self, conversation_id: uuid.UUID | str) -> list[str]:
        """Return the conversation's scope folders as strings (for the REST API).

        Reads the in-memory mirror (kept in sync by :meth:`set_scope`,
        :meth:`clear_scope` and :meth:`load_all`), so this never hits the DB.

        Args:
            conversation_id: The owning conversation id.

        Returns:
            The scope folders as absolute path strings, or ``[]`` when unset.
        """
        roots = self._scopes.get(str(conversation_id))
        if not roots:
            return []
        return [str(p) for p in roots]

    # ------------------------------------------------------------------
    # Mutate
    # ------------------------------------------------------------------

    async def set_scope(
        self,
        conversation_id: uuid.UUID | str,
        folders: list[str],
    ) -> None:
        """Validate, resolve and persist *folders* as the conversation scope.

        Every folder is validated with :meth:`validate_folder` *before* any
        write, so a single bad entry raises and leaves the stored scope
        untouched.  On success the :class:`ConversationScope` row is UPSERTed
        (one row per conversation), the in-memory mirror is updated, and the
        ``scope.updated`` event is emitted best-effort.

        Args:
            conversation_id: The owning conversation id.
            folders: Candidate absolute folder paths to confine tools to.

        Raises:
            ValueError: If any folder fails :meth:`validate_folder` (nothing is
                persisted in that case).
        """
        resolved = [self.validate_folder(folder) for folder in folders]
        stored = [str(path) for path in resolved]
        conv_uuid = _to_uuid(conversation_id)
        conv_key = str(conversation_id)

        async with self._session_factory() as session:
            row = await session.get(ConversationScope, conv_uuid)
            if row is None:
                row = ConversationScope(
                    conversation_id=conv_uuid,
                    folders=stored,
                )
                session.add(row)
            else:
                row.folders = stored
                row.updated_at = _utcnow()
            await session.commit()

        self._scopes[conv_key] = resolved
        logger.debug(
            "Scope persisted: conversation_id={} folders={}",
            conv_key, len(resolved),
        )

        await self._emit_event({
            "type": "scope.updated",
            "conversation_id": conv_key,
            "folders": stored,
        })

    async def clear_scope(self, conversation_id: uuid.UUID | str) -> None:
        """Delete the conversation's scope row and drop the in-memory entry.

        A no-op on the DB side when no row exists, but the ``scope.updated``
        event (with an empty ``folders`` list) is still emitted so listeners
        learn the scope was cleared.

        Args:
            conversation_id: The owning conversation id.
        """
        conv_uuid = _to_uuid(conversation_id)
        conv_key = str(conversation_id)

        async with self._session_factory() as session:
            row = await session.get(ConversationScope, conv_uuid)
            if row is not None:
                await session.delete(row)
                await session.commit()

        self._scopes.pop(conv_key, None)

        await self._emit_event({
            "type": "scope.updated",
            "conversation_id": conv_key,
            "folders": [],
        })

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_folder(self, folder: str) -> Path:
        """Validate *folder* is a safe, existing directory and resolve it.

        Replicates the minimal filesystem-safety checks used by the
        ``pc_automation`` and ``file_search`` plugins (rather than importing
        their internals, which would couple this service to plugin code):

        * reject empty / blank input;
        * reject UNC and device paths — a leading ``\\`` or ``//`` — mirroring
          :func:`backend.plugins.pc_automation.security.validate_path` and
          :func:`backend.plugins.file_search.searcher._validate_path`, which
          both refuse network/device paths outright;
        * resolve symlinks and ``..`` first so a traversal cannot smuggle a
          path past the forbidden-root check below;
        * require the resolved path to exist and be a directory;
        * reject anything at or under a forbidden / system root —
          ``self._config.forbidden_paths`` plus the Windows system roots
          replicated from ``pc_automation`` ``FORBIDDEN_PATHS``.

        Args:
            folder: The candidate absolute folder path.

        Returns:
            The resolved, validated directory :class:`~pathlib.Path`.

        Raises:
            ValueError: If *folder* fails any of the checks above.
        """
        if not folder or not folder.strip():
            raise ValueError("Empty folder path")

        raw = folder.strip()

        # Reject UNC (``\\server\share``) and device (``\\.\dev``) paths, plus
        # forward-slash UNC (``//server/share``).  A single leading backslash
        # is also refused (it can degrade into a UNC path on normalisation),
        # mirroring ``pc_automation.security.validate_path``.
        if raw.startswith("\\") or raw.startswith("//"):
            raise ValueError(f"UNC and device paths are not allowed: {folder}")

        # Resolve symlinks / ``..`` before the forbidden-root check (a
        # traversal must not be able to escape it).  ``strict=False`` —
        # existence is asserted explicitly just below.
        try:
            resolved = Path(raw).resolve()
        except (OSError, ValueError) as exc:
            raise ValueError(f"Invalid folder path: {exc}") from exc

        if not resolved.exists():
            raise ValueError(f"Folder does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"Not a directory: {resolved}")

        # Forbidden / system roots: configured roots first, then the
        # replicated Windows system roots.  Each is resolved best-effort.
        for entry in (*self._config.forbidden_paths, *_SYSTEM_ROOTS):
            try:
                forbidden_root = Path(entry).resolve()
            except (OSError, ValueError):
                continue
            if _is_relative_to(resolved, forbidden_root):
                raise ValueError(
                    f"Folder '{resolved}' is inside a forbidden/system root: "
                    f"{forbidden_root}"
                )

        return resolved

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
            logger.warning("Scope event callback failed: {}", exc)
