"""Tests for the :class:`AgentRun` SQLModel.

Covers default values and a round-trip through an in-memory SQLite database
to ensure the table is created and the FKs resolve.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlmodel import select

from backend.db.database import create_engine_and_session, init_db
from backend.db.models import AgentRun, Conversation, Message


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_agent_run_defaults() -> None:
    run = AgentRun(
        conversation_id=uuid.uuid4(),
        user_message_id=uuid.uuid4(),
    )
    assert isinstance(run.id, uuid.UUID)
    assert run.final_assistant_message_id is None
    assert run.goal == ""
    assert run.complexity == ""
    assert run.plan_json == "[]"
    assert run.state == "planning"
    assert run.current_step == 0
    assert run.total_steps == 0
    assert run.replans == 0
    assert run.retries_total == 0
    assert run.total_tokens_in == 0
    assert run.total_tokens_out == 0
    assert run.total_tool_calls == 0
    assert isinstance(run.started_at, datetime)
    assert run.started_at.tzinfo is not None
    assert run.finished_at is None
    assert run.error is None


# ---------------------------------------------------------------------------
# DB round-trip
# ---------------------------------------------------------------------------


async def test_agent_run_roundtrip() -> None:
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
    await init_db(engine)

    conv = Conversation(title="Agent run test")
    async with session_factory() as session:
        session.add(conv)
        await session.commit()

    user_msg = Message(
        conversation_id=conv.id, role="user", content="do the thing",
    )
    async with session_factory() as session:
        session.add(user_msg)
        await session.commit()

    run = AgentRun(
        conversation_id=conv.id,
        user_message_id=user_msg.id,
        goal="do the thing",
        complexity="medium",
        plan_json=json.dumps([{"id": 1, "action": "noop"}]),
        state="running",
        current_step=1,
        total_steps=3,
        total_tokens_in=42,
        total_tokens_out=17,
        total_tool_calls=2,
    )
    async with session_factory() as session:
        session.add(run)
        await session.commit()

    async with session_factory() as session:
        result = await session.exec(select(AgentRun))
        rows = result.all()
        assert len(rows) == 1
        loaded = rows[0]
        assert loaded.id == run.id
        assert loaded.conversation_id == conv.id
        assert loaded.user_message_id == user_msg.id
        assert loaded.goal == "do the thing"
        assert loaded.complexity == "medium"
        assert json.loads(loaded.plan_json) == [{"id": 1, "action": "noop"}]
        assert loaded.state == "running"
        assert loaded.current_step == 1
        assert loaded.total_steps == 3
        assert loaded.total_tokens_in == 42
        assert loaded.total_tokens_out == 17
        assert loaded.total_tool_calls == 2

    await engine.dispose()
