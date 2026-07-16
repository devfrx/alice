"""AL\\CE — Caricamento e validazione degli scenari YAML."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from backend.evals.models import Scenario

#: Directory di default degli scenari della suite.
SCENARIOS_DIR = Path(__file__).parent / "scenarios"


class ScenarioLoadError(Exception):
    """Scenario malformato o incoerente con il filename."""


def load_scenario(path: Path) -> Scenario:
    """Carica e valida un singolo scenario da *path*.

    Args:
        path: File ``.yaml`` dello scenario.

    Returns:
        Lo :class:`Scenario` validato.

    Raises:
        ScenarioLoadError: YAML illeggibile, schema invalido o ``id``
            diverso dallo stem del filename.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScenarioLoadError(f"{path.name}: YAML invalido — {exc}") from exc
    try:
        scenario = Scenario.model_validate(raw)
    except ValidationError as exc:
        raise ScenarioLoadError(f"{path.name}: schema invalido — {exc}") from exc
    if scenario.id != path.stem:
        raise ScenarioLoadError(
            f"{path.name}: id '{scenario.id}' diverso dal filename stem",
        )
    return scenario


def load_scenarios(
    directory: Path = SCENARIOS_DIR,
    *,
    filter_substring: str | None = None,
) -> list[Scenario]:
    """Carica tutti gli scenari di *directory*, ordinati per id.

    Args:
        directory: Directory contenente i file ``.yaml``.
        filter_substring: Se dato, tiene solo gli id che lo contengono.

    Returns:
        Gli scenari validati, ordinati per ``id``.

    Raises:
        ScenarioLoadError: Un file è invalido o due scenari condividono l'id.
    """
    scenarios = [load_scenario(p) for p in sorted(directory.glob("*.yaml"))]
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ScenarioLoadError("id duplicati nella directory scenari")
    if filter_substring:
        scenarios = [s for s in scenarios if filter_substring in s.id]
    return scenarios
