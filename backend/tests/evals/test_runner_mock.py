"""E2E dell'harness con LLM scriptato: boot, scenario, check, report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from backend.evals.models import (
    CheckSpec,
    JudgeSpec,
    SandboxFile,
    Scenario,
    ScenarioSetup,
)
from backend.evals.runner import run_scenario
from backend.tests.evals.scripted_llm import ScriptedLLM
from fastapi import FastAPI

_SCRIPT: list[list[dict[str, Any]]] = [
    [
        {"type": "token", "content": "Ho letto il file: contiene 'segreto-42'."},
        {"type": "usage", "input_tokens": 100, "output_tokens": 20, "cost": 0.0},
        {"type": "done", "finish_reason": "stop"},
    ],
]


@pytest.fixture
def scenario() -> Scenario:
    return Scenario(
        id="mock-read-01",
        title="Lettura mock",
        domain="filesystem",
        setup=ScenarioSetup(
            sandbox=[SandboxFile(path="dati.txt", content="segreto-42")],
            permission_mode="auto_edits",
        ),
        prompt="Dimmi cosa contiene {sandbox}/dati.txt.",
        checks=[
            CheckSpec(kind="response_matches", pattern="segreto-42"),
            CheckSpec(kind="finished_ok"),
            CheckSpec(kind="tool_not_called", name="execute_command"),
        ],
        judge=JudgeSpec(criteria=["La risposta è pertinente?"]),
    )


async def test_run_scenario_mock(app: FastAPI, scenario: Scenario, tmp_path: Path) -> None:
    ctx = app.state.context
    ctx.llm_service = ScriptedLLM(scripts=_SCRIPT)

    result = await run_scenario(
        ctx,
        scenario,
        output_dir=tmp_path,
        judge_enabled=True,
    )

    assert result.error is None
    assert result.passed is True
    assert [c.passed for c in result.checks] == [True, True, True]
    assert result.trace.finish_reason == "stop"
    assert result.judge[0].score == 7
    trace_file = tmp_path / "mock-read-01.jsonl"
    assert trace_file.is_file()
    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    frame_types = [json.loads(line)["type"] for line in lines]
    assert "turn.started" in frame_types
    assert "turn.finished" in frame_types
    assert frame_types[-1] == "eval.final"
