"""Test di aggregazione, salvataggio e confronto dei report."""

from __future__ import annotations

from pathlib import Path

from backend.evals.models import (
    CheckResult,
    RunReport,
    ScenarioResult,
    TraceSummary,
)
from backend.evals.report import compare_reports, load_report, render_text, save_report


def _result(sid: str, *, passed: bool, cost: float = 0.01) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=sid,
        domain="filesystem",
        passed=passed,
        checks=[CheckResult(kind="finished_ok", passed=passed)],
        trace=TraceSummary(steps=2, finish_reason="stop", cost=cost),
        duration_seconds=1.0,
    )


def _report(*, run_id: str, results: list[ScenarioResult]) -> RunReport:
    return RunReport(
        run_id=run_id,
        model="z-ai/glm-5.2",
        started_at="2026-07-16T10:00:00",
        scenarios=results,
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    report = _report(run_id="r1", results=[_result("a-01", passed=True)])
    path = tmp_path / "report.json"
    save_report(report, path)
    assert load_report(path) == report
    assert b"\r" not in path.read_bytes()


def test_render_text_totals() -> None:
    report = _report(
        run_id="r1",
        results=[_result("a-01", passed=True), _result("b-02", passed=False)],
    )
    text = render_text(report)
    assert "1/2" in text  # scenari passati
    assert "a-01" in text and "b-02" in text
    assert "z-ai/glm-5.2" in text


def test_compare_reports_transitions() -> None:
    baseline = _report(
        run_id="r1",
        results=[_result("a-01", passed=True), _result("b-02", passed=False)],
    )
    current = _report(
        run_id="r2",
        results=[_result("a-01", passed=False), _result("b-02", passed=True)],
    )
    lines = compare_reports(current, baseline)
    joined = "\n".join(lines)
    assert "a-01" in joined and "REGRESSIONE" in joined
    assert "b-02" in joined and "MIGLIORATO" in joined
