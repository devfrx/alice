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
    assert main([str(out)]) == 0
    assert out.read_text(encoding="utf-8") == first
    parsed = json.loads(first)
    assert "/api/health" in parsed["paths"]
