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
async def test_save_dict_row_replaces_subtree(session_factory) -> None:
    """A dict-valued row (PATCH replace-subtree semantics) prunes stale leaves.

    Real flow: the FE PATCHes ``agent.prompts.tier_guidance`` with a pruned
    mapping expecting removed tiers to fall back to defaults — a leftover
    per-tier leaf row would silently resurrect the old override.
    """
    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"agent.prompts.tier_guidance.strict": "old override"})
    await store.save_paths({"agent.prompts.tier_guidance": {"plan": "new"}})
    loaded = await store.load()
    assert loaded == {"agent": {"prompts": {"tier_guidance": {"plan": "new"}}}}
    async with session_factory() as session:
        rows = (await session.exec(select(UserPreference))).all()
    assert [r.key for r in rows] == ["agent.prompts.tier_guidance"]


@pytest.mark.asyncio
async def test_save_subtree_prune_escapes_like_wildcards(session_factory) -> None:
    """``_`` in a dotted path is a LIKE wildcard — the prune must escape it.

    Without escaping, writing ``agent.a_b`` deletes the rows of the UNRELATED
    subtree ``agent.a.b.*`` (``_`` matches the dot).
    """
    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"agent.a.b.c": 1})
    await store.save_paths({"agent.a_b": 2})
    async with session_factory() as session:
        keys = {r.key for r in (await session.exec(select(UserPreference))).all()}
    assert keys == {"agent.a.b.c", "agent.a_b"}


@pytest.mark.asyncio
async def test_load_overlapping_legacy_rows_is_deterministic(
    session_factory,
) -> None:
    """Pre-prune DBs may hold a dict row AND a deeper leaf row for the same
    subtree; materialisation must be deterministic — most-specific wins —
    instead of depending on row insertion order."""
    from backend.db.models import _utcnow

    now = _utcnow()
    async with session_factory() as session:
        # Leaf row inserted FIRST: before the depth-sort in load(), the
        # dict row (inserted later) clobbered it.
        session.add(UserPreference(
            key="agent.prompts.tier_guidance.strict", value=json.dumps("leaf"),
            updated_at=now,
        ))
        session.add(UserPreference(
            key="agent.prompts.tier_guidance",
            value=json.dumps({"strict": "dict", "plan": "p"}),
            updated_at=now,
        ))
        await session.commit()

    store = PreferencesLayerStore(session_factory)
    loaded = await store.load()
    assert loaded["agent"]["prompts"]["tier_guidance"] == {
        "strict": "leaf", "plan": "p",
    }


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
async def test_fossil_row_does_not_poison_layer_or_brick_writes(
    session_factory, tmp_path,
) -> None:
    """A fossil ``agent.enabled`` row must never brick the write path.

    Reproduces the real-DB blocker: an old schema had ``AgentConfig.enabled``,
    today's ``AgentConfig`` is ``extra=forbid`` and has no such field. If the
    preferences layer committed before validation, ``AliceConfig(**merged)``
    would raise, the poisoned dict would stay committed, and every later
    ``set_many`` would re-raise forever (permanent 422). Here the layer must
    stay unmounted instead, and subsequent writes must still succeed.
    """
    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"agent": {"enabled": True}})
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )

    resolved = await svc.load_preferences_layer(store)  # must not raise

    # Resolved config is still valid (defaults) — nothing bricked.
    assert resolved.agent.planning is True
    assert not hasattr(resolved.agent, "enabled")

    # Write path must not be bricked by the poisoned layer.
    await svc.set("ui.theme", "dark", layer=ConfigLayer.PREFERENCES)
    assert svc.get_resolved().ui.theme == "dark"


@pytest.mark.asyncio
async def test_migration_then_load_mounts_only_valid_rows(
    session_factory, tmp_path,
) -> None:
    """End-to-end bootstrap order: migration prunes, then the layer mounts clean.

    Seeds the fossil ``agent.enabled`` row alongside a valid one directly in
    the DB store (bypassing policy-gated ``set``), runs
    ``run_secret_migrations`` (which prunes schema-unknown rows), then loads
    the preferences layer — mirroring what the real bootstrap does at
    startup. Only the valid row should end up mounted.
    """
    from backend.services.config_migration import run_secret_migrations
    from backend.services.secret_store import InMemorySecretStore

    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"agent.enabled": True, "ui.theme": "dark"})
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )

    await run_secret_migrations(InMemorySecretStore(), session_factory, svc, email_username="")
    resolved = await svc.load_preferences_layer(store)

    assert resolved.ui.theme == "dark"
    assert svc.get_layer(ConfigLayer.PREFERENCES) == {"ui": {"theme": "dark"}}


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
