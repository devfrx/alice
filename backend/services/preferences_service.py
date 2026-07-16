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
from sqlmodel import select

from backend.core.config import AliceConfig
from backend.db.models import UserPreference, _utcnow

# Sections whose settings are user preferences (persist across restarts).
# -- Legacy allowlists (used only by the deprecated shims below; the
#    canonical writability policy lives in ``backend.services.config_policy``).
PERSISTABLE_SECTIONS: frozenset[str] = frozenset({
    "tts", "stt", "voice", "ui", "plugins",
    "pc_automation", "web_search", "calendar", "weather",
    "clipboard", "notifications", "media_control", "file_search", "news",
    "agent", "email",
})

# Sensitive keys that must never be persisted to the preferences table.
SENSITIVE_PREFERENCE_KEYS: frozenset[str] = frozenset({
    "password",
})

# Within the 'llm' section, only these keys are user preferences.
PERSISTABLE_LLM_KEYS: frozenset[str] = frozenset({
    "system_prompt_enabled",
    "tools_enabled",
    "max_tool_iterations",
    "context_compression_enabled",
    "context_compression_threshold",
    "context_compression_reserve",
    "tool_rag_enabled",
    "tool_rag_top_k",
    "disabled_tools",
    "user_preferred_name",
    "provider",
    "openrouter_api_key",
    "openrouter_model",
    "openrouter_favorites",
})


class PreferencesLayerStore:
    """Load/persist the preferences layer (dotted-path rows)."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def load(self) -> dict[str, Any]:
        """Return all rows as a nested dict (invalid JSON rows skipped)."""
        async with self._session_factory() as session:
            rows = (await session.exec(select(UserPreference))).all()
        nested: dict[str, Any] = {}
        for row in rows:
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
        """Upsert one row per dotted path (single transaction)."""
        now = _utcnow()
        async with self._session_factory() as session:
            for path, value in changes.items():
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
            await session.execute(sa.delete(UserPreference))  # type: ignore[arg-type]
            await session.commit()
        logger.info("Deleted {} persisted preferences", count)
        return count

    # -- Legacy shims (rimossi nel Task 11 col rewiring di PUT/bootstrap) --

    async def load_all(self) -> dict[str, Any]:
        """Load all stored preferences as a nested dict (alias for ``load``)."""
        return await self.load()

    async def save_preference(self, key: str, value: Any) -> None:
        """Save a single preference (atomic upsert)."""
        async with self._session_factory() as session:
            pref = UserPreference(
                key=key, value=json.dumps(value), updated_at=_utcnow(),
            )
            await session.merge(pref)
            await session.commit()

    async def save_section(self, section: str, data: dict[str, Any]) -> None:
        """Persist all keys in a section (single transaction)."""
        now = _utcnow()
        async with self._session_factory() as session:
            for key, value in data.items():
                pref = UserPreference(
                    key=f"{section}.{key}",
                    value=json.dumps(value),
                    updated_at=now,
                )
                await session.merge(pref)
            await session.commit()

    async def persist_from_update(self, body: dict[str, Any]) -> None:
        """Extract persistable preferences from an update body and save them.

        Called after PUT /config to persist only the independent settings.
        """
        for section, updates in body.items():
            if not isinstance(updates, dict):
                continue

            if section in PERSISTABLE_SECTIONS:
                safe_updates = {
                    key: value
                    for key, value in updates.items()
                    if key not in SENSITIVE_PREFERENCE_KEYS
                }
                if safe_updates:
                    await self.save_section(section, safe_updates)
            elif section == "llm":
                for key, value in updates.items():
                    if key in PERSISTABLE_LLM_KEYS:
                        await self.save_preference(f"llm.{key}", value)

    def apply_to_config(
        self, config: AliceConfig, prefs: dict[str, Any],
    ) -> None:
        """Overlay persisted preferences onto the config object.

        Called at startup after loading YAML defaults.
        """
        for section, values in prefs.items():
            if not isinstance(values, dict):
                continue

            cfg_section = getattr(config, section, None)
            if cfg_section is None:
                continue

            if section == "llm":
                for key, value in values.items():
                    if key in PERSISTABLE_LLM_KEYS and hasattr(cfg_section, key):
                        try:
                            setattr(cfg_section, key, value)
                        except (ValueError, TypeError) as exc:
                            logger.warning(
                                "Skipping invalid preference {}.{}: {}",
                                section, key, exc,
                            )
            elif section in PERSISTABLE_SECTIONS:
                for key, value in values.items():
                    if hasattr(cfg_section, key):
                        try:
                            setattr(cfg_section, key, value)
                        except (ValueError, TypeError) as exc:
                            logger.warning(
                                "Skipping invalid preference {}.{}: {}",
                                section, key, exc,
                            )

        count = sum(
            len(v) if isinstance(v, dict) else 1
            for v in prefs.values()
        )
        if count:
            logger.info("Applied {} persisted user preferences", count)


# Legacy alias: some call-sites/imports may still reference the old name.
PreferencesService = PreferencesLayerStore
