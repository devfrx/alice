"""Unit tests for the /api/mcp/memory response models (Fase 4)."""

from __future__ import annotations

from backend.api.routes.mcp_memory import KGGraphResponse, _graph


def test_graph_parses_server_shape() -> None:
    data = {
        "entities": [
            {"name": "Ada", "entityType": "person", "observations": ["likes math"]},
        ],
        "relations": [
            {"from": "Ada", "to": "Babbage", "relationType": "knows"},
        ],
    }
    g: KGGraphResponse = _graph(data)
    assert g.entities[0].name == "Ada"
    assert g.relations[0].from_entity == "Ada"


def test_graph_falls_back_to_empty_on_mismatch() -> None:
    g = _graph({"entities": "nope"})
    assert g.entities == []
    assert g.relations == []


def test_graph_falls_back_on_non_graph_payload() -> None:
    # _call() wraps non-JSON tool output as {"result": raw}.
    g = _graph({"result": "plain text"})
    assert g.entities == []
    assert g.relations == []


def test_graph_serializes_from_alias() -> None:
    data = {
        "entities": [],
        "relations": [{"from": "A", "to": "B", "relationType": "r"}],
    }
    dumped = _graph(data).model_dump(by_alias=True)
    assert dumped["relations"][0]["from"] == "A"
