"""Test del validator di echarts_option (auto-fix + rifiuto LLM-output rotti)."""

from __future__ import annotations

import pytest

from backend.plugins.chart_generator.option_validator import (
    ChartOptionError,
    validate_and_normalize_option,
)


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------


def test_autofills_series_type_from_chart_type() -> None:
    """Quando ``series[].type`` manca lo riempie dal ``chart_type`` top-level."""
    option = {"series": [{"data": [1, 2, 3]}]}
    fixed = validate_and_normalize_option(option, "bar")
    assert fixed["series"][0]["type"] == "bar"


def test_keeps_existing_series_type_when_present() -> None:
    """Non sovrascrive il ``type`` esplicito anche se diverge dal chart_type."""
    option = {"series": [{"type": "line", "data": [1]}]}
    fixed = validate_and_normalize_option(option, "bar")
    assert fixed["series"][0]["type"] == "line"


def test_does_not_mutate_input() -> None:
    """L'input originale resta intatto (auto-fix è non distruttivo)."""
    option = {"series": [{"data": [1]}]}
    validate_and_normalize_option(option, "bar")
    assert "type" not in option["series"][0]


# ---------------------------------------------------------------------------
# Errori parlanti per LLM
# ---------------------------------------------------------------------------


def test_rejects_missing_series() -> None:
    with pytest.raises(ChartOptionError, match="series"):
        validate_and_normalize_option({"xAxis": {}}, "bar")


def test_rejects_empty_series_list() -> None:
    with pytest.raises(ChartOptionError, match="vuot"):
        validate_and_normalize_option({"series": []}, "bar")


def test_rejects_missing_data_in_series() -> None:
    with pytest.raises(ChartOptionError, match="data"):
        validate_and_normalize_option(
            {"series": [{"type": "bar"}]}, "bar",
        )


def test_rejects_empty_data_array() -> None:
    with pytest.raises(ChartOptionError, match="vuot"):
        validate_and_normalize_option(
            {"series": [{"type": "bar", "data": []}]}, "bar",
        )


def test_rejects_unknown_chart_type_when_series_type_missing() -> None:
    with pytest.raises(ChartOptionError, match="non è un tipo ECharts"):
        validate_and_normalize_option(
            {"series": [{"data": [1]}]}, "blarg",
        )


# ---------------------------------------------------------------------------
# Rilevamento corruzione da LLM (caso reale: backtick + chiave troncata)
# ---------------------------------------------------------------------------


def test_detects_corrupted_name_with_backtick_type_fragment() -> None:
    """Il bug visto in produzione: il modello incolla ``,type:`` nel name.

    Caso reale dalla conversazione ec63a397: il modello ha generato
    ``"name":"Valore in Miliardi/Milioni`,type:"`` invece di
    ``"name":"...","type":"bar"``.  Il JSON è valido ma la series resta
    senza type → ECharts renderizza vuoto.  Il validator deve rifiutare.
    """
    option = {
        "series": [
            {
                "data": [3.6, 40],
                "name": "Valore in Miliardi/Milioni`,type:",
            },
        ],
    }
    with pytest.raises(ChartOptionError, match="sospetto"):
        validate_and_normalize_option(option, "bar")


def test_detects_corrupted_name_with_quote_type_fragment() -> None:
    option = {
        "series": [
            {"type": "line", "data": [1], "name": 'Pippo",type:"line'},
        ],
    }
    with pytest.raises(ChartOptionError, match="sospetto"):
        validate_and_normalize_option(option, "line")


def test_detects_corrupted_explicit_type() -> None:
    """Caso reale conv. 260d532c: ``"type":"bar}]},title:"`` arriva come stringa.

    JSON valido, ma series[0].type contiene `}`/`]`/`,`/`:` — frammenti
    di altre chiavi finiti dentro il valore per quoting LLM rotto.
    """
    option = {
        "xAxis": {"data": ["A", "B", "C"]},
        "yAxis": {"type": "value"},
        "series": [{"type": 'bar}]},title:"', "data": [1, 2, 3]}],
    }
    with pytest.raises(ChartOptionError, match="non validi"):
        validate_and_normalize_option(option, "bar")


