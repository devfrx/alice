"""Shared fixtures for the AL\\CE test suite."""

from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock

# WS wire guard: violations raise inside the test suite (warn-only in prod).
os.environ.setdefault("ALICE_WS_STRICT_CONTRACTS", "1")

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


@pytest.fixture
def mock_embedding_client():
    """Mock EmbeddingClientProtocol returning 4-dim vectors."""
    client = AsyncMock()
    client.dimensions = 4
    client.encode = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4])
    client.encode_batch = AsyncMock(
        side_effect=lambda texts: [[0.1, 0.2, 0.3, 0.4]] * len(texts)
    )
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_qdrant_service():
    """Mock QdrantServiceProtocol."""
    service = AsyncMock()
    service.initialize = AsyncMock()
    service.close = AsyncMock()
    service.ensure_collection = AsyncMock()
    service.upsert = AsyncMock()
    service.search = AsyncMock(return_value=[])
    service.delete = AsyncMock()
    service.scroll = AsyncMock(return_value=([], None))
    service.count = AsyncMock(return_value=0)
    return service
