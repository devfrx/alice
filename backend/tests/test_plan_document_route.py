"""AL\\CE — unit tests for ``GET /api/plan-document/{conversation_id}``.

These exercise the route handler in isolation rather than through the full
:func:`backend.core.app.create_app` fixture: that fixture boots every plugin
and opens WebSocket/network paths that are slow and hang offline.  Calling the
handler directly with a stub request whose ``app.state.context`` carries a
mocked plan-document service keeps the test fast and deterministic, and still
covers the response shape and the defensive ``service is None`` path.  Mirrors
``test_tasks_route``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.routes.plan_document import (
    PlanDocumentResponse,
    get_conversation_plan_document,
)


def _make_request(ctx: object) -> SimpleNamespace:
    """Build a minimal stub request exposing ``app.state.context``."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(context=ctx)))


@pytest.mark.asyncio
async def test_returns_stored_document() -> None:
    """A wired service's document is returned in the response."""
    conv_id = uuid.uuid4()
    now = datetime.now(UTC)
    doc = {"title": "Plan", "body": "## step\nwork", "updated_at": now}
    service = SimpleNamespace(get_document=AsyncMock(return_value=doc))
    request = _make_request(SimpleNamespace(plan_document_service=service))

    result = await get_conversation_plan_document(str(conv_id), request)  # type: ignore[arg-type]

    assert isinstance(result, PlanDocumentResponse)
    assert result.conversation_id == str(conv_id)
    assert result.title == "Plan"
    assert result.body == "## step\nwork"
    assert result.updated_at == now
    service.get_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_unset_document_returns_empty() -> None:
    """A wired service with no document yields an empty response."""
    conv_id = uuid.uuid4()
    service = SimpleNamespace(get_document=AsyncMock(return_value=None))
    request = _make_request(SimpleNamespace(plan_document_service=service))

    result = await get_conversation_plan_document(str(conv_id), request)  # type: ignore[arg-type]

    assert result.conversation_id == str(conv_id)
    assert result.title == ""
    assert result.body == ""
    assert result.updated_at is None


@pytest.mark.asyncio
async def test_unset_service_returns_empty() -> None:
    """A ``None`` service yields an empty document instead of erroring."""
    conv_id = uuid.uuid4()
    request = _make_request(SimpleNamespace(plan_document_service=None))

    result = await get_conversation_plan_document(str(conv_id), request)  # type: ignore[arg-type]

    assert result.conversation_id == str(conv_id)
    assert result.title == ""
    assert result.body == ""
    assert result.updated_at is None


@pytest.mark.asyncio
async def test_missing_context_returns_empty() -> None:
    """A request with no ``app.state.context`` is handled defensively."""
    request = _make_request(None)

    result = await get_conversation_plan_document(str(uuid.uuid4()), request)  # type: ignore[arg-type]

    assert result.title == ""
    assert result.body == ""
    assert result.updated_at is None


@pytest.mark.asyncio
async def test_invalid_uuid_raises_400() -> None:
    """A malformed conversation id is rejected with a 400 (mirrors tasks)."""
    service = SimpleNamespace(get_document=AsyncMock())
    request = _make_request(SimpleNamespace(plan_document_service=service))

    with pytest.raises(HTTPException) as excinfo:
        await get_conversation_plan_document("not-a-uuid", request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 400
    service.get_document.assert_not_awaited()
