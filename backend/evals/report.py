"""AL\\CE — Report dei run eval: persistenza, confronto, render testuale."""

from __future__ import annotations

from pathlib import Path

from backend.evals.models import RunReport


def save_report(report: RunReport, path: Path) -> None:
    """Serializza *report* in JSON (indentato) su *path*.

    Args:
        report: Il report da persistere.
        path: File di destinazione (la directory viene creata se assente).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8", newline="\n")


def load_report(path: Path) -> RunReport:
    """Carica un :class:`RunReport` da un file JSON.

    Args:
        path: File sorgente scritto da :func:`save_report`.

    Returns:
        Il report deserializzato.
    """
    return RunReport.model_validate_json(path.read_text(encoding="utf-8"))


def compare_reports(current: RunReport, baseline: RunReport) -> list[str]:
    """Righe di confronto per-scenario tra *current* e *baseline*.

    Segnala: REGRESSIONE (passava, ora no), MIGLIORATO (falliva, ora sì),
    NUOVO (assente in baseline), RIMOSSO (assente in current).

    Args:
        current: Il report del run corrente.
        baseline: Il report di riferimento con cui confrontare.

    Returns:
        Una riga per ogni transizione di stato rilevata, ordinate per
        scenario del run corrente seguite dagli scenari rimossi.
    """
    lines: list[str] = []
    base = {r.scenario_id: r for r in baseline.scenarios}
    curr = {r.scenario_id: r for r in current.scenarios}
    for sid, result in curr.items():
        if sid not in base:
            lines.append(f"NUOVO       {sid}: passed={result.passed}")
        elif base[sid].passed and not result.passed:
            lines.append(f"REGRESSIONE {sid}: passava in {baseline.run_id}, ora fallisce")
        elif not base[sid].passed and result.passed:
            lines.append(f"MIGLIORATO  {sid}: falliva in {baseline.run_id}, ora passa")
    for sid in base:
        if sid not in curr:
            lines.append(f"RIMOSSO     {sid}: presente solo in baseline")
    return lines


def render_text(report: RunReport, baseline: RunReport | None = None) -> str:
    """Render leggibile del report (+ confronto opzionale con la baseline).

    Args:
        report: Il report da visualizzare.
        baseline: Se presente, aggiunge una sezione di confronto per-scenario.

    Returns:
        Il testo multi-riga pronto per la stampa/console.
    """
    lines: list[str] = [
        f"Eval run {report.run_id} — modello {report.model} — {report.started_at}",
        "",
    ]
    for r in sorted(report.scenarios, key=lambda x: x.scenario_id):
        status = "PASS" if r.passed else ("ERROR" if r.error else "FAIL")
        checks = f"{sum(c.passed for c in r.checks)}/{len(r.checks)}"
        judge = f" judge={sum(v.score for v in r.judge) / len(r.judge):.1f}" if r.judge else ""
        lines.append(
            f"[{status:5}] {r.scenario_id:24} ({r.domain:11}) "
            f"checks={checks} steps={r.trace.steps} "
            f"cost={r.trace.cost:.4f} {r.duration_seconds:.0f}s{judge}"
            + (f"  !! {r.error}" if r.error else ""),
        )
    total = len(report.scenarios)
    passed = sum(r.passed for r in report.scenarios)
    all_checks = [c for r in report.scenarios for c in r.checks]
    cost = sum(r.trace.cost for r in report.scenarios)
    lines += [
        "",
        f"Scenari: {passed}/{total} — check: "
        f"{sum(c.passed for c in all_checks)}/{len(all_checks)} — "
        f"costo totale: {cost:.4f}",
    ]
    if baseline is not None:
        diff = compare_reports(report, baseline)
        lines += ["", f"Confronto con baseline {baseline.run_id}:"]
        lines += diff if diff else ["  nessuna variazione per-scenario"]
    return "\n".join(lines)
