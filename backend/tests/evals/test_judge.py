"""Test del judge LLM con servizio finto."""

from __future__ import annotations

from typing import Any

from backend.evals.judge import judge_response
from backend.evals.models import JudgeSpec


class _FakeLLM:
    def __init__(self, replies: list[str]) -> None:
        self._replies = replies
        self.calls: list[list[dict[str, Any]]] = []

    async def complete_nonstreaming(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 512,
    ) -> str:
        self.calls.append(messages)
        return self._replies[len(self.calls) - 1]


async def test_judge_parses_json() -> None:
    llm = _FakeLLM(['{"score": 8, "reason": "chiaro e corretto"}'])
    verdicts = await judge_response(
        llm,
        spec=JudgeSpec(criteria=["È chiaro?"]),
        task_prompt="Fai X",
        response="Fatto X.",
    )
    assert len(verdicts) == 1
    assert verdicts[0].score == 8
    assert verdicts[0].criterion == "È chiaro?"


async def test_judge_regex_fallback_and_clamp() -> None:
    llm = _FakeLLM(["Direi score: 15 perché ottimo", "nessun numero qui"])
    verdicts = await judge_response(
        llm,
        spec=JudgeSpec(criteria=["A?", "B?"]),
        task_prompt="Fai X",
        response="Fatto.",
    )
    assert verdicts[0].score == 10  # clampato a 10
    assert verdicts[1].score == 0  # non parsabile → 0 con reason esplicativa
    assert "non parsabile" in verdicts[1].reason


async def test_judge_json_non_dict_does_not_crash() -> None:
    llm = _FakeLLM(["15"])
    verdicts = await judge_response(
        llm,
        spec=JudgeSpec(criteria=["A?"]),
        task_prompt="Fai X",
        response="Fatto.",
    )
    assert verdicts[0].score == 10  # fallback regex su "15", clampato
