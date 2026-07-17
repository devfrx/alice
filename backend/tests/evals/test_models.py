"""Test dei modelli pydantic dell'eval harness."""

from __future__ import annotations

import pytest
from backend.evals.models import CheckSpec, Scenario
from pydantic import ValidationError


def _minimal_scenario_data() -> dict[str, object]:
    return {
        "id": "fs-demo-01",
        "title": "Demo",
        "domain": "filesystem",
        "prompt": "Crea un file.",
        "checks": [{"kind": "finished_ok"}],
    }


def test_scenario_minimal_valid() -> None:
    s = Scenario.model_validate(_minimal_scenario_data())
    assert s.id == "fs-demo-01"
    assert s.setup.permission_mode == "auto_edits"  # default
    assert s.budget.max_seconds == 180.0  # default
    assert s.judge is None


def test_scenario_requires_checks() -> None:
    data = _minimal_scenario_data()
    data["checks"] = []
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_scenario_rejects_unknown_domain() -> None:
    data = _minimal_scenario_data()
    data["domain"] = "cucina"
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_check_spec_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        CheckSpec.model_validate({"kind": "boh"})


def test_scenario_rejects_unknown_fields() -> None:
    data = _minimal_scenario_data()
    data["cheks"] = []  # typo intenzionale
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)
