"""Tests for the one-shot secret migration."""

from __future__ import annotations

import json

import pytest
import yaml
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import UserPreference
from backend.services.config_migration import run_secret_migrations
from backend.services.config_service import LayeredConfigService
from backend.services.secret_store import InMemorySecretStore


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, class_=SQLModelAsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _seed_pref(factory, key: str, value: object) -> None:
    async with factory() as session:
        session.add(UserPreference(key=key, value=json.dumps(value)))
        await session.commit()


@pytest.mark.asyncio
async def test_db_secret_row_moves_to_store_and_row_deleted(
    session_factory, tmp_path,
) -> None:
    await _seed_pref(session_factory, "llm.openrouter_api_key", "sk-or-legacy")
    await _seed_pref(session_factory, "email.use_keyring", False)
    await _seed_pref(session_factory, "ui.theme", "dark")
    store = InMemorySecretStore()
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )

    await run_secret_migrations(store, session_factory, svc, email_username="")

    assert store.cached()["llm.openrouter_api_key"] == "sk-or-legacy"
    from sqlmodel import select
    async with session_factory() as session:
        rows = (await session.exec(select(UserPreference))).all()
    keys = {r.key for r in rows}
    assert "llm.openrouter_api_key" not in keys       # migrata
    assert "email.use_keyring" not in keys            # chiave morta eliminata
    assert "ui.theme" in keys                         # preferenza valida intatta


@pytest.mark.asyncio
async def test_yaml_secret_is_stripped_and_stored(session_factory, tmp_path) -> None:
    user_yaml = tmp_path / "u.yaml"
    user_yaml.write_text(
        yaml.safe_dump({"continuum": {"api_token": "ct-legacy"}, "ui": {"theme": "dark"}}),
        encoding="utf-8",
    )
    store = InMemorySecretStore()
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=user_yaml,
    )

    await run_secret_migrations(store, session_factory, svc, email_username="")

    assert store.cached()["continuum.api_token"] == "ct-legacy"
    on_disk = yaml.safe_load(user_yaml.read_text(encoding="utf-8"))
    assert "api_token" not in on_disk.get("continuum", {})
    assert on_disk["ui"]["theme"] == "dark"


@pytest.mark.asyncio
async def test_migration_is_idempotent(session_factory, tmp_path) -> None:
    await _seed_pref(session_factory, "llm.openrouter_api_key", "sk-once")
    store = InMemorySecretStore()
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    await run_secret_migrations(store, session_factory, svc, email_username="")
    await run_secret_migrations(store, session_factory, svc, email_username="")
    assert store.cached()["llm.openrouter_api_key"] == "sk-once"


@pytest.mark.asyncio
async def test_legacy_email_keyring_credential_migrates(
    session_factory, tmp_path,
) -> None:
    class FakeKeyring:
        store = {("alice", "user@example.com"): "legacy-pw"}

        @classmethod
        def get_password(cls, service: str, name: str) -> str | None:
            return cls.store.get((service, name))

        @classmethod
        def delete_password(cls, service: str, name: str) -> None:
            cls.store.pop((service, name), None)

    store = InMemorySecretStore()
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    await run_secret_migrations(
        store, session_factory, svc,
        email_username="user@example.com", keyring_module=FakeKeyring,
    )
    assert store.cached()["email.password"] == "legacy-pw"
    assert ("alice", "user@example.com") not in FakeKeyring.store
