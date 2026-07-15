"""AL\\CE — Cost accounting through the turn pipeline."""

from __future__ import annotations

import pytest

from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.models import TurnProgress, TurnResult

pytestmark = pytest.mark.asyncio


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.is_connected = True

    async def send(self, event: dict) -> None:
        self.events.append(event)


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
