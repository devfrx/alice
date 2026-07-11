"""Contract tests: offline OpenAPI export."""

from __future__ import annotations

import json
from pathlib import Path

from backend.api.openapi_export import build_schema, main


def test_build_schema_has_expected_shape() -> None:
    """The schema is OpenAPI 3.x and contains a known route."""
    schema = build_schema()
    assert str(schema["openapi"]).startswith("3.")
    assert "/api/health" in schema["paths"]


def test_main_writes_deterministic_json(tmp_path: Path) -> None:
    """Two consecutive exports produce byte-identical output."""
    out = tmp_path / "openapi.json"
    assert main([str(out)]) == 0
    first = out.read_text(encoding="utf-8")
    assert b"\r" not in out.read_bytes()
    assert main([str(out)]) == 0
    assert out.read_text(encoding="utf-8") == first
    parsed = json.loads(first)
    assert "/api/health" in parsed["paths"]


def test_ws_contract_injected_as_components() -> None:
    """The WS channel unions ride the same OpenAPI document (spec §6)."""
    schema = build_schema()
    components = schema["components"]["schemas"]
    for union_name in (
        "ChatServerMessage",
        "ChatClientMessage",
        "WsUserMessage",
        "EventsServerMessage",
        "EventsClientMessage",
    ):
        assert union_name in components, union_name
    # Discriminated member schemas land as named components too.
    assert "WsToken" in components
    assert "WsCalendarChanged" in components
    # The discriminator survives so openapi-typescript emits a tagged union.
    assert components["EventsServerMessage"]["discriminator"]["propertyName"] == "type"
