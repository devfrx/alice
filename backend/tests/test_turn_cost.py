"""AL\\CE — Cost accounting through the turn pipeline."""

from __future__ import annotations

import pytest

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
