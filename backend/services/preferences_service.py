"""AL\\CE — DB-backed store for the ``preferences`` config layer.

Rows in ``user_preferences`` are ``dotted.path -> JSON value``; the
store materialises them as the nested dict the LayeredConfigService
merges as the ``preferences`` layer. Writability policy lives in
``config_policy`` and is enforced by the config service, not here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import col, select

from backend.db.models import UserPreference, _utcnow


class PreferencesLayerStore:
    """Load/persist the preferences layer (dotted-path rows)."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def load(self) -> dict[str, Any]:
        """Return all rows as a nested dict (invalid JSON rows skipped).

        Rows are materialised shallowest-first so overlapping rows (a
        dict-valued row plus a deeper leaf row for the same subtree, possible
        in DBs written before ``save_paths`` pruned descendants) resolve
        deterministically: the most-specific row wins instead of whichever
        happened to come last in insertion order.
        """
        async with self._session_factory() as session:
            rows = (await session.exec(select(UserPreference))).all()
        nested: dict[str, Any] = {}
        for row in sorted(rows, key=lambda r: (r.key.count("."), r.key)):
            try:
                value = json.loads(row.value)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid preference value for '{}', skipping", row.key)
                continue
            node = nested
            parts = row.key.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
                if not isinstance(node, dict):
                    logger.warning("Preference key '{}' collides, skipping", row.key)
                    break
            else:
                node[parts[-1]] = value
        return nested

    async def save_paths(self, changes: dict[str, Any]) -> None:
        """Upsert one row per dotted path (single transaction).

        Writing a path makes it authoritative for its whole subtree: any
        descendant rows (``path.*``) are deleted in the same transaction.
        A dict-valued row (PATCH replace-subtree semantics, e.g.
        ``agent.prompts.tier_guidance``) therefore cannot leave stale deeper
        rows behind that would resurrect pruned overrides on the next load.
        """
        now = _utcnow()
        async with self._session_factory() as session:
            for path, value in changes.items():
                await session.execute(
                    sa.delete(UserPreference).where(
                        # autoescape: "_" in a dotted path is a LIKE wildcard.
                        col(UserPreference.key).startswith(
                            path + ".", autoescape=True,
                        )
                    )
                )
                await session.merge(
                    UserPreference(key=path, value=json.dumps(value), updated_at=now)
                )
            await session.commit()

    async def delete_paths(self, paths: Iterable[str]) -> int:
        """Delete the given dotted paths; returns the number removed."""
        keys = list(paths)
        if not keys:
            return 0
        async with self._session_factory() as session:
            result = await session.execute(
                sa.delete(UserPreference).where(
                    UserPreference.key.in_(keys)  # type: ignore[attr-defined]
                )
            )
            await session.commit()
        return int(result.rowcount or 0)

    async def delete_all(self) -> int:
        """Delete every preference row (reset to defaults)."""
        async with self._session_factory() as session:
            rows = (await session.exec(select(UserPreference))).all()
            count = len(rows)
            await session.execute(sa.delete(UserPreference))
            await session.commit()
        logger.info("Deleted {} persisted preferences", count)
        return count
