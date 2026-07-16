"""Test della sintesi trace e della scrittura JSONL."""

from __future__ import annotations

import json
from pathlib import Path

from backend.evals.trace import summarize_trace, write_trace_jsonl

_EVENTS: list[dict[str, object]] = [
    {"type": "turn.started", "turn_id": "t1", "conversation_id": "c1"},
    {"type": "turn.llm_step", "turn_id": "t1", "step": 1},
    {
        "type": "tool.call",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "file_search_write_text_file",
        "args": {"path": "x.txt"},
    },
    {
        "type": "tool.result",
        "turn_id": "t1",
        "execution_id": "e1",
        "tool_name": "file_search_write_text_file",
        "success": True,
        "result": "ok",
    },
    {"type": "turn.llm_step", "turn_id": "t1", "step": 2},
    {
        "type": "turn.usage",
        "turn_id": "t1",
        "step": 2,
        "input_tokens": 900,
        "output_tokens": 120,
        "tool_calls": 1,
        "max_steps": 11,
    },
    {
        "type": "turn.finished",
        "turn_id": "t1",
        "finish_reason": "stop",
        "input_tokens": 900,
        "output_tokens": 120,
        "steps": 2,
        "cost": None,
    },
]


def test_summarize_trace_counts() -> None:
    s = summarize_trace(_EVENTS, finish_reason="stop", cost=0.0042)
    assert s.steps == 2
    assert s.tool_calls == ["file_search_write_text_file"]
    assert s.input_tokens == 900
    assert s.output_tokens == 120
    assert s.finish_reason == "stop"
    assert s.cost == 0.0042


def test_summarize_trace_empty() -> None:
    s = summarize_trace([], finish_reason="error", cost=0.0)
    assert s.steps == 0
    assert s.tool_calls == []


def test_write_trace_jsonl(tmp_path: Path) -> None:
    out = tmp_path / "sc.jsonl"
    write_trace_jsonl(out, _EVENTS, final={"response": "fatto"})
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(_EVENTS) + 1
    assert json.loads(lines[-1]) == {"type": "eval.final", "response": "fatto"}
