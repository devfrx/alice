"""Test del loader YAML → Scenario."""

from __future__ import annotations

from pathlib import Path

import pytest
from backend.evals.loader import ScenarioLoadError, load_scenario, load_scenarios

_VALID_YAML = """\
id: fs-demo-01
title: Demo
domain: filesystem
prompt: "Crea un file."
checks:
  - kind: finished_ok
"""


def test_load_scenario_valid(tmp_path: Path) -> None:
    f = tmp_path / "fs-demo-01.yaml"
    f.write_text(_VALID_YAML, encoding="utf-8")
    s = load_scenario(f)
    assert s.id == "fs-demo-01"


def test_load_scenario_id_must_match_filename(tmp_path: Path) -> None:
    f = tmp_path / "altro-nome.yaml"
    f.write_text(_VALID_YAML, encoding="utf-8")
    with pytest.raises(ScenarioLoadError, match="filename"):
        load_scenario(f)


def test_load_scenario_invalid_yaml(tmp_path: Path) -> None:
    f = tmp_path / "rotto.yaml"
    f.write_text("id: [non chiuso", encoding="utf-8")
    with pytest.raises(ScenarioLoadError):
        load_scenario(f)


def test_load_scenarios_sorted_and_filtered(tmp_path: Path) -> None:
    for sid in ("b-02", "a-01"):
        (tmp_path / f"{sid}.yaml").write_text(
            _VALID_YAML.replace("fs-demo-01", sid),
            encoding="utf-8",
        )
    all_scenarios = load_scenarios(tmp_path)
    assert [s.id for s in all_scenarios] == ["a-01", "b-02"]
    filtered = load_scenarios(tmp_path, filter_substring="b-")
    assert [s.id for s in filtered] == ["b-02"]


def test_load_scenarios_propagates_invalid_file(tmp_path: Path) -> None:
    (tmp_path / "a-01.yaml").write_text(
        _VALID_YAML.replace("fs-demo-01", "a-01"),
        encoding="utf-8",
    )
    (tmp_path / "rotto.yaml").write_text("id: [non chiuso", encoding="utf-8")
    with pytest.raises(ScenarioLoadError):
        load_scenarios(tmp_path)
