"""Tests for backend.core.app (FastAPI application factory)."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient

from backend.core.context import AppContext


async def test_health_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert data["version"] == "0.1.0"


async def test_app_state_has_context(app: FastAPI) -> None:
    assert hasattr(app.state, "context")
    assert isinstance(app.state.context, AppContext)


async def test_app_state_context_has_llm_service(app: FastAPI) -> None:
    assert app.state.context.llm_service is not None


async def test_app_state_context_has_db(app: FastAPI) -> None:
    assert app.state.context.db is not None


async def test_conversations_list_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/chat/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
