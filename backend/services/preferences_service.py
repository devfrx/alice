"""AL\\CE — User preferences persistence service."""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from backend.core.config import AliceConfig
from backend.db.models import UserPreference, _utcnow


# Sections whose settings are user preferences (persist across restarts).
PERSISTABLE_SECTIONS: frozenset[str] = frozenset({
    "tts", "stt", "voice", "ui", "plugins",
    "pc_automation", "web_search", "calendar", "weather",
    "clipboard", "notifications", "media_control", "file_search", "news",
})

# Within the 'llm' section, only these keys are user preferences.
PERSISTABLE_LLM_KEYS: frozenset[str] = frozenset({
    "system_prompt_enabled",
    "tools_enabled",
    "max_tool_iterations",
})


class PreferencesService:
    """Manages user preference persistence in the database."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def load_all(self) -> dict[str, Any]:
        """Load all stored preferences as a nested dict."""
        async with self._session_factory() as session:
            result = await session.exec(select(UserPreference))
            prefs = result.all()

        nested: dict[str, Any] = {}
        for pref in prefs:
            try:
                value = json.loads(pref.value)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Invalid preference value for key '{}', skipping",
                    pref.key,
                )
                continue

            parts = pref.key.split(".", 1)
            if len(parts) == 2:
                section, key = parts
                if section not in nested:
                    nested[section] = {}
                nested[section][key] = value
            else:
                nested[pref.key] = value

        return nested

    async def save_preference(self, key: str, value: Any) -> None:
        """Save a single preference."""
        async with self._session_factory() as session:
            existing = await session.get(UserPreference, key)
            if existing:
                existing.value = json.dumps(value)
                existing.updated_at = _utcnow()
                session.add(existing)
            else:
                pref = UserPreference(
                    key=key, value=json.dumps(value),
                )
                session.add(pref)
            await session.commit()

    async def save_section(self, section: str, data: dict[str, Any]) -> None:
        """Persist all keys in a section."""
        for key, value in data.items():
            await self.save_preference(f"{section}.{key}", value)

    async def persist_from_update(self, body: dict[str, Any]) -> None:
        """Extract persistable preferences from an update body and save them.

        Called after PUT /config to persist only the independent settings.
        """
        for section, updates in body.items():
            if not isinstance(updates, dict):
                continue

            if section in PERSISTABLE_SECTIONS:
                await self.save_section(section, updates)
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

    async def delete_all(self) -> int:
        """Delete all persisted preferences (reset to defaults)."""
        async with self._session_factory() as session:
            result = await session.exec(select(UserPreference))
            prefs = result.all()
            count = len(prefs)
            for pref in prefs:
                await session.delete(pref)
            await session.commit()
        logger.info("Deleted {} persisted preferences", count)
        return count
