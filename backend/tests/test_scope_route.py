"""AL\\CE — unit tests for the ``/api/scope/{conversation_id}`` handlers.

These exercise the GET/PUT/DELETE route handlers in isolation rather than
through the full :func:`backend.core.app.create_app` fixture: that fixture
boots every plugin and opens WebSocket/network paths that are slow (~100s) and
hang offline.  Calling each handler directly with a stub request whose
``app.state.context`` carries a mocked :class:`ScopeService` keeps the tests
fast and deterministic, and still covers the idle-guard (``409`` while busy),
the defensive ``service is None`` path (``503`` on mutate, empty on read), and
the validation (``400``) and bad-UUID (``400``) paths.

An autouse fixture clears the chat busy registry around every test so a
simulated "busy" conversation never leaks into a sibling test.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.routes.chat import _shared
from backend.api.routes.scope import (
    ScopeResponse,
    ScopeUpdateRequest,
    delete_conversation_scope,
    get_conversation_scope,
    put_conversation_scope,
)


def _make_request(ctx: object) -> SimpleNamespace:
    """Build a minimal stub request exposing ``app.state.context``."""
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(context=ctx)))


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Clear the busy registry before and after each test (no leakage)."""
    _shared._active_conversations.clear()
    yield
    _shared._active_conversations.clear()


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_folders_and_idle() -> None:
    """A wired service's folders are returned with ``is_idle`` True when idle."""
    conv_id = uuid.uuid4()
    folders = [r"C:\work\project", r"D:\notes"]
    service = SimpleNamespace(get_scope=AsyncMock(return_value=folders))
    request = _make_request(SimpleNamespace(scope_service=service))

    result = await get_conversation_scope(str(conv_id), request)  # type: ignore[arg-type]

    assert isinstance(result, ScopeResponse)
    assert result.conversation_id == str(conv_id)
    assert result.folders == folders
    assert result.is_idle is True
    service.get_scope.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_reports_not_idle_when_busy() -> None:
    """A conversation in the busy registry is reported ``is_idle`` False."""
    conv_id = uuid.uuid4()
    _shared._active_conversations.add(str(conv_id))
    service = SimpleNamespace(get_scope=AsyncMock(return_value=[]))
    request = _make_request(SimpleNamespace(scope_service=service))

    result = await get_conversation_scope(str(conv_id), request)  # type: ignore[arg-type]

    assert result.is_idle is False


@pytest.mark.asyncio
async def test_get_unset_service_returns_empty() -> None:
    """A ``None`` scope service yields an empty scope instead of erroring."""
    conv_id = uuid.uuid4()
    request = _make_request(SimpleNamespace(scope_service=None))

    result = await get_conversation_scope(str(conv_id), request)  # type: ignore[arg-type]

    assert result.conversation_id == str(conv_id)
    assert result.folders == []
    assert result.is_idle is True


@pytest.mark.asyncio
async def test_get_missing_context_returns_empty() -> None:
    """A request with no ``app.state.context`` is handled defensively."""
    request = _make_request(None)

    result = await get_conversation_scope(str(uuid.uuid4()), request)  # type: ignore[arg-type]

    assert result.folders == []
    assert result.is_idle is True


