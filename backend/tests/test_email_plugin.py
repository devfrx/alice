"""Tests for backend.plugins.email_assistant.plugin — EmailPlugin."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.plugin_models import ExecutionContext
from backend.plugins.email_assistant.plugin import EmailPlugin

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="test",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


def _make_plugin(*, enabled: bool = True, service: AsyncMock | None = None) -> EmailPlugin:
    """Build an EmailPlugin wired to a mock context."""
    ctx = MagicMock()
    ctx.config.email.enabled = enabled
    ctx.email_service = service
    p = EmailPlugin()
    p._ctx = ctx
    p._initialized = True
    return p


@pytest.fixture
def email_svc() -> AsyncMock:
    """Mock email service with default return values."""
    svc = AsyncMock()
    svc.fetch_inbox = AsyncMock(return_value=[
        {"uid": "1", "subject": "Hello", "from": "a@b.com"},
    ])
    svc.fetch_email = AsyncMock(return_value=None)
    svc.search = AsyncMock(return_value=[])
    svc.send = AsyncMock(return_value={"success": True, "message_id": "<id>"})
    svc.mark_read = AsyncMock(return_value=True)
    svc.archive = AsyncMock(return_value=True)
    return svc


@pytest.fixture
def plugin(email_svc: AsyncMock) -> EmailPlugin:
    return _make_plugin(enabled=True, service=email_svc)


# ---------------------------------------------------------------------------
# read_emails
# ---------------------------------------------------------------------------


async def test_read_emails_success(
    plugin: EmailPlugin, exec_ctx: ExecutionContext,
):
    result = await plugin.execute_tool("read_emails", {}, context=exec_ctx)
    assert result.success is True
    data = json.loads(result.content)
    assert isinstance(data, list)
    assert data[0]["uid"] == "1"


# ---------------------------------------------------------------------------
# get_email
# ---------------------------------------------------------------------------


async def test_get_email_not_found(
    plugin: EmailPlugin, exec_ctx: ExecutionContext,
):
    result = await plugin.execute_tool(
        "get_email", {"uid": "999"}, context=exec_ctx,
    )
    assert result.success is False
    assert "non trovata" in result.error_message


async def test_get_email_found(
    plugin: EmailPlugin, email_svc: AsyncMock, exec_ctx: ExecutionContext,
):
    email_svc.fetch_email.return_value = {
        "uid": "42", "subject": "Found", "body": "content",
    }
    result = await plugin.execute_tool(
        "get_email", {"uid": "42"}, context=exec_ctx,
    )
    assert result.success is True
    data = json.loads(result.content)
    assert data["uid"] == "42"


# ---------------------------------------------------------------------------
# search_emails
# ---------------------------------------------------------------------------


async def test_search_emails_success(
    plugin: EmailPlugin, exec_ctx: ExecutionContext,
):
    result = await plugin.execute_tool(
        "search_emails", {"query": "FROM test"}, context=exec_ctx,
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------


async def test_send_email_success(
    plugin: EmailPlugin, exec_ctx: ExecutionContext,
):
    result = await plugin.execute_tool(
        "send_email",
        {"to": ["x@y.com"], "subject": "Hi", "body": "Hello"},
        context=exec_ctx,
    )
    assert result.success is True
    data = json.loads(result.content)
    assert data["success"] is True


async def test_send_email_rate_limit(
    plugin: EmailPlugin, email_svc: AsyncMock, exec_ctx: ExecutionContext,
):
    email_svc.send.side_effect = ValueError("Limite invii orari raggiunto")
    result = await plugin.execute_tool(
        "send_email",
        {"to": ["x@y.com"], "subject": "Hi", "body": "Hello"},
        context=exec_ctx,
    )
    assert result.success is False
    assert "Limite" in result.error_message


# ---------------------------------------------------------------------------
# mark_as_read
# ---------------------------------------------------------------------------


async def test_mark_as_read_success(
    plugin: EmailPlugin, exec_ctx: ExecutionContext,
):
    result = await plugin.execute_tool(
        "mark_as_read", {"uid": "1"}, context=exec_ctx,
    )
    assert result.success is True
    assert "letta" in result.content


# ---------------------------------------------------------------------------
# archive_email
# ---------------------------------------------------------------------------


async def test_archive_email_success(
    plugin: EmailPlugin, exec_ctx: ExecutionContext,
):
    result = await plugin.execute_tool(
        "archive_email", {"uid": "1"}, context=exec_ctx,
    )
    assert result.success is True
    assert "archiviata" in result.content


async def test_archive_email_not_found(
    plugin: EmailPlugin, email_svc: AsyncMock, exec_ctx: ExecutionContext,
):
    email_svc.archive.return_value = False
    result = await plugin.execute_tool(
        "archive_email", {"uid": "999"}, context=exec_ctx,
    )
    assert result.success is False
    assert "Impossibile" in result.error_message


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


async def test_plugin_disabled_returns_no_tools():
    p = _make_plugin(enabled=False)
    assert p.get_tools() == []


async def test_plugin_disabled_execute_returns_error(exec_ctx: ExecutionContext):
    p = _make_plugin(enabled=False)
    result = await p.execute_tool("read_emails", {}, context=exec_ctx)
    assert result.success is False
    assert "non abilitato" in result.error_message


async def test_unknown_tool_returns_failure(
    plugin: EmailPlugin, exec_ctx: ExecutionContext,
):
    result = await plugin.execute_tool(
        "nonexistent_tool", {}, context=exec_ctx,
    )
    assert result.success is False
    assert "sconosciuto" in result.error_message


async def test_service_unavailable_returns_error(exec_ctx: ExecutionContext):
    p = _make_plugin(enabled=True, service=None)
    result = await p.execute_tool("read_emails", {}, context=exec_ctx)
    assert result.success is False
    assert "non disponibile" in result.error_message
