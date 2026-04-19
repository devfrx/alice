"""SINGLE_TOOL strategy of :class:`AgentTurnExecutor`.

Verifies:
    * the executor delegates to :class:`DirectTurnExecutor` exactly once,
    * an :class:`AgentRun` row is persisted with ``state="done"``,
    * ``agent.run_started`` and ``agent.run_finished`` events are
      emitted (no ``agent.plan_created`` because the planner is skipped).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from sqlmodel import select

from backend.db.database import create_engine_and_session, init_db
from backend.db.models import AgentRun, Conversation, Message
from backend.services.agent.models import TaskComplexity
from backend.services.turn.models import TurnResult
from backend.services.turn.sink import RecordingEventSink

from ._agent_helpers import (
    MockDirect,
    build_executor,
    make_agent_cfg,
    make_agent_turn,
)


async def _seed_conv_and_user_msg(session_factory):
    conv = Conversation(title="agent run test")
    async with session_factory() as session:
        session.add(conv)
        await session.commit()
    user_msg = Message(
        conversation_id=conv.id, role="user", content="single tool task"
    )
    async with session_factory() as session:
        session.add(user_msg)
        await session.commit()
    return conv, user_msg


@pytest.mark.asyncio
async def test_single_tool_creates_run_and_delegates() -> None:
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
    await init_db(engine)
    conv, user_msg = await _seed_conv_and_user_msg(session_factory)

    direct = MockDirect(
        default=TurnResult(
            content="risposta tool",
            thinking="",
            input_tokens=20,
            output_tokens=5,
            finish_reason="stop",
            had_tool_calls=True,
        )
    )
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.SINGLE_TOOL,
        cfg=make_agent_cfg(save_runs=True),
    )
    sink = RecordingEventSink()

    async with session_factory() as session:
        turn = make_agent_turn()
        # Use the seeded ids so the FK constraint is satisfied.
        turn = replace(turn, conv_id=conv.id, user_msg_id=user_msg.id)
        result = await executor.execute(
            turn=turn,
            sink=sink,
            cancel_event=asyncio.Event(),
            session=session,
        )
        await session.commit()

    assert len(direct.calls) == 1
    assert result.content == "risposta tool"
    assert result.agent_run_id is not None

    types = [e["type"] for e in sink.events]
    assert types[0] == "agent.run_started"
    assert types[-1] == "agent.run_finished"
    assert "agent.plan_created" not in types

    async with session_factory() as session:
        rows = (await session.exec(select(AgentRun))).all()
        assert len(rows) == 1
        run = rows[0]
        assert run.state == "done"
        assert run.complexity == TaskComplexity.SINGLE_TOOL.value
        assert run.total_tokens_in == 20
        assert run.total_tokens_out == 5
        assert run.total_tool_calls == 1
        assert run.finished_at is not None


@pytest.mark.asyncio
async def test_single_tool_without_persistence_keeps_running() -> None:
    """``save_runs=False`` skips DB writes but still emits run events."""
    direct = MockDirect(
        default=TurnResult(
            content="ok",
            thinking="",
            input_tokens=0,
            output_tokens=0,
            finish_reason="stop",
            had_tool_calls=True,
        )
    )
    executor = build_executor(
        direct=direct,
        complexity=TaskComplexity.SINGLE_TOOL,
        cfg=make_agent_cfg(save_runs=False),
    )
    sink = RecordingEventSink()

    result = await executor.execute(
        turn=make_agent_turn(),
        sink=sink,
        cancel_event=asyncio.Event(),
        session=None,
    )

    assert result.agent_run_id is None
    types = [e["type"] for e in sink.events]
    assert "agent.run_started" in types
    assert "agent.run_finished" in types
