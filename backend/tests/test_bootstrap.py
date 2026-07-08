"""Tests for the declarative bootstrap (Fase 5).

Covers the DELIBERATE deviation from the pre-Fase-5 lifespan: the
``try/finally`` now wraps the whole stage sequence, so a mid-startup
failure runs :func:`shutdown_services` against the partially-initialised
context instead of leaking engine/clients (the old code never reached
its ``finally`` when setup raised before ``yield``).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from backend.core import app as app_module
from backend.core.bootstrap import shutdown_services
from backend.core.config import load_config
from backend.core.context import create_context


async def test_midstartup_failure_still_runs_shutdown(monkeypatch):
    """A stage raising mid-startup must still trigger shutdown_services."""
    calls: dict[str, object] = {}

    async def boom(ctx):  # replaces stage_inference
        raise RuntimeError("boom")

    async def spy_shutdown(ctx):
        calls["ctx"] = ctx

    monkeypatch.setattr(app_module, "stage_inference", boom)
    monkeypatch.setattr(app_module, "shutdown_services", spy_shutdown)

    app = FastAPI()
    app.state._config = load_config()
    app.state._testing = True

    with pytest.raises(RuntimeError, match="boom"):
        async with app_module._lifespan(app):
            pytest.fail("lifespan must not yield when a stage raises")

    assert calls["ctx"] is not None  # partial context, not None


async def test_shutdown_services_tolerates_partial_context():
    """Every step is guarded: a barely-constructed context is a no-op."""
    ctx = create_context(load_config())
    await shutdown_services(ctx)  # must not raise


async def test_shutdown_services_tolerates_none():
    await shutdown_services(None)  # must not raise
