"""AL\\CE — Secret storage backed by the OS keyring.

Secrets NEVER live in config layers (YAML/DB): they are written to the
Windows Credential Manager (service ``alice``, credential name = dotted
config path, e.g. ``llm.openrouter_api_key``) and hydrated into the
resolved config from an in-memory cache (see LayeredConfigService).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from loguru import logger

from backend.core.protocols import SecretStoreProtocol
from backend.services.config_policy import SECRET_PATHS

_SERVICE_NAME = "alice"


class InMemorySecretStore:
    """Volatile secret store for tests and keyring-less fallback."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(initial or {})

    async def get(self, name: str) -> str | None:
        return self._data.get(name)

    async def set(self, name: str, value: str) -> None:
        self._data[name] = value

    async def delete(self, name: str) -> None:
        self._data.pop(name, None)

    async def load_cache(self) -> dict[str, str]:
        return dict(self._data)

    def cached(self) -> dict[str, str]:
        return dict(self._data)


class KeyringSecretStore:
    """Keyring-backed store with a synchronous read cache.

    The cache is loaded once at bootstrap (``load_cache``) and kept in
    sync on every ``set``/``delete`` — reads never hit the keyring on
    the hot path (config rebuild is synchronous).
    """

    def __init__(self, keyring_module: Any | None = None) -> None:
        resolved: Any = keyring_module
        if resolved is None:
            import keyring as _keyring  # noqa: PLC0415 — optional dep

            if os.name == "nt":
                # Pin the backend explicitly: entry_points discovery is
                # fragile under PyInstaller.
                from keyring.backends.Windows import WinVaultKeyring

                _keyring.set_keyring(WinVaultKeyring())  # type: ignore[no-untyped-call]  # keyring stub gap
            resolved = _keyring
        self._keyring: Any = resolved
        self._cache: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self._cache.get(name)

    async def set(self, name: str, value: str) -> None:
        await asyncio.to_thread(
            self._keyring.set_password, _SERVICE_NAME, name, value,
        )
        self._cache[name] = value

    async def delete(self, name: str) -> None:
        try:
            await asyncio.to_thread(
                self._keyring.delete_password, _SERVICE_NAME, name,
            )
        except Exception as exc:  # noqa: BLE001 — missing credential is fine
            logger.debug("Keyring delete for '{}' raised: {}", name, exc)
        self._cache.pop(name, None)

    async def load_cache(self) -> dict[str, str]:
        cache: dict[str, str] = {}
        for path in sorted(SECRET_PATHS):
            value = await asyncio.to_thread(
                self._keyring.get_password, _SERVICE_NAME, path,
            )
            if value:
                cache[path] = value
        self._cache = cache
        return dict(cache)

    def cached(self) -> dict[str, str]:
        return dict(self._cache)


def create_secret_store(prefer_memory: bool = False) -> SecretStoreProtocol:
    """Build the production store, falling back to in-memory.

    Args:
        prefer_memory: Force the volatile backend (test lifespans).
    """
    if prefer_memory:
        return InMemorySecretStore()
    try:
        return KeyringSecretStore()
    except Exception as exc:  # noqa: BLE001 — keyring missing/broken
        logger.warning(
            "Keyring unavailable ({}) — secrets will NOT survive restarts",
            exc,
        )
        return InMemorySecretStore()
