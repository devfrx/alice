"""Wire-format guard: the permission-mode endpoint serializes the tier as JSON string.

Task 4 typed ``PermissionModeResponse.mode`` as the ``PermissionMode`` StrEnum;
this test pins the wire shape so the enum can never leak a non-string encoding.
The client is used WITHOUT running the lifespan: ``app.state.context`` is absent,
so the route takes its defensive branch and returns the default tier.
"""

from __future__ import annotations

import uuid

from backend.core.app import create_app
from starlette.testclient import TestClient


def test_get_permission_mode_wire_shape() -> None:
    """The enum-typed response serializes to the exact pre-enum JSON."""
    app = create_app(testing=True)
    client = TestClient(app)  # no context manager: lifespan never runs
    conv_id = str(uuid.uuid4())
    resp = client.get(f"/api/permission-mode/{conv_id}")
    assert resp.status_code == 200
    assert resp.json() == {"conversation_id": conv_id, "mode": "strict"}
