"""Tests for the Fase 8 headless-turn seam (autonomous turns)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from ._turn_helpers import StreamingMockLLM, make_ctx


def test_headless_channel_satisfies_protocol() -> None:
    from backend.services.turn.channel import (
        HeadlessInteractionChannel,
        InteractionChannel,
    )

    channel = HeadlessInteractionChannel()
    assert isinstance(channel, InteractionChannel)
    assert channel.connected is True
    assert channel.cancelled is False


@pytest.mark.asyncio
async def test_headless_channel_request_returns_none() -> None:
    from backend.services.turn.channel import HeadlessInteractionChannel

    channel = HeadlessInteractionChannel()
    answer = await channel.request(
        "tool_confirmation", {"tool": "x"}, execution_id="e1", timeout_s=1.0,
    )
    assert answer is None


@pytest.mark.asyncio
async def test_null_sink_satisfies_protocol_and_drops() -> None:
    from backend.services.turn.sink import NullEventSink, WSEventSink

    sink = NullEventSink()
    assert isinstance(sink, WSEventSink)
    assert sink.is_connected is True
    await sink.send({"type": "token", "content": "x"})  # must not raise


class _AssemblingMockLLM(StreamingMockLLM):
    """StreamingMockLLM extended with the prompt-building surface.

    ``TurnAssembler`` (unlike the bare executor) also calls
    ``get_system_prompt`` and ``build_messages`` on the LLM service.
    """

    def get_system_prompt(
        self,
        memory_context: str | None = None,
        *,
        persona: str | None = None,
    ) -> str:
        return "You are a test assistant."

    def build_messages(
        self,
        user_content: str,
        history: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, str]] | None = None,
        memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(history or [])
        messages.append({"role": "user", "content": user_content})
        return messages


@pytest.mark.asyncio
async def test_run_headless_turn_persists_a_normal_turn() -> None:
    """An autonomous turn is a normal turn: user+assistant rows persisted."""
    from sqlmodel import select

    from backend.api.routes.chat.headless import run_headless_turn
    from backend.db.models import Message

    ctx = make_ctx()
    ctx.llm_service = _AssemblingMockLLM(
        events=[
            {"type": "token", "content": "Autonomous hello"},
            {"type": "done", "finish_reason": "stop"},
        ],
    )
    # Assembler-required services beyond the executor-only ``make_ctx``:
    # minimal stubs so every optional integration path is cleanly skipped.
    ctx.tool_registry = None
    ctx.knowledge_service = None
    ctx.plan_document_service = None
    ctx.plan_service = None
    ctx.context_manager = None
    ctx.config.llm.tools_enabled = False
    ctx.config.llm.max_tokens = 1024
    ctx.config.mcp = SimpleNamespace(servers=[])
    ctx.config.agent = SimpleNamespace(
        engine="v1",
        prompts=SimpleNamespace(persona=None),
        reflection=SimpleNamespace(enabled=False),
    )

    # StaticPool keeps the single in-memory DB shared across connections.
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    ctx.db = async_sessionmaker(
        engine, class_=SQLModelAsyncSession, expire_on_commit=False,
    )

    result = await run_headless_turn(
        ctx, conversation_id=None, prompt="Daily briefing please",
    )

    assert result is not None
    assert result.finish_reason != "error"
    async with ctx.db() as session:
        rows = (await session.exec(select(Message))).all()
    roles = [r.role for r in rows]
    assert "user" in roles
    assert "assistant" in roles
    await engine.dispose()
