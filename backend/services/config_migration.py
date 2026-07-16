# backend/services/config_migration.py
"""AL\\CE — One-shot, idempotent migration of legacy secrets.

Moves secrets out of the preferences DB and the YAML layers into the
SecretStore, migrates the legacy email keyring credential, and deletes
dead preference rows. Every step is a no-op when there is nothing to
migrate; failures are logged and non-fatal (retried at next boot).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import UserPreference
from backend.services.config_policy import SECRET_PATHS, is_preference_writable
from backend.services.config_service import ConfigLayer, LayeredConfigService

_LEGACY_KEYRING_SERVICE = "alice"


async def run_secret_migrations(
    secret_store: Any,
    session_factory: async_sessionmaker[SQLModelAsyncSession],
    config_service: LayeredConfigService,
    email_username: str,
    keyring_module: Any | None = None,
) -> None:
    """Run all legacy-secret migrations (idempotent, non-fatal)."""
    try:
        await _migrate_db_rows(secret_store, session_factory)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Secret DB migration failed (will retry next boot): {}", exc)
    try:
        await _migrate_yaml_layers(secret_store, config_service)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Secret YAML migration failed: {}", exc)
    try:
        await _migrate_legacy_email_credential(
            secret_store, email_username, keyring_module,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Legacy email keyring migration failed: {}", exc)


async def _migrate_db_rows(
    secret_store: Any, session_factory: async_sessionmaker[SQLModelAsyncSession],
) -> None:
    """Secret rows -> store; out-of-policy rows -> deleted."""
    async with session_factory() as session:
        rows = (await session.exec(select(UserPreference))).all()
        dead_keys: list[str] = []
        for row in rows:
            if row.key in SECRET_PATHS:
                try:
                    value = json.loads(row.value)
                except (json.JSONDecodeError, TypeError):
                    value = None
                if isinstance(value, str) and value:
                    await secret_store.set(row.key, value)
                    logger.info("Migrated secret '{}' from DB to keyring", row.key)
                dead_keys.append(row.key)
            elif not is_preference_writable(row.key):
                dead_keys.append(row.key)
        if dead_keys:
            await session.execute(
                sa.delete(UserPreference).where(
                    UserPreference.key.in_(dead_keys)  # type: ignore[attr-defined]
                )
            )
            await session.commit()
            logger.info("Pruned {} legacy preference rows: {}", len(dead_keys), dead_keys)


async def _migrate_yaml_layers(
    secret_store: Any, config_service: LayeredConfigService,
) -> None:
    """Secrets found in system/user YAML -> store + file rewritten."""
    for layer in (ConfigLayer.SYSTEM, ConfigLayer.USER):
        data = config_service.get_layer(layer)
        found: dict[str, str] = {}
        for path in SECRET_PATHS:
            node: Any = data
            for part in path.split("."):
                if not isinstance(node, dict) or part not in node:
                    node = None
                    break
                node = node[part]
            if isinstance(node, str) and node:
                found[path] = node
        if not found:
            continue
        for path, value in found.items():
            await secret_store.set(path, value)
        removed = await config_service.strip_paths_from_disk_layer(
            layer, found.keys(),
        )
        logger.info("Migrated {} secrets out of {} layer: {}", len(removed), layer, removed)


async def _migrate_legacy_email_credential(
    secret_store: Any, email_username: str, keyring_module: Any | None,
) -> None:
    """Legacy ('alice', <username>) credential -> 'email.password'."""
    username = email_username.strip()
    if not username or secret_store.cached().get("email.password"):
        return
    if keyring_module is None:
        try:
            import keyring as keyring_module  # noqa: PLC0415
        except ImportError:
            return
    assert keyring_module is not None  # noqa: S101 — narrowed above, never reaches here as None
    legacy = await asyncio.to_thread(
        keyring_module.get_password, _LEGACY_KEYRING_SERVICE, username,
    )
    if not legacy:
        return
    await secret_store.set("email.password", legacy)
    await asyncio.to_thread(
        keyring_module.delete_password, _LEGACY_KEYRING_SERVICE, username,
    )
    logger.info("Migrated legacy email keyring credential for '{}'", username)
