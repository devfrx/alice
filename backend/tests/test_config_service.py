"""Tests for backend.services.config_service.LayeredConfigService."""

from __future__ import annotations

import pytest

from backend.services.config_service import ConfigLayer, LayeredConfigService


def test_rebuild_hydrates_secrets_from_provider(tmp_path) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "missing.yaml",
        system_path=tmp_path / "system.yaml",
        user_path=tmp_path / "user.yaml",
        secrets_provider=lambda: {"llm.openrouter_api_key": "sk-or-hydrated"},
    )
    resolved = svc.get_resolved()
    assert resolved.llm.openrouter_api_key.get_secret_value() == "sk-or-hydrated"


@pytest.mark.asyncio
async def test_rebuild_method_picks_up_new_secrets(tmp_path) -> None:
    secrets: dict[str, str] = {}
    svc = LayeredConfigService(
        defaults_path=tmp_path / "missing.yaml",
        system_path=tmp_path / "system.yaml",
        user_path=tmp_path / "user.yaml",
        secrets_provider=lambda: dict(secrets),
    )
    assert svc.get_resolved().llm.api_token.get_secret_value() == ""
    secrets["llm.api_token"] = "tok-live"
    resolved = await svc.rebuild()
    assert resolved.llm.api_token.get_secret_value() == "tok-live"


@pytest.mark.asyncio
async def test_set_many_is_atomic_on_validation_failure(tmp_path) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await svc.set_many(
            {"ui.theme": "dark", "llm.temperature": 99.0},  # il secondo è invalido
            layer=ConfigLayer.RUNTIME,
        )
    # niente commit parziale: il layer runtime è rimasto intatto
    assert svc.get_layer(ConfigLayer.RUNTIME) == {}


@pytest.mark.asyncio
async def test_set_many_emits_one_event_per_path(tmp_path) -> None:
    from backend.core.event_bus import EventBus

    bus = EventBus()
    events: list[dict] = []

    async def _capture(**kwargs) -> None:
        events.append(kwargs)

    bus.subscribe("config.changed", _capture)
    svc = LayeredConfigService(
        event_bus=bus,
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    await svc.set_many(
        {"ui.theme": "dark", "ui.language": "en"}, layer=ConfigLayer.RUNTIME,
    )
    paths = {e["path"] for e in events}
    assert paths == {"ui.theme", "ui.language"}


@pytest.mark.asyncio
async def test_set_many_empty_changes_is_noop(tmp_path) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    resolved = await svc.set_many({}, layer=ConfigLayer.RUNTIME)
    assert resolved is svc.get_resolved()
    assert svc.get_layer(ConfigLayer.RUNTIME) == {}


@pytest.mark.asyncio
async def test_set_delegates_to_set_many(tmp_path) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    resolved = await svc.set("ui.theme", "dark", layer=ConfigLayer.RUNTIME)
    assert resolved.ui.theme == "dark"
    assert svc.get_layer(ConfigLayer.RUNTIME) == {"ui": {"theme": "dark"}}
