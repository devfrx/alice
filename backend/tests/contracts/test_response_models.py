"""Contract ratchet: every /api endpoint must declare a Pydantic response model.

The baseline file freezes today's violations. The test fails when:

* a NEW untyped endpoint appears (fix it: declare ``response_model``), or
* a baseline entry becomes typed (good: delete that line from the baseline).

Endpoints whose ``response_class`` is a ``FileResponse`` are exempt (no JSON
contract to declare). WebSocket routes are not ``APIRoute`` and are skipped.

Regenerate the baseline ONLY when intentionally shrinking it (PowerShell)::

    $env:ALICE_REGEN_CONTRACT_BASELINE = "1"
    pytest tests/contracts/test_response_models.py
    Remove-Item Env:\\ALICE_REGEN_CONTRACT_BASELINE
"""

from __future__ import annotations

import os
import typing
from pathlib import Path

from backend.core.app import create_app
from fastapi.datastructures import DefaultPlaceholder
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.responses import FileResponse

BASELINE = Path(__file__).parent / "response_model_baseline.txt"


def _is_typed(route: APIRoute) -> bool:
    """True when the route declares a Pydantic response contract.

    Accepts a ``BaseModel`` subclass or ``list[BaseModel]``; plain ``dict``
    annotations do NOT count (they produce an empty OpenAPI schema).
    """
    model = route.response_model
    if model is None:
        return False
    if typing.get_origin(model) is list:
        args = typing.get_args(model)
        return bool(args) and isinstance(args[0], type) and issubclass(args[0], BaseModel)
    return isinstance(model, type) and issubclass(model, BaseModel)


def _is_exempt(route: APIRoute) -> bool:
    """File/stream endpoints have no JSON contract to declare."""
    response_class: object = route.response_class
    if isinstance(response_class, DefaultPlaceholder):
        response_class = response_class.value
    return isinstance(response_class, type) and issubclass(response_class, FileResponse)


def _violations() -> set[str]:
    """Collect ``"METHOD /api/path"`` keys for every untyped endpoint."""
    app = create_app(testing=True)
    found: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api"):
            continue
        if _is_exempt(route) or _is_typed(route):
            continue
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            found.add(f"{method} {route.path}")
    return found


def test_response_model_ratchet() -> None:
    """No new untyped endpoints; baseline entries must be removed once fixed."""
    current = _violations()
    if os.environ.get("ALICE_REGEN_CONTRACT_BASELINE") == "1":
        BASELINE.write_text("\n".join(sorted(current)) + "\n", encoding="utf-8")
    baseline = {
        line.strip()
        for line in BASELINE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    new = current - baseline
    fixed = baseline - current
    assert not new, f"New endpoints without a Pydantic response_model: {sorted(new)}"
    assert not fixed, (
        "Endpoints now typed — delete these lines from response_model_baseline.txt: "
        f"{sorted(fixed)}"
    )
