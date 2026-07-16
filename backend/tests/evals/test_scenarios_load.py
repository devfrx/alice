"""Tutti gli scenari committati caricano e rispettano i vincoli di suite."""

from __future__ import annotations

from backend.evals.loader import SCENARIOS_DIR, load_scenarios

_EXPECTED_DOMAINS = {
    "filesystem",
    "search",
    "multistep",
    "planning",
    "permissions",
    "recovery",
    "knowledge",
}


def test_all_scenarios_load_and_cover_domains() -> None:
    scenarios = load_scenarios(SCENARIOS_DIR)
    assert len(scenarios) >= 20
    assert {s.domain for s in scenarios} == _EXPECTED_DOMAINS
    for s in scenarios:
        assert s.checks, s.id
        assert s.budget.max_seconds <= 300, s.id