def test_rejects_unknown_explicit_type() -> None:
    option = {
        "xAxis": {"data": ["A"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "blarg", "data": [1]}],
    }
    with pytest.raises(ChartOptionError, match="non è un tipo ECharts"):
        validate_and_normalize_option(option, "bar")


# ---------------------------------------------------------------------------
# Coerenza assi cartesiani
# ---------------------------------------------------------------------------


def test_skips_axis_check_when_xaxis_missing() -> None:
    """Senza xAxis ECharts usa default category → non rifiutiamo."""
    option = {"series": [{"type": "bar", "data": [1, 2]}]}
    fixed = validate_and_normalize_option(option, "bar")
    assert fixed["series"][0]["data"] == [1, 2]


def test_autofills_missing_yaxis_when_xaxis_present() -> None:
    """Caso reale conv. 8e9b4d38: xAxis fornito, yAxis assente.

    Senza autofix ECharts solleva ``yAxis "0" not found`` perché la
    series default punta a ``yAxisIndex=0`` che non esiste → canvas
    vuoto nel viewer. Il validator deve aggiungere un default.
    """
    option = {
        "xAxis": {"data": ["A", "B", "C"]},
        "series": [{"type": "bar", "data": [1, 2, 3], "name": "X"}],
    }
    fixed = validate_and_normalize_option(option, "bar")
    assert fixed["yAxis"] == {"type": "value"}
    # xAxis originale preservato
    assert fixed["xAxis"]["data"] == ["A", "B", "C"]


def test_autofills_missing_xaxis_when_yaxis_present() -> None:
    option = {
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "data": [1, 2]}],
    }
    fixed = validate_and_normalize_option(option, "line")
    assert fixed["xAxis"] == {"type": "category"}


def test_autofills_both_axes_when_missing() -> None:
    option = {"series": [{"type": "bar", "data": [1, 2]}]}
    fixed = validate_and_normalize_option(option, "bar")
    assert fixed["xAxis"] == {"type": "category"}
    assert fixed["yAxis"] == {"type": "value"}


def test_does_not_autofill_axes_for_pie() -> None:
    """I grafici axis-less (pie/radar/gauge/...) non devono ricevere assi."""
    option = {
        "series": [{"type": "pie", "data": [{"name": "A", "value": 1}]}],
    }
    fixed = validate_and_normalize_option(option, "pie")
    assert "xAxis" not in fixed
    assert "yAxis" not in fixed


def test_rejects_axis_data_length_mismatch() -> None:
    option = {
        "xAxis": {"data": ["A", "B", "C"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [1, 2]}],
    }
    with pytest.raises(ChartOptionError, match="Mismatch"):
        validate_and_normalize_option(option, "bar")


def test_accepts_matching_lengths() -> None:
    option = {
        "xAxis": {"data": ["A", "B"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [1, 2]}],
    }
    fixed = validate_and_normalize_option(option, "bar")
    assert fixed["series"][0]["data"] == [1, 2]


# ---------------------------------------------------------------------------
# Tipi axis-less
# ---------------------------------------------------------------------------


def test_pie_chart_does_not_require_axes() -> None:
    option = {
        "series": [
            {
                "type": "pie",
                "data": [
                    {"name": "A", "value": 10},
                    {"name": "B", "value": 20},
                ],
            },
        ],
    }
    fixed = validate_and_normalize_option(option, "pie")
    assert fixed["series"][0]["type"] == "pie"


def test_pie_chart_autofills_type_from_chart_type() -> None:
    option = {"series": [{"data": [{"name": "A", "value": 1}]}]}
    fixed = validate_and_normalize_option(option, "pie")
    assert fixed["series"][0]["type"] == "pie"


# ---------------------------------------------------------------------------
# Strutture invalide a livello tipo
# ---------------------------------------------------------------------------


def test_rejects_non_dict_option() -> None:
    with pytest.raises(ChartOptionError):
        validate_and_normalize_option([], "bar")  # type: ignore[arg-type]


def test_rejects_non_list_series() -> None:
    with pytest.raises(ChartOptionError, match="lista"):
        validate_and_normalize_option({"series": {"type": "bar"}}, "bar")


def test_rejects_non_dict_series_entry() -> None:
    with pytest.raises(ChartOptionError, match="oggetto"):
        validate_and_normalize_option({"series": ["foo"]}, "bar")
