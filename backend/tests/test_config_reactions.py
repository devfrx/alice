"""Tests for the declarative config-change reaction registry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.config_reactions import REACTIONS, apply_reactions


def _reaction_names() -> set[str]:
    return {handler.__name__ for _, handler in REACTIONS}


def test_registry_covers_the_known_reactive_paths() -> None:
    assert {
        "_react_stt", "_react_tts", "_react_email", "_react_llm_rebuild",
        "_react_model_cache", "_react_openrouter_model", "_react_system_prompt",
    } <= _reaction_names()


@pytest.mark.asyncio
async def test_llm_rebuild_fires_on_provider_change() -> None:
    ctx = MagicMock()
    ctx.llm_service = MagicMock()
    rebuild = AsyncMock()
    # monkeypatch del modulo: la reazione delega a _apply_llm_provider_change
    import backend.api.routes.config_reactions as cr
    original = cr._apply_llm_provider_change
    cr._apply_llm_provider_change = rebuild
    try:
        await apply_reactions(ctx, {"llm.provider"})
    finally:
        cr._apply_llm_provider_change = original
    rebuild.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_reaction_on_unrelated_paths() -> None:
    ctx = MagicMock()
    ctx.llm_service = MagicMock()
    await apply_reactions(ctx, {"ui.theme", "voice.wake_word"})
    ctx.llm_service.invalidate_model_cache.assert_not_called()


@pytest.mark.asyncio
async def test_model_change_invalidates_cache() -> None:
    ctx = MagicMock()
    ctx.llm_service = MagicMock()
    await apply_reactions(ctx, {"llm.model"})
    ctx.llm_service.invalidate_model_cache.assert_called_once()
