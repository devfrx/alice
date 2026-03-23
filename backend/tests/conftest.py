"""Shared fixtures for the AL\\CE test suite."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.app import create_app
from backend.core.config import AliceConfig, load_config
from backend.core.event_bus import EventBus


@pytest.fixture
def config() -> AliceConfig:
    """Load the real default.yaml configuration."""
    return load_config()


@pytest.fixture
def event_bus() -> EventBus:
    """Return a fresh EventBus instance."""
    return EventBus()


@pytest.fixture
async def app():
    """Create a FastAPI app with testing=True and trigger its lifespan."""
    application = create_app(testing=True)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    """Async HTTP client wired to the test application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
