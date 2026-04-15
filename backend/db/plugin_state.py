"""AL\\CE — Plugin state persistence repository.

Provides a thin async repository over the ``plugin_states`` table so
that plugin enable/disable toggles survive application restarts.

Usage pattern (mirrors PreferencesService):

    repo = PluginStateRepository(ctx.db)
    states = await repo.get_all()          # {name: enabled, ...}
    await repo.set("web_search", False)    # upsert
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import PluginState


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PluginStateRepository:
    """Async repository for plugin enabled/disabled state.

    Args:
        session_factory: The ``async_sessionmaker`` stored in
            ``AppContext.db`` (set up in ``core/app.py``).
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def get_all(self) -> dict[str, bool]:
        """Return all persisted plugin states as ``{plugin_name: enabled}``.

        Returns an empty dict if no rows exist yet (first-run scenario).
        """
        async with self._session_factory() as session:
            result = await session.exec(select(PluginState))
            rows: list[PluginState] = list(result.all())
        return {row.plugin_name: row.enabled for row in rows}

    async def set(self, plugin_name: str, enabled: bool) -> None:
        """Upsert the enabled state for *plugin_name*.

        Args:
            plugin_name: Plugin identifier (e.g. ``'web_search'``).
            enabled: ``True`` to enable, ``False`` to disable.
        """
        async with self._session_factory() as session:
            existing: PluginState | None = await session.get(
                PluginState, plugin_name
            )
            if existing is None:
                session.add(
                    PluginState(
                        plugin_name=plugin_name,
                        enabled=enabled,
                        updated_at=_utcnow(),
                    )
                )
            else:
                existing.enabled = enabled
                existing.updated_at = _utcnow()
                session.add(existing)
            await session.commit()

    async def initialize_defaults(self, default_enabled: list[str]) -> None:
        """Seed the table on first run.

        For every plugin in *default_enabled* that has no row yet,
        inserts a row with ``enabled=True``.  Already-persisted rows
        are never overwritten, preserving user choices on subsequent
        restarts.

        Uses a single session/transaction to avoid TOCTOU races where
        a concurrent call could insert the same plugin name between
        the read and write, causing a primary-key conflict.

        Args:
            default_enabled: The list from ``config.plugins.enabled``
                (read from ``default.yaml``).
        """
        async with self._session_factory() as session:
            result = await session.exec(select(PluginState))
            existing_names = {row.plugin_name for row in result.all()}

            new_rows = [
                PluginState(
                    plugin_name=name,
                    enabled=True,
                    updated_at=_utcnow(),
                )
                for name in default_enabled
                if name not in existing_names
            ]
            if not new_rows:
                return

            for row in new_rows:
                session.add(row)
            await session.commit()