@pytest.mark.asyncio
async def test_get_invalid_uuid_raises_400() -> None:
    """A malformed conversation id is rejected with a 400."""
    service = SimpleNamespace(get_scope=AsyncMock())
    request = _make_request(SimpleNamespace(scope_service=service))

    with pytest.raises(HTTPException) as excinfo:
        await get_conversation_scope("not-a-uuid", request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 400
    service.get_scope.assert_not_awaited()


# ---------------------------------------------------------------------------
# PUT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_idle_valid_persists_and_returns() -> None:
    """An idle PUT validates+persists and echoes the stored folders."""
    conv_id = uuid.uuid4()
    stored = [r"C:\work\project"]
    service = SimpleNamespace(
        set_scope=AsyncMock(return_value=None),
        get_scope=AsyncMock(return_value=stored),
    )
    request = _make_request(SimpleNamespace(scope_service=service))
    body = ScopeUpdateRequest(folders=[r"C:\work\project"])

    result = await put_conversation_scope(str(conv_id), body, request)  # type: ignore[arg-type]

    assert isinstance(result, ScopeResponse)
    assert result.conversation_id == str(conv_id)
    assert result.folders == stored
    assert result.is_idle is True
    service.set_scope.assert_awaited_once_with(conv_id, [r"C:\work\project"])


@pytest.mark.asyncio
async def test_put_busy_raises_409_and_skips_set() -> None:
    """A busy conversation rejects PUT with 409 ``scope_locked`` and no write."""
    conv_id = uuid.uuid4()
    _shared._active_conversations.add(str(conv_id))
    service = SimpleNamespace(
        set_scope=AsyncMock(),
        get_scope=AsyncMock(),
    )
    request = _make_request(SimpleNamespace(scope_service=service))
    body = ScopeUpdateRequest(folders=[r"C:\work\project"])

    with pytest.raises(HTTPException) as excinfo:
        await put_conversation_scope(str(conv_id), body, request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "scope_locked"
    service.set_scope.assert_not_awaited()


@pytest.mark.asyncio
async def test_put_invalid_folder_raises_400() -> None:
    """A folder that fails service validation surfaces as a 400."""
    conv_id = uuid.uuid4()
    service = SimpleNamespace(
        set_scope=AsyncMock(side_effect=ValueError("bad")),
        get_scope=AsyncMock(),
    )
    request = _make_request(SimpleNamespace(scope_service=service))
    body = ScopeUpdateRequest(folders=[r"C:\Windows"])

    with pytest.raises(HTTPException) as excinfo:
        await put_conversation_scope(str(conv_id), body, request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "bad"


@pytest.mark.asyncio
async def test_put_unset_service_raises_503() -> None:
    """A ``None`` scope service rejects PUT with 503."""
    conv_id = uuid.uuid4()
    request = _make_request(SimpleNamespace(scope_service=None))
    body = ScopeUpdateRequest(folders=[r"C:\work\project"])

    with pytest.raises(HTTPException) as excinfo:
        await put_conversation_scope(str(conv_id), body, request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_put_invalid_uuid_raises_400() -> None:
    """A malformed conversation id is rejected with a 400 before any write."""
    service = SimpleNamespace(set_scope=AsyncMock(), get_scope=AsyncMock())
    request = _make_request(SimpleNamespace(scope_service=service))
    body = ScopeUpdateRequest(folders=[r"C:\work\project"])

    with pytest.raises(HTTPException) as excinfo:
        await put_conversation_scope("not-a-uuid", body, request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 400
    service.set_scope.assert_not_awaited()


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_idle_clears_and_returns_empty() -> None:
    """An idle DELETE clears the scope and returns an empty folder list."""
    conv_id = uuid.uuid4()
    service = SimpleNamespace(clear_scope=AsyncMock(return_value=None))
    request = _make_request(SimpleNamespace(scope_service=service))

    result = await delete_conversation_scope(str(conv_id), request)  # type: ignore[arg-type]

    assert isinstance(result, ScopeResponse)
    assert result.conversation_id == str(conv_id)
    assert result.folders == []
    assert result.is_idle is True
    service.clear_scope.assert_awaited_once_with(conv_id)


@pytest.mark.asyncio
async def test_delete_busy_raises_409_and_skips_clear() -> None:
    """A busy conversation rejects DELETE with 409 ``scope_locked``."""
    conv_id = uuid.uuid4()
    _shared._active_conversations.add(str(conv_id))
    service = SimpleNamespace(clear_scope=AsyncMock())
    request = _make_request(SimpleNamespace(scope_service=service))

    with pytest.raises(HTTPException) as excinfo:
        await delete_conversation_scope(str(conv_id), request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "scope_locked"
    service.clear_scope.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_unset_service_raises_503() -> None:
    """A ``None`` scope service rejects DELETE with 503."""
    conv_id = uuid.uuid4()
    request = _make_request(SimpleNamespace(scope_service=None))

    with pytest.raises(HTTPException) as excinfo:
        await delete_conversation_scope(str(conv_id), request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_delete_invalid_uuid_raises_400() -> None:
    """A malformed conversation id is rejected with a 400 before any clear."""
    service = SimpleNamespace(clear_scope=AsyncMock())
    request = _make_request(SimpleNamespace(scope_service=service))

    with pytest.raises(HTTPException) as excinfo:
        await delete_conversation_scope("not-a-uuid", request)  # type: ignore[arg-type]

    assert excinfo.value.status_code == 400
    service.clear_scope.assert_not_awaited()
