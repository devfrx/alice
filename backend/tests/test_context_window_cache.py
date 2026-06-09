"""Tests for the non-blocking context-window cache in LLMService."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.llm_service import LLMService


def _llm() -> LLMService:
    cfg = MagicMock()
    cfg.connect_timeout = 1.0
    cfg.timeout = 10.0
    # Avoid real network client construction details by patching after init if needed.
    svc = LLMService.__new__(LLMService)
    # Initialise only the cache fields the methods under test touch.
    svc._ctx_window_cache = None
    svc._ctx_window_expires = 0.0
    svc._ctx_window_ttl = 300.0
    svc._default_ctx_window = 32768
    svc._ctx_window_refreshing = False
    return svc


def _manager(window: int) -> MagicMock:
    mgr = MagicMock()
    mgr.list_models = AsyncMock(
        return_value={
            "models": [
                {
                    "type": "llm",
                    "loaded_instances": [{"config": {"context_length": window}}],
                }
            ],
        }
    )
    return mgr


@pytest.mark.asyncio
async def test_cached_getter_returns_default_without_blocking_then_warms():
    svc = _llm()
    mgr = _manager(8192)
    # First call: no cache yet → returns default immediately, schedules refresh.
    first = svc.get_cached_context_window(mgr)
    assert first == 32768
    # Let the scheduled background refresh run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    # Cache is now warm with the real value.
    assert svc.get_cached_context_window(mgr) == 8192


@pytest.mark.asyncio
async def test_cached_getter_never_raises_when_manager_down():
    svc = _llm()
    mgr = MagicMock()
    mgr.list_models = AsyncMock(side_effect=RuntimeError("ConnectError"))
    assert svc.get_cached_context_window(mgr) == 32768
    await asyncio.sleep(0)
    # Still returns a usable value; never propagates the error.
    assert svc.get_cached_context_window(mgr) == 32768


@pytest.mark.asyncio
async def test_invalidate_forces_refresh():
    svc = _llm()
    mgr = _manager(4096)
    await svc._refresh_context_window(mgr)
    assert svc.get_cached_context_window(mgr) == 4096
    svc.invalidate_context_window_cache()
    mgr.list_models = AsyncMock(
        return_value={
            "models": [
                {"type": "llm", "loaded_instances": [{"config": {"context_length": 16384}}]}
            ],
        }
    )
    await svc._refresh_context_window(mgr)
    assert svc.get_cached_context_window(mgr) == 16384
