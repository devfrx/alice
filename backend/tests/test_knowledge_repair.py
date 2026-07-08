"""Tests for repair_vector_store — atomic Knowledge group swap (Fase 5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.config import load_config
from backend.core.context import create_context
from backend.services import knowledge_init
from backend.services.rag_readiness import RagReadiness


@pytest.fixture
def ctx(monkeypatch):
    ctx = create_context(load_config())
    ctx.embedding_client = MagicMock()
    ctx.tool_registry = None

    qdrant = MagicMock()
    qdrant.initialize = AsyncMock()
    qdrant.close = AsyncMock()
    qdrant.clear_embedded_data = MagicMock()
    monkeypatch.setattr(
        knowledge_init, "QdrantService", MagicMock(return_value=qdrant),
    )

    # config.memory.enabled is True in the default config (YAML wins), so
    # repair takes the memory-init branch. MemoryService is imported lazily
    # inside repair_vector_store; patch the source attribute so the deferred
    # `from ... import MemoryService` picks up the mock instead of building
    # a real service against the mocked Qdrant client.
    memory_instance = MagicMock()
    memory_instance.initialize = AsyncMock()
    memory_instance.close = AsyncMock()
    monkeypatch.setattr(
        "backend.services.memory_service.MemoryService",
        MagicMock(return_value=memory_instance),
    )

    readiness = RagReadiness(
        ready=False, reason="test", memory_enabled=False,
        tool_rag_enabled=False,
    )
    monkeypatch.setattr(
        knowledge_init, "check_rag_readiness",
        AsyncMock(return_value=readiness),
    )
    return ctx


async def test_repair_swaps_knowledge_group_atomically(ctx):
    old_group = ctx.knowledge
    await knowledge_init.repair_vector_store(ctx)
    assert ctx.knowledge is not old_group
    # EVERY field of the OLD group is untouched (a fresh group is all-None):
    # a regression to even ONE in-place flat write would mutate it and
    # reopen the partial-state window this task closes.
    assert old_group.qdrant_service is None
    assert old_group.memory_service is None
    assert old_group.knowledge_service is None
    assert old_group.continuum_client is None
    assert old_group.rag_readiness is None
    # The new group is fully wired.
    assert ctx.qdrant_service is not None
    assert ctx.knowledge_service is not None
    assert ctx.rag_readiness is not None


async def test_repair_reuses_shared_continuum_client(ctx):
    sentinel = MagicMock()
    ctx.continuum_client = sentinel
    await knowledge_init.repair_vector_store(ctx)
    assert ctx.continuum_client is sentinel


async def test_repair_memory_failure_keeps_qdrant(ctx, monkeypatch):
    """Memory init failing with healthy Qdrant: qdrant present, memory None."""
    failing_memory = MagicMock()
    failing_memory.initialize = AsyncMock(side_effect=RuntimeError("boom"))
    failing_memory.close = AsyncMock()
    monkeypatch.setattr(
        "backend.services.memory_service.MemoryService",
        MagicMock(return_value=failing_memory),
    )
    await knowledge_init.repair_vector_store(ctx)
    assert ctx.qdrant_service is not None
    assert ctx.memory_service is None
    assert ctx.knowledge_service is not None
    failing_memory.close.assert_awaited_once()


async def test_repair_repoints_tool_rag_at_new_backends(ctx):
    """Step 4 must hand the NEW qdrant/embedding to the tool registry."""
    registry = MagicMock()
    registry.set_vector_backends = MagicMock()
    registry.clear_status_cache = MagicMock()
    registry.refresh = AsyncMock()
    ctx.tool_registry = registry
    await knowledge_init.repair_vector_store(ctx)
    registry.set_vector_backends.assert_called_once_with(
        ctx.qdrant_service, ctx.embedding_client,
    )
    registry.clear_status_cache.assert_called_once()
    registry.refresh.assert_awaited_once()


async def test_repair_qdrant_failure_leaves_memory_disabled(ctx, monkeypatch):
    failing = MagicMock()
    failing.initialize = AsyncMock(side_effect=RuntimeError("boom"))
    failing.close = AsyncMock()
    failing.clear_embedded_data = MagicMock()
    monkeypatch.setattr(
        knowledge_init, "QdrantService", MagicMock(return_value=failing),
    )
    await knowledge_init.repair_vector_store(ctx)
    assert ctx.qdrant_service is None
    assert ctx.memory_service is None
    assert ctx.knowledge_service is not None  # memory-unavailable facade
