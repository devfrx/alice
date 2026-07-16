"""Tests for the preferences layer store + LayeredConfigService integration."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.db.models import UserPreference
from backend.services.config_service import ConfigLayer, LayeredConfigService
from backend.services.preferences_service import PreferencesLayerStore


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, class_=SQLModelAsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_store_load_builds_nested_dict(session_factory) -> None:
    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"llm.provider": "openrouter", "ui.theme": "dark"})
    loaded = await store.load()
    assert loaded == {"llm": {"provider": "openrouter"}, "ui": {"theme": "dark"}}


@pytest.mark.asyncio
async def test_store_save_paths_upserts(session_factory) -> None:
    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"ui.theme": "dark"})
    await store.save_paths({"ui.theme": "light"})
    async with session_factory() as session:
        rows = (await session.exec(select(UserPreference))).all()
    assert len(rows) == 1
    assert json.loads(rows[0].value) == "light"


@pytest.mark.asyncio
async def test_preferences_layer_wins_over_user_yaml(
    session_factory, tmp_path,
) -> None:
    import yaml
    user_yaml = tmp_path / "u.yaml"
    user_yaml.write_text(yaml.safe_dump({"ui": {"theme": "light"}}), encoding="utf-8")
    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"ui.theme": "dark"})
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=user_yaml,
    )
    resolved = await svc.load_preferences_layer(store)
    assert resolved.ui.theme == "dark"          # preferences > user
    assert svc.get_layer(ConfigLayer.PREFERENCES) == {"ui": {"theme": "dark"}}


@pytest.mark.asyncio
async def test_set_on_preferences_layer_persists_to_db(
    session_factory, tmp_path,
) -> None:
    store = PreferencesLayerStore(session_factory)
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    await svc.load_preferences_layer(store)
    await svc.set("ui.theme", "dark", layer=ConfigLayer.PREFERENCES)
    assert (await store.load()) == {"ui": {"theme": "dark"}}
    # e il reload da disco NON perde il layer preferences
    svc.reload()
    assert svc.get_resolved().ui.theme == "dark"


@pytest.mark.asyncio
async def test_secret_paths_rejected_on_every_layer(
    session_factory, tmp_path,
) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    for layer in (ConfigLayer.USER, ConfigLayer.PREFERENCES, ConfigLayer.RUNTIME):
        with pytest.raises(ValueError, match="secret"):
            await svc.set("llm.openrouter_api_key", "sk-nope", layer=layer)


@pytest.mark.asyncio
async def test_out_of_policy_path_rejected_on_preferences(
    session_factory, tmp_path,
) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    with pytest.raises(ValueError, match="policy"):
        await svc.set("server.port", 9999, layer=ConfigLayer.PREFERENCES)
    # ...ma sul layer user resta legittimo (power-user via PATCH)
    await svc.set("server.port", 9999, layer=ConfigLayer.USER)
