"""Tests for the all-or-nothing RAG readiness gate."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.rag_readiness import RagReadiness, check_rag_readiness


def _ctx(*, in_memory=False, embed_ok=True, mem_dim=1024, tool_count=3):
    ctx = MagicMock()
    ctx.config.llm.tool_rag_enabled = True
    qd = MagicMock()
    qd.in_memory = in_memory
    qd.try_clear_stale_lock = MagicMock(return_value=False)
    qd.reinitialize = AsyncMock()
    qd.get_collection_dim = AsyncMock(return_value=mem_dim)
    qd.count = AsyncMock(return_value=tool_count)
    ctx.qdrant_service = qd
    emb = MagicMock()
    emb.dimensions = 1024
    emb.encode = AsyncMock(
        return_value=[0.0] * 1024 if embed_ok else None,
        side_effect=None if embed_ok else RuntimeError("no embed"),
    )
    ctx.embedding_client = emb
    ctx.memory_service = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_ready_when_all_checks_pass():
    res = await check_rag_readiness(_ctx())
    assert isinstance(res, RagReadiness)
    assert res.ready is True
    assert res.memory_enabled is True
    assert res.tool_rag_enabled is True


@pytest.mark.asyncio
async def test_not_ready_when_in_memory_and_repair_fails():
    ctx = _ctx(in_memory=True)
    res = await check_rag_readiness(ctx)
    assert res.ready is False
    assert "in-memory" in res.reason.lower()
    ctx.qdrant_service.try_clear_stale_lock.assert_called_once()


@pytest.mark.asyncio
async def test_not_ready_when_embedding_roundtrip_fails():
    res = await check_rag_readiness(_ctx(embed_ok=False))
    assert res.ready is False
    assert "embed" in res.reason.lower()


@pytest.mark.asyncio
async def test_repair_recovers_in_memory():
    ctx = _ctx(in_memory=True)
    ctx.qdrant_service.try_clear_stale_lock = MagicMock(return_value=True)

    async def _reinit():
        ctx.qdrant_service.in_memory = False
    ctx.qdrant_service.reinitialize = AsyncMock(side_effect=_reinit)

    res = await check_rag_readiness(ctx)
    assert res.ready is True
