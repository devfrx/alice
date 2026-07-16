"""AL\\CE — Cost accounting through the turn pipeline."""

from __future__ import annotations

import pytest
from sqlmodel import select

from backend.db.database import create_engine_and_session, init_db
from backend.db.models import Conversation, Message
from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.models import TurnProgress, TurnResult


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.is_connected = True

    async def send(self, event: dict) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_finish_stamps_cost_on_result_and_frame() -> None:
    executor = DirectTurnExecutor.__new__(DirectTurnExecutor)
    sink = _RecordingSink()
    progress = TurnProgress(turn_id="t1", steps=2, cost=0.0015)
    result = TurnResult(
        content="ok", thinking="", input_tokens=10, output_tokens=5,
        finish_reason="stop",
    )

    out = await executor._finish(sink, progress, result)

    assert out.cost == pytest.approx(0.0015)
    finished = [e for e in sink.events if e["type"] == "turn.finished"]
    assert finished and finished[0]["cost"] == pytest.approx(0.0015)


@pytest.mark.asyncio
async def test_finish_omits_cost_when_zero() -> None:
    executor = DirectTurnExecutor.__new__(DirectTurnExecutor)
    sink = _RecordingSink()
    progress = TurnProgress(turn_id="t1", steps=1)
    result = TurnResult(
        content="ok", thinking="", input_tokens=10, output_tokens=5,
        finish_reason="stop",
    )

    out = await executor._finish(sink, progress, result)

    assert out.cost == 0.0
    finished = [e for e in sink.events if e["type"] == "turn.finished"]
    assert finished and finished[0]["cost"] is None


@pytest.mark.asyncio
async def test_finish_suppresses_frame_cost_on_error() -> None:
    """Error turns roll back in ``_persist_final_turn``: the frame must not
    carry a cost the persisted ledger won't back (live chip would diverge
    on reload). The returned result keeps the real accumulated cost."""
    executor = DirectTurnExecutor.__new__(DirectTurnExecutor)
    sink = _RecordingSink()
    progress = TurnProgress(turn_id="t1", steps=2, cost=0.0015)
    result = TurnResult(
        content="", thinking="", input_tokens=10, output_tokens=5,
        finish_reason="error",
    )

    out = await executor._finish(sink, progress, result)

    assert out.cost == pytest.approx(0.0015)
    finished = [e for e in sink.events if e["type"] == "turn.finished"]
    assert finished and finished[0]["cost"] is None


@pytest.mark.asyncio
async def test_finish_keeps_frame_cost_on_cancelled() -> None:
    """Cancelled turns with content DO persist their cost — the frame must
    keep carrying it (only the error/rollback class is suppressed)."""
    executor = DirectTurnExecutor.__new__(DirectTurnExecutor)
    sink = _RecordingSink()
    progress = TurnProgress(turn_id="t1", steps=1, cost=0.002)
    result = TurnResult(
        content="partial", thinking="", input_tokens=10, output_tokens=5,
        finish_reason="cancelled",
    )

    out = await executor._finish(sink, progress, result)

    assert out.cost == pytest.approx(0.002)
    finished = [e for e in sink.events if e["type"] == "turn.finished"]
    assert finished and finished[0]["cost"] == pytest.approx(0.002)


def test_sum_usage_cost_ignores_malformed_entries() -> None:
    from backend.api.routes.chat.conversations import _sum_usage_cost

    class _Msg:
        def __init__(self, usage) -> None:
            self.usage = usage

    msgs = [
        _Msg({"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001}),
        _Msg({"cost": "0.002"}),      # stringa valida
        _Msg({"cost": "n/a"}),        # malformata → ignorata
        _Msg(None),                    # nessuna usage
        _Msg({"prompt_tokens": 3}),    # senza cost
    ]
    assert _sum_usage_cost(msgs) == pytest.approx(0.003)


def test_message_model_has_usage_column() -> None:
    from backend.db.models import Message

    msg = Message(conversation_id=__import__("uuid").uuid4(), role="assistant")
    assert msg.usage is None
    msg.usage = {"prompt_tokens": 1, "completion_tokens": 2, "cost": 0.5}
    assert msg.usage["cost"] == 0.5


async def test_usage_round_trips_through_db_and_sums() -> None:
    """Message.usage survives a real commit/read-back on SQLite.

    Covers the migration path (``init_db`` runs the ``ALTER TABLE`` that
    adds the ``usage`` column) and the on-read cost aggregation used by
    the conversations route.
    """
    from backend.api.routes.chat.conversations import _sum_usage_cost

    engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
    await init_db(engine)

    conv = Conversation(title="Cost round-trip")
    async with session_factory() as session:
        session.add(conv)
        await session.commit()

    msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content="ok",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    )
    async with session_factory() as session:
        session.add(msg)
        await session.commit()

    async with session_factory() as session:
        result = await session.exec(
            select(Message).where(Message.conversation_id == conv.id)
        )
        loaded = result.one()
        assert loaded.usage == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "cost": 0.001,
        }
        assert _sum_usage_cost([loaded]) == pytest.approx(0.001)

    await engine.dispose()
