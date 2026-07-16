"""AL\\CE — Valutatori dei check deterministici (misura primaria)."""

from __future__ import annotations

import re
from pathlib import Path

from backend.evals.models import CheckResult, CheckSpec, TraceSummary


def _tool_matches(called: str, wanted: str) -> bool:
    """Match sul nome namespaced esatto o sul suffisso ``_<wanted>``."""
    return called == wanted or called.endswith(f"_{wanted}")


def evaluate_check(
    check: CheckSpec,
    *,
    sandbox: Path,
    response: str,
    trace: TraceSummary,
) -> CheckResult:
    """Valuta un singolo check contro sandbox, risposta e trace.

    Semantiche per ``kind``:

    - ``file_exists`` / ``file_absent``: ``check.path`` relativo alla sandbox.
    - ``file_contains``: substring case-insensitive (``casefold``) di
      ``check.text`` nel contenuto di ``check.path``.
    - ``response_matches``: ``re.search`` di ``check.pattern`` su *response*
      con i flag ``IGNORECASE | DOTALL``.
    - ``tool_called`` / ``tool_not_called``: match sul nome namespaced esatto
      oppure sul suffisso ``_<check.name>`` (es. ``file_search_write_text_file``
      matcha ``name: write_text_file``).
    - ``max_steps``: ``trace.steps <= check.value``.
    - ``finished_ok``: ``trace.finish_reason == "stop"``.

    Args:
        check: La specifica del check (i campi usati dipendono da ``kind``).
        sandbox: Radice della sandbox dello scenario (per i check su file).
        response: Testo finale dell'assistente.
        trace: Sintesi della trace del turno.

    Returns:
        Il :class:`CheckResult` con esito e dettaglio umano.
    """
    kind = check.kind
    if kind in ("file_exists", "file_absent", "file_contains"):
        rel = check.path or ""
        target = (sandbox / rel).resolve()
        if kind == "file_exists":
            ok = target.is_file()
            return CheckResult(kind=kind, passed=ok, detail=f"{rel}: exists={ok}")
        if kind == "file_absent":
            ok = not target.exists()
            return CheckResult(kind=kind, passed=ok, detail=f"{rel}: absent={ok}")
        if not target.is_file():
            return CheckResult(kind=kind, passed=False, detail=f"{rel}: file mancante")
        content = target.read_text(encoding="utf-8", errors="replace")
        ok = (check.text or "").casefold() in content.casefold()
        return CheckResult(kind=kind, passed=ok, detail=f"{rel}: contains={ok}")

    if kind == "response_matches":
        pattern = check.pattern or ""
        ok = re.search(pattern, response, re.IGNORECASE | re.DOTALL) is not None
        return CheckResult(kind=kind, passed=ok, detail=f"pattern={pattern!r} match={ok}")

    if kind in ("tool_called", "tool_not_called"):
        wanted = check.name or ""
        hit = any(_tool_matches(c, wanted) for c in trace.tool_calls)
        ok = hit if kind == "tool_called" else not hit
        return CheckResult(kind=kind, passed=ok, detail=f"{wanted}: called={hit}")

    if kind == "max_steps":
        limit = check.value if check.value is not None else 0
        ok = trace.steps <= limit
        return CheckResult(kind=kind, passed=ok, detail=f"steps={trace.steps} max={limit}")

    # finished_ok
    ok = trace.finish_reason == "stop"
    return CheckResult(kind=kind, passed=ok, detail=f"finish_reason={trace.finish_reason}")


def evaluate_checks(
    checks: list[CheckSpec],
    *,
    sandbox: Path,
    response: str,
    trace: TraceSummary,
) -> list[CheckResult]:
    """Valuta tutti i *checks* nell'ordine dato (vedi :func:`evaluate_check`)."""
    return [evaluate_check(c, sandbox=sandbox, response=response, trace=trace) for c in checks]
