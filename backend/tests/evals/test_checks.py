"""Test dei valutatori dei check deterministici."""

from __future__ import annotations

from pathlib import Path

from backend.evals.checks import evaluate_checks
from backend.evals.models import CheckSpec, TraceSummary


def _trace(**kw: object) -> TraceSummary:
    base: dict[str, object] = {
        "steps": 3,
        "tool_calls": ["file_search_write_text_file"],
        "finish_reason": "stop",
    }
    base.update(kw)
    return TraceSummary.model_validate(base)


def test_file_checks(tmp_path: Path) -> None:
    (tmp_path / "out.txt").write_text("Ciao MONDO", encoding="utf-8")
    results = evaluate_checks(
        [
            CheckSpec(kind="file_exists", path="out.txt"),
            CheckSpec(kind="file_absent", path="altro.txt"),
            CheckSpec(kind="file_contains", path="out.txt", text="ciao mondo"),
        ],
        sandbox=tmp_path,
        response="",
        trace=_trace(),
    )
    assert [r.passed for r in results] == [True, True, True]


def test_response_and_tools() -> None:
    results = evaluate_checks(
        [
            CheckSpec(kind="response_matches", pattern="creat[oa]"),
            CheckSpec(kind="tool_called", name="write_text_file"),
            CheckSpec(kind="tool_not_called", name="run_terminal_command"),
        ],
        sandbox=Path("."),
        response="Ho creato il file richiesto.",
        trace=_trace(),
    )
    assert all(r.passed for r in results)


def test_budget_checks() -> None:
    results = evaluate_checks(
        [
            CheckSpec(kind="max_steps", value=3),
            CheckSpec(kind="finished_ok"),
        ],
        sandbox=Path("."),
        response="",
        trace=_trace(steps=4, finish_reason="error"),
    )
    assert [r.passed for r in results] == [False, False]


def test_file_contains_missing_file(tmp_path: Path) -> None:
    results = evaluate_checks(
        [CheckSpec(kind="file_contains", path="no.txt", text="x")],
        sandbox=tmp_path,
        response="",
        trace=_trace(),
    )
    assert results[0].passed is False
    assert "no.txt" in results[0].detail


def test_response_not_matches() -> None:
    results = evaluate_checks(
        [
            CheckSpec(kind="response_not_matches", pattern="note\\.txt"),
            CheckSpec(kind="response_not_matches", pattern="main\\.py"),
        ],
        sandbox=Path("."),
        response="I file Python sono src/main.py e src/utils/helpers.py.",
        trace=_trace(),
    )
    assert [r.passed for r in results] == [True, False]


def test_response_not_matches_invalid_regex_fails() -> None:
    """Una regex invalida non passa mai, nemmeno nella variante negata."""
    results = evaluate_checks(
        [CheckSpec(kind="response_not_matches", pattern="[non chiuso")],
        sandbox=Path("."),
        response="qualsiasi",
        trace=_trace(),
    )
    assert results[0].passed is False
    assert "pattern invalido" in results[0].detail


def test_response_matches_invalid_regex() -> None:
    results = evaluate_checks(
        [CheckSpec(kind="response_matches", pattern="[non chiuso")],
        sandbox=Path("."),
        response="qualsiasi",
        trace=_trace(),
    )
    assert results[0].passed is False
    assert "pattern invalido" in results[0].detail


def test_file_checks_reject_paths_outside_sandbox(tmp_path: Path) -> None:
    results = evaluate_checks(
        [
            CheckSpec(kind="file_exists", path="../fuori.txt"),
            CheckSpec(kind="file_absent", path="C:/Windows/system.ini"),
        ],
        sandbox=tmp_path,
        response="",
        trace=_trace(),
    )
    assert [r.passed for r in results] == [False, False]
    assert "fuori dalla sandbox" in results[0].detail
