"""AL\\CE — Offline OpenAPI schema export (no server, no lifespan).

Phase-1 contract tooling: builds the FastAPI app object only (services are
initialized in the lifespan, which never runs here) and serializes
``app.openapi()`` deterministically (sorted keys, stable indentation) so the
schema can be committed and consumed as codegen input by the frontend
(``openapi-typescript`` via ``scripts/gen-contracts.ps1``). The exported
document also carries the WS channel unions from backend/api/ws_schema as named components.

Usage (from the repo root, venv active)::

    python -m backend.api.openapi_export frontend/src/renderer/src/types/generated/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _inject_ws_schemas(schema: dict[str, Any]) -> None:
    """Inject the WS channel unions into ``components.schemas``.

    The WS contract rides the same OpenAPI document so the existing
    ``openapi-typescript`` pipeline generates the TS unions with no extra
    tooling. Pydantic emits validation-mode JSON Schema (fields with
    defaults are optional — truthful about today's wire, where ``origin``
    is not emitted yet). A name collision with a REST component (or a
    mismatched duplicate between adapters) is a hard error: rename the
    Pydantic model rather than silently overwrite.

    Args:
        schema: The OpenAPI document dict to mutate in place.

    Raises:
        ValueError: If a WS component name collides with an existing
            component that has a different schema.
    """
    from backend.api.ws_schema import WS_CONTRACT_ADAPTERS

    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for union_name, adapter in WS_CONTRACT_ADAPTERS.items():
        sub = adapter.json_schema(
            ref_template="#/components/schemas/{model}",
        )
        for def_name, def_schema in sub.pop("$defs", {}).items():
            existing = components.get(def_name)
            if existing is not None and existing != def_schema:
                raise ValueError(
                    f"WS schema component collision: {def_name!r}",
                )
            components[def_name] = def_schema
        if union_name in components:
            raise ValueError(
                f"WS schema component collision: {union_name!r}",
            )
        components[union_name] = sub


def build_schema() -> dict[str, Any]:
    """Build the OpenAPI schema without starting any service.

    Returns:
        The OpenAPI document as a plain dict, with the WS channel unions injected as
        named components.
    """
    from backend.core.app import create_app

    app = create_app(testing=True)
    schema = app.openapi()
    _inject_ws_schemas(schema)
    return schema


def main(argv: list[str]) -> int:
    """Write the schema as stable JSON to ``argv[0]`` (default ``./openapi.json``).

    Args:
        argv: CLI arguments (without the program name).

    Returns:
        Process exit code (0 on success).
    """
    out = Path(argv[0]) if argv else Path("openapi.json")
    schema = build_schema()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
