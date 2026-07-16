"""Tests for backend.services.config_service.LayeredConfigService."""

from __future__ import annotations

import pytest

from backend.services.config_service import LayeredConfigService


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
