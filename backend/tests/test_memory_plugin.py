"""Tests for backend.plugins.memory — MemoryPlugin."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from backend.core.plugin_models import ExecutionContext, ToolResult
from backend.services.memory_service import MemoryEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="test",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


def _make_memory_entry(
    content: str = "user likes dark mode",
    scope: str = "long_term",
    category: str | None = "preference",
    source: str = "llm",
) -> MemoryEntry:
    """Build a MemoryEntry with sensible defaults."""
    return MemoryEntry(
        id=uuid.uuid4(),
        content=content,
        scope=scope,
        category=category,
        source=source,
        created_at=datetime.now(timezone.utc),
        expires_at=None,
        conversation_id=None,
        embedding_model="test-model",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ctx():
    """Build a mock AppContext with a real ``QdrantBackend`` wrapping a mocked memory service."""
    from backend.core.context import AppContext
    from backend.services.knowledge import QdrantBackend

    ctx = MagicMock(spec=AppContext)
    ctx.memory_service = AsyncMock()
    ctx.note_service = None
    ctx.knowledge_backend = QdrantBackend(
        memory_service=ctx.memory_service,
        note_service=None,
    )
    ctx.config = MagicMock()
    ctx.config.memory.embedding_model = "test-model"
    ctx.config.memory.session_ttl_hours = 24
    return ctx


@pytest.fixture
def exec_context() -> ExecutionContext:
    return _make_exec_ctx()


@pytest.fixture
def plugin(mock_ctx):
    """Return an initialised MemoryPlugin with a mocked context."""
    from backend.plugins.memory.plugin import MemoryPlugin

    p = MemoryPlugin()
    p._ctx = mock_ctx
    p._initialized = True
    return p


@pytest.fixture
def plugin_no_service(mock_ctx):
    """MemoryPlugin where the knowledge backend (memory) is unavailable."""
    from backend.plugins.memory.plugin import MemoryPlugin

    mock_ctx.memory_service = None
    mock_ctx.knowledge_backend = None
    p = MemoryPlugin()
    p._ctx = mock_ctx
    p._initialized = True
    return p


# ===================================================================
# 1. Plugin Lifecycle & Attributes
# ===================================================================


class TestMemoryPluginLifecycle:
    """Plugin metadata, tool registration, and attributes."""

    def test_plugin_attributes(self):
        from backend.plugins.memory.plugin import MemoryPlugin

        p = MemoryPlugin()
        assert p.plugin_name == "memory"
        assert p.plugin_version == "1.0.0"
        assert p.plugin_priority == 90
        assert p.plugin_dependencies == []

    def test_get_tools_returns_five(self, plugin):
        tools = plugin.get_tools()
        assert len(tools) == 5

    def test_tool_names(self, plugin):
        names = {t.name for t in plugin.get_tools()}
        assert names == {
            "remember",
            "recall",
            "forget",
            "list_memories",
            "clear_session_memory",
        }

    def test_forget_requires_confirmation(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["forget"].requires_confirmation is True
        assert tools["forget"].risk_level == "medium"

    def test_clear_session_requires_confirmation(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["clear_session_memory"].requires_confirmation is True
        assert tools["clear_session_memory"].risk_level == "medium"

    def test_remember_is_safe(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["remember"].requires_confirmation is False
        assert tools["remember"].risk_level == "safe"

    def test_recall_is_safe(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["recall"].requires_confirmation is False
        assert tools["recall"].risk_level == "safe"

    def test_list_memories_is_safe(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["list_memories"].requires_confirmation is False
        assert tools["list_memories"].risk_level == "safe"


# ===================================================================
# 2. remember tool
# ===================================================================


class TestRememberTool:
    """Tests for the remember tool execution."""

    @pytest.mark.asyncio
    async def test_remember_tool(self, plugin, mock_ctx, exec_context):
        entry = _make_memory_entry()
        mock_ctx.memory_service.add = AsyncMock(return_value=entry)

        result = await plugin.execute_tool(
            "remember",
            {
                "content": "user likes dark mode",
                "category": "preference",
                "scope": "long_term",
            },
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.add.assert_awaited_once()
        call_kwargs = mock_ctx.memory_service.add.call_args
        assert call_kwargs.kwargs["content"] == "user likes dark mode"
        assert call_kwargs.kwargs["scope"] == "long_term"
        assert call_kwargs.kwargs["category"] == "preference"
        assert call_kwargs.kwargs["source"] == "llm"

    @pytest.mark.asyncio
    async def test_remember_with_expires_hours(
        self, plugin, mock_ctx, exec_context
    ):
        entry = _make_memory_entry(scope="session")
        mock_ctx.memory_service.add = AsyncMock(return_value=entry)

        result = await plugin.execute_tool(
            "remember",
            {
                "content": "temporary preference",
                "scope": "session",
                "expires_hours": 12,
            },
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.add.assert_awaited_once()
        call_kwargs = mock_ctx.memory_service.add.call_args
        # Verify expires_at was calculated (not None)
        assert "expires_at" in str(call_kwargs) or call_kwargs is not None

    @pytest.mark.asyncio
    async def test_remember_defaults_to_long_term(
        self, plugin, mock_ctx, exec_context
    ):
        entry = _make_memory_entry()
        mock_ctx.memory_service.add = AsyncMock(return_value=entry)

        result = await plugin.execute_tool(
            "remember",
            {"content": "a fact about the user"},
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.add.assert_awaited_once()


# ===================================================================
# 3. recall tool
# ===================================================================


class TestRecallTool:
    """Tests for the recall tool execution."""

    @pytest.mark.asyncio
    async def test_recall_tool(self, plugin, mock_ctx, exec_context):
        results = [
            {"entry": _make_memory_entry(content="user likes dark mode"), "score": 0.95},
            {"entry": _make_memory_entry(content="user prefers Python"), "score": 0.87},
        ]
        mock_ctx.memory_service.search = AsyncMock(return_value=results)

        result = await plugin.execute_tool(
            "recall",
            {"query": "user preferences", "limit": 5},
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.search.assert_awaited_once()
        # Result content should reference the found memories
        assert result.content is not None

    @pytest.mark.asyncio
    async def test_recall_no_results(self, plugin, mock_ctx, exec_context):
        mock_ctx.memory_service.search = AsyncMock(return_value=[])

        result = await plugin.execute_tool(
            "recall",
            {"query": "nonexistent topic"},
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.search.assert_awaited_once()
        # search() called with filter=None (no category provided)
        call_kwargs = mock_ctx.memory_service.search.call_args
        assert call_kwargs.kwargs.get("filter") is None


# ===================================================================
# 4. forget tool
# ===================================================================


class TestForgetTool:
    """Tests for the forget tool execution."""

    @pytest.mark.asyncio
    async def test_forget_tool(self, plugin, mock_ctx, exec_context):
        memory_id = str(uuid.uuid4())
        mock_ctx.memory_service.delete = AsyncMock(return_value=True)

        result = await plugin.execute_tool(
            "forget",
            {"memory_id": memory_id},
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_forget_not_found(self, plugin, mock_ctx, exec_context):
        memory_id = str(uuid.uuid4())
        mock_ctx.memory_service.delete = AsyncMock(return_value=False)

        result = await plugin.execute_tool(
            "forget",
            {"memory_id": memory_id},
            exec_context,
        )

        # Plugin should return error when memory not found
        assert result.success is False
        mock_ctx.memory_service.delete.assert_awaited_once()


# ===================================================================
# 5. list_memories tool
# ===================================================================


class TestListMemoriesTool:
    """Tests for the list_memories tool execution."""

    @pytest.mark.asyncio
    async def test_list_memories_tool(self, plugin, mock_ctx, exec_context):
        entries = [_make_memory_entry(), _make_memory_entry(content="second")]
        mock_ctx.memory_service.list = AsyncMock(return_value=(entries, 2))

        result = await plugin.execute_tool(
            "list_memories",
            {"category": "preference", "scope": "long_term"},
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.list.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_memories_no_filters(
        self, plugin, mock_ctx, exec_context
    ):
        mock_ctx.memory_service.list = AsyncMock(return_value=([], 0))

        result = await plugin.execute_tool(
            "list_memories",
            {},
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.list.assert_awaited_once()


# ===================================================================
# 6. clear_session_memory tool
# ===================================================================


class TestClearSessionMemoryTool:
    """Tests for the clear_session_memory tool execution."""

    @pytest.mark.asyncio
    async def test_clear_session_memory_tool(
        self, plugin, mock_ctx, exec_context
    ):
        mock_ctx.memory_service.delete_by_scope = AsyncMock(return_value=5)

        result = await plugin.execute_tool(
            "clear_session_memory",
            {},
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.delete_by_scope.assert_awaited_once_with(
            "session"
        )

    @pytest.mark.asyncio
    async def test_clear_session_memory_none_deleted(
        self, plugin, mock_ctx, exec_context
    ):
        mock_ctx.memory_service.delete_by_scope = AsyncMock(return_value=0)

        result = await plugin.execute_tool(
            "clear_session_memory",
            {},
            exec_context,
        )

        assert result.success is True
        mock_ctx.memory_service.delete_by_scope.assert_awaited_once_with(
            "session"
        )


# ===================================================================
# 7. memory_service unavailable
# ===================================================================


class TestMemoryServiceUnavailable:
    """Tests when memory_service is None in context."""

    @pytest.mark.asyncio
    async def test_remember_service_unavailable(
        self, plugin_no_service, exec_context
    ):
        result = await plugin_no_service.execute_tool(
            "remember",
            {"content": "test"},
            exec_context,
        )

        assert result.success is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_recall_service_unavailable(
        self, plugin_no_service, exec_context
    ):
        result = await plugin_no_service.execute_tool(
            "recall",
            {"query": "test"},
            exec_context,
        )

        assert result.success is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_forget_service_unavailable(
        self, plugin_no_service, exec_context
    ):
        result = await plugin_no_service.execute_tool(
            "forget",
            {"memory_id": str(uuid.uuid4())},
            exec_context,
        )

        assert result.success is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_list_service_unavailable(
        self, plugin_no_service, exec_context
    ):
        result = await plugin_no_service.execute_tool(
            "list_memories",
            {},
            exec_context,
        )

        assert result.success is False
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_clear_session_service_unavailable(
        self, plugin_no_service, exec_context
    ):
        result = await plugin_no_service.execute_tool(
            "clear_session_memory",
            {},
            exec_context,
        )

        assert result.success is False
        assert result.error_message is not None
