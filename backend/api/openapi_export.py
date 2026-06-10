"""AL\\CE — Offline OpenAPI schema export (no server, no lifespan).

Phase-1 contract tooling: builds the FastAPI app object only (services are
initialized in the lifespan, which never runs here) and serializes
``app.openapi()`` deterministically (sorted keys, stable indentation) so the
schema can be committed and consumed as codegen input by the frontend
(``openapi-typescript`` via ``scripts/gen-contracts.ps1``).

Usage (from the repo root, venv active)::

    python -m backend.api.openapi_export frontend/src/renderer/src/types/generated/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def build_schema() -> dict[str, Any]:
    """Build the OpenAPI schema without starting any service.

    Returns:
        The OpenAPI document as a plain dict, exactly as FastAPI generates it.
    """
    from backend.core.app import create_app

    app = create_app(testing=True)
    return app.openapi()


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
