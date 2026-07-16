"""Tests for the SecretStore backends."""

from __future__ import annotations

import pytest

from backend.services.secret_store import (
    InMemorySecretStore,
    KeyringSecretStore,
    create_secret_store,
)


@pytest.mark.asyncio
async def test_inmemory_roundtrip() -> None:
    store = InMemorySecretStore()
    assert await store.get("llm.openrouter_api_key") is None
    await store.set("llm.openrouter_api_key", "sk-or-abc")
    assert await store.get("llm.openrouter_api_key") == "sk-or-abc"
    assert store.cached() == {"llm.openrouter_api_key": "sk-or-abc"}
    await store.delete("llm.openrouter_api_key")
    assert await store.get("llm.openrouter_api_key") is None
    assert store.cached() == {}


@pytest.mark.asyncio
async def test_inmemory_load_cache_returns_copy() -> None:
    store = InMemorySecretStore({"email.password": "pw"})
    cache = await store.load_cache()
    assert cache == {"email.password": "pw"}
    cache["email.password"] = "tampered"
    assert store.cached() == {"email.password": "pw"}


@pytest.mark.asyncio
async def test_keyring_store_uses_service_alice(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, tuple[str, ...]] = {}

    class FakeKeyring:
        @staticmethod
        def get_password(service: str, name: str) -> str | None:
            calls["get"] = (service, name)
            return "stored-value"

        @staticmethod
        def set_password(service: str, name: str, value: str) -> None:
            calls["set"] = (service, name, value)

        @staticmethod
        def delete_password(service: str, name: str) -> None:
            calls["delete"] = (service, name)

    store = KeyringSecretStore(keyring_module=FakeKeyring())
    await store.set("mqtt.password", "hunter2")
    assert calls["set"] == ("alice", "mqtt.password", "hunter2")
    assert store.cached()["mqtt.password"] == "hunter2"
    await store.delete("mqtt.password")
    assert calls["delete"] == ("alice", "mqtt.password")
    assert "mqtt.password" not in store.cached()


@pytest.mark.asyncio
async def test_keyring_load_cache_scans_secret_paths() -> None:
    class FakeKeyring:
        @staticmethod
        def get_password(service: str, name: str) -> str | None:
            return "tok" if name == "llm.api_token" else None

    store = KeyringSecretStore(keyring_module=FakeKeyring())
    cache = await store.load_cache()
    assert cache == {"llm.api_token": "tok"}


def test_factory_prefer_memory() -> None:
    store = create_secret_store(prefer_memory=True)
    assert isinstance(store, InMemorySecretStore)
