"""AL\\CE — Mid-turn permission-tier liveness (Fase 7).

The gate reads the tier **per tool-call**, so changing the mode mid-turn (the
user "hitting the brakes") takes effect on the very next gated call without
rebuilding anything.
"""

from __future__ import annotations

import pytest

from backend.core.plugin_models import ExecutionContext, ToolDefinition
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_service import PermissionService
from backend.services.turn.pipeline import (
    Disposition,
    PermissionMiddleware,
    ToolCall,
    ToolOutcome,
)


def _write_call(tmp_path) -> ToolCall:
    tool = ToolDefinition(
        name="write_text_file",
        description="d",
        capabilities=("fs_write",),
        path_args=("path",),
    )
    return ToolCall(
        tc_id="c1",
        tool_name="write_text_file",
        args={"path": str(tmp_path / "f.txt")},
        tool_def=tool,
        exec_id="e1",
        conversation_id="conv-1",
        context=ExecutionContext(
            session_id="ip", conversation_id="conv-1", execution_id="e1",
        ),
        dedup_key="k",
        is_client=False,
        turn_id="turn-1",
    )


async def _proceed(call: ToolCall) -> ToolOutcome:
    return ToolOutcome(call, Disposition.EXECUTE)


@pytest.mark.asyncio
async def test_mode_change_takes_effect_on_next_call(tmp_path) -> None:
    scope = tmp_path / "ws"
    scope.mkdir()
    svc = PermissionService(scope_provider=lambda _c: [scope])

    # Mutable tier holder, flipped between the two gated calls.
    current = {"mode": PermissionMode.AUTOPILOT}
    mw = PermissionMiddleware(svc, lambda _conv: current["mode"])

    call1 = _write_call(scope)
    out1 = await mw.handle(call1, _proceed)
    assert out1.disposition is Disposition.EXECUTE  # autopilot lets the write run

    # User switches to plan mode mid-turn.
    current["mode"] = PermissionMode.PLAN
    call2 = _write_call(scope)
    out2 = await mw.handle(call2, _proceed)
    assert out2.disposition is Disposition.PLAN_DENIED  # the brakes apply immediately
