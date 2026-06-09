"""ask_user multi-question round-trip: payload out, labeled answers back."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.services.turn.pipeline import _execute_user_interaction


@pytest.mark.asyncio
async def test_multi_question_payload_and_answer_formatting():
    channel = AsyncMock()
    channel.request = AsyncMock(return_value={
        "answers": [
            {"question_id": "q1", "selected": ["Red"], "free_text": ""},
            {"question_id": "q2", "selected": ["A", "C"], "free_text": "and D"},
        ],
    })
    args = {
        "questions": [
            {"id": "q1", "text": "Favourite colour?", "type": "radio",
             "options": ["Red", "Blue"], "allow_free_text": False},
            {"id": "q2", "text": "Pick toppings", "type": "checkbox",
             "options": ["A", "B", "C"], "allow_free_text": True},
        ],
    }
    result = await _execute_user_interaction(
        channel, "ask_user", args, execution_id="e1", timeout_s=30,
    )
    assert result.success is True
    sent = channel.request.call_args.args[1]
    assert sent["questions"][0]["id"] == "q1"
    assert sent["questions"][1]["type"] == "checkbox"
    out = result.content if hasattr(result, "content") else result.result
    assert "Favourite colour?" in out
    assert "Red" in out
    assert "and D" in out


@pytest.mark.asyncio
async def test_no_questions_fails_gracefully():
    channel = AsyncMock()
    result = await _execute_user_interaction(
        channel, "ask_user", {"questions": []}, execution_id="e2", timeout_s=30,
    )
    assert result.success is False
