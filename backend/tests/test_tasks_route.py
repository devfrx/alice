"""AL\\CE — unit tests for the ``GET /api/tasks/{conversation_id}`` handler.

These exercise the route handler in isolation rather than through the full
:func:`backend.core.app.create_app` fixture used by ``test_artifacts_route``:
that fixture boots every plugin and opens WebSocket/network paths that are
slow (~100s) and hang offline.  Calling the handler directly with a stub
request whose ``app.state.context`` carries a mocked plan service keeps the
test fast and deterministic, and still covers the dict shape and the
defensive ``plan_service is None`` path.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.routes.tasks import TasksResponse, get_conversation_plan


def _make_request(ctx: object) -> SimpleNamespace:
    """Build a minimal stub request exposing ``app.state.context``."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(context=ctx)))


@pytest.mark.asyncio
async def test_returns_persisted_steps() -> None:
    """A wired plan service's steps are returned verbatim."""
    conv_id = uuid.uuid4()
    steps = [
        {"step": "Gather sources", "status": "done"},
        {"step": "Draft answer", "status": "in_progress"},
    ]
    plan_service = SimpleNamespace(get_plan=AsyncMock(return_value=steps))
    request = _make_request(SimpleNamespace(plan_service=plan_service))

    result = await get_conversation_plan(str(conv_id), request)  # type: ignore[arg-type]

    assert isinstance(result, TasksResponse)
    assert result.conversation_id == str(conv_id)
    assert result.steps == steps
    plan_service.get_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_unset_plan_service_returns_empty() -> None:
    """A ``None`` plan service yields an empty task list instead of erroring."""
    conv_id = uuid.uuid4()
    request = _make_request(SimpleNamespace(plan_service=None))

    result = await get_conversation_plan(str(conv_id), request)  # type: ignore[arg-type]

    assert result.conversation_id == str(conv_id)
    assert result.steps == []


@pytest.mark.asyncio
async def test_missing_context_returns_empty() -> None:
    """A request with no ``app.state.context`` is handled defensively."""
    request = _make_request(None)

    result = await get_conversation_plan(str(uuid.uuid4()), request)  # type: ignore[arg-type]

    assert result.steps == []


@pytest.mark.asyncio
async def test_invalid_uuid_raises_400() -> None:
    """A malformed conversation id is rejected with a 400 (mirrors artifacts)."""
    plan_service = SimpleNamespace(get_plan=AsyncMock())
    request = _make_request(SimpleNamespace(plan_service=plan_service))

    with pytest.raises(HTTPException) as excinfo:
        await get_conversation_plan("not-a-uuid", request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 400
    plan_service.get_plan.assert_not_awaited()
