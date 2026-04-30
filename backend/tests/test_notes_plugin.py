"""Tests for backend.plugins.notes — NotesPlugin."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.plugin_models import ExecutionContext, ToolResult
from backend.services.note_service import NoteEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOTE_ID = str(uuid.uuid4())


def _make_exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="test",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


def _make_note_entry(
    *,
    note_id: str = _NOTE_ID,
    title: str = "Test Note",
    content: str = "# Hello",
    folder_path: str = "",
    tags: list[str] | None = None,
    pinned: bool = False,
) -> NoteEntry:
    """Build a NoteEntry with sensible defaults."""
    return NoteEntry(
        id=note_id,
        title=title,
        content=content,
        folder_path=folder_path,
        tags=tags or ["test"],
        wikilinks=[],
        pinned=pinned,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ctx():
    """Build a mock AppContext with a real ``QdrantBackend`` wrapping a mocked note service."""
    from backend.core.context import AppContext
    from backend.services.knowledge import QdrantBackend

    ctx = MagicMock(spec=AppContext)
    ctx.note_service = AsyncMock()
    ctx.memory_service = None
    ctx.knowledge_backend = QdrantBackend(
        memory_service=None,
        note_service=ctx.note_service,
    )
    ctx.event_bus = AsyncMock()
    ctx.config = MagicMock()
    ctx.config.notes.max_content_chars_llm = 50_000
    return ctx


@pytest.fixture
def exec_context() -> ExecutionContext:
    return _make_exec_ctx()


@pytest.fixture
def plugin(mock_ctx):
    """Return an initialised NotesPlugin with a mocked context."""
    from backend.plugins.notes.plugin import NotesPlugin

    p = NotesPlugin()
    p._ctx = mock_ctx
    p._initialized = True
    return p


@pytest.fixture
def plugin_no_service(mock_ctx):
    """NotesPlugin where the knowledge backend (notes) is unavailable."""
    from backend.plugins.notes.plugin import NotesPlugin

    mock_ctx.note_service = None
    mock_ctx.knowledge_backend = None
    p = NotesPlugin()
    p._ctx = mock_ctx
    p._initialized = True
    return p


# ===================================================================
# 1. Plugin Lifecycle & Attributes
# ===================================================================


class TestNotesPluginLifecycle:
    """Plugin metadata, tool registration, and attributes."""

    def test_plugin_attributes(self):
        from backend.plugins.notes.plugin import NotesPlugin

        p = NotesPlugin()
        assert p.plugin_name == "notes"
        assert p.plugin_version == "1.0.0"
        assert p.plugin_dependencies == []
        assert p.plugin_priority == 85

    def test_get_tools_returns_six(self, plugin):
        tools = plugin.get_tools()
        assert len(tools) == 6

    def test_tool_names(self, plugin):
        names = {t.name for t in plugin.get_tools()}
        assert names == {
            "create_note",
            "read_note",
            "update_note",
            "delete_note",
            "search_notes",
            "list_notes",
        }

    def test_safe_tools_risk_level(self, plugin):
        """create, read, update, search, list are safe with no confirmation."""
        tools = {t.name: t for t in plugin.get_tools()}
        safe_names = [
            "create_note", "read_note", "update_note",
            "search_notes", "list_notes",
        ]
        for name in safe_names:
            assert tools[name].risk_level == "safe", f"{name} risk_level"
            assert tools[name].requires_confirmation is False, (
                f"{name} requires_confirmation"
            )

    def test_delete_note_requires_confirmation(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["delete_note"].risk_level == "medium"
        assert tools["delete_note"].requires_confirmation is True

    def test_create_note_maxlength(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        props = tools["create_note"].parameters["properties"]
        assert props["content"]["maxLength"] == 100_000
        assert props["title"]["maxLength"] == 500

    def test_update_note_maxlength(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        props = tools["update_note"].parameters["properties"]
        assert props["content"]["maxLength"] == 100_000
        assert props["title"]["maxLength"] == 500

    def test_list_notes_required_empty(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["list_notes"].parameters.get("required") == []


# ===================================================================
# 2. create_note
# ===================================================================


class TestCreateNote:
    """Tests for the create_note tool."""

    @pytest.mark.asyncio
    async def test_create_success(self, plugin, mock_ctx, exec_context):
        entry = _make_note_entry()
        mock_ctx.note_service.create = AsyncMock(return_value=entry)

        result = await plugin.execute_tool(
            "create_note",
            {"title": "Test Note", "content": "# Hello", "tags": ["test"]},
            exec_context,
        )

        assert result.success is True
        assert entry.id in result.content
        mock_ctx.note_service.create.assert_awaited_once()
        call_kw = mock_ctx.note_service.create.call_args.kwargs
        assert call_kw["title"] == "Test Note"
        assert call_kw["content"] == "# Hello"
        mock_ctx.event_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_missing_title(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "create_note",
            {"content": "some text"},
            exec_context,
        )
        assert result.success is False
        assert "title" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_create_empty_title(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "create_note",
            {"title": "   ", "content": "some text"},
            exec_context,
        )
        assert result.success is False
        assert "title" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_create_missing_content_defaults_empty(
        self, plugin, mock_ctx, exec_context,
    ):
        """Missing content defaults to empty string — no error."""
        entry = _make_note_entry(content="")
        mock_ctx.note_service.create = AsyncMock(return_value=entry)

        result = await plugin.execute_tool(
            "create_note",
            {"title": "No Body"},
            exec_context,
        )

        assert result.success is True
        call_kw = mock_ctx.note_service.create.call_args.kwargs
        assert call_kw["content"] == ""

    @pytest.mark.asyncio
    async def test_create_content_exceeds_limit(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "create_note",
            {"title": "Big", "content": "x" * 100_001},
            exec_context,
        )
        assert result.success is False
        assert "too long" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_create_service_exception(
        self, plugin, mock_ctx, exec_context,
    ):
        mock_ctx.note_service.create = AsyncMock(
            side_effect=RuntimeError("db error"),
        )

        result = await plugin.execute_tool(
            "create_note",
            {"title": "Fail", "content": "x"},
            exec_context,
        )

        assert result.success is False
        assert "failed" in result.error_message.lower()


# ===================================================================
# 3. read_note
# ===================================================================


class TestReadNote:
    """Tests for the read_note tool."""

    @pytest.mark.asyncio
    async def test_read_success(self, plugin, mock_ctx, exec_context):
        entry = _make_note_entry()
        mock_ctx.note_service.get = AsyncMock(return_value=entry)

        result = await plugin.execute_tool(
            "read_note",
            {"note_id": _NOTE_ID},
            exec_context,
        )

        assert result.success is True
        assert result.content["title"] == "Test Note"
        assert result.content["content"] == "# Hello"
        mock_ctx.note_service.get.assert_awaited_once_with(_NOTE_ID)

    @pytest.mark.asyncio
    async def test_read_truncates_long_content(
        self, plugin, mock_ctx, exec_context,
    ):
        """Content longer than max_content_chars_llm is truncated."""
        long = "a" * 60_000
        entry = _make_note_entry(content=long)
        mock_ctx.note_service.get = AsyncMock(return_value=entry)
        mock_ctx.config.notes.max_content_chars_llm = 1_000

        result = await plugin.execute_tool(
            "read_note",
            {"note_id": _NOTE_ID},
            exec_context,
        )

        assert result.success is True
        assert len(result.content["content"]) < len(long)
        assert result.content["content"].endswith("…(truncated)")

    @pytest.mark.asyncio
    async def test_read_not_found(self, plugin, mock_ctx, exec_context):
        mock_ctx.note_service.get = AsyncMock(return_value=None)

        result = await plugin.execute_tool(
            "read_note",
            {"note_id": _NOTE_ID},
            exec_context,
        )

        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_read_missing_note_id(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "read_note", {}, exec_context,
        )
        assert result.success is False
        assert "note_id" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_read_invalid_uuid(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "read_note",
            {"note_id": "not-a-uuid"},
            exec_context,
        )
        assert result.success is False
        assert "invalid" in result.error_message.lower()


# ===================================================================
# 4. update_note
# ===================================================================


class TestUpdateNote:
    """Tests for the update_note tool."""

    @pytest.mark.asyncio
    async def test_update_partial(self, plugin, mock_ctx, exec_context):
        entry = _make_note_entry(title="Updated")
        mock_ctx.note_service.update = AsyncMock(return_value=entry)

        result = await plugin.execute_tool(
            "update_note",
            {"note_id": _NOTE_ID, "title": "Updated"},
            exec_context,
        )

        assert result.success is True
        assert _NOTE_ID in result.content
        mock_ctx.note_service.update.assert_awaited_once()
        call_args = mock_ctx.note_service.update.call_args
        assert call_args.kwargs["title"] == "Updated"
        mock_ctx.event_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_not_found(self, plugin, mock_ctx, exec_context):
        mock_ctx.note_service.update = AsyncMock(return_value=None)

        result = await plugin.execute_tool(
            "update_note",
            {"note_id": _NOTE_ID, "title": "Updated"},
            exec_context,
        )

        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_update_missing_note_id(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "update_note", {"title": "Updated"}, exec_context,
        )
        assert result.success is False
        assert "note_id" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_update_invalid_uuid(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "update_note",
            {"note_id": "bad-id", "title": "X"},
            exec_context,
        )
        assert result.success is False
        assert "invalid" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_update_content_exceeds_limit(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "update_note",
            {"note_id": _NOTE_ID, "content": "x" * 100_001},
            exec_context,
        )
        assert result.success is False
        assert "too long" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_update_service_exception(
        self, plugin, mock_ctx, exec_context,
    ):
        mock_ctx.note_service.update = AsyncMock(
            side_effect=RuntimeError("db error"),
        )

        result = await plugin.execute_tool(
            "update_note",
            {"note_id": _NOTE_ID, "title": "X"},
            exec_context,
        )

        assert result.success is False
        assert "failed" in result.error_message.lower()


# ===================================================================
# 5. delete_note
# ===================================================================


class TestDeleteNote:
    """Tests for the delete_note tool."""

    @pytest.mark.asyncio
    async def test_delete_success(self, plugin, mock_ctx, exec_context):
        mock_ctx.note_service.delete = AsyncMock(return_value=True)

        result = await plugin.execute_tool(
            "delete_note",
            {"note_id": _NOTE_ID},
            exec_context,
        )

        assert result.success is True
        assert "deleted" in result.content.lower()
        mock_ctx.note_service.delete.assert_awaited_once_with(_NOTE_ID)
        mock_ctx.event_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_not_found(self, plugin, mock_ctx, exec_context):
        mock_ctx.note_service.delete = AsyncMock(return_value=False)

        result = await plugin.execute_tool(
            "delete_note",
            {"note_id": _NOTE_ID},
            exec_context,
        )

        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_delete_missing_note_id(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "delete_note", {}, exec_context,
        )
        assert result.success is False
        assert "note_id" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_delete_invalid_uuid(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "delete_note",
            {"note_id": "nope"},
            exec_context,
        )
        assert result.success is False
        assert "invalid" in result.error_message.lower()


# ===================================================================
# 6. search_notes
# ===================================================================


class TestSearchNotes:
    """Tests for the search_notes tool."""

    @pytest.mark.asyncio
    async def test_search_with_results(
        self, plugin, mock_ctx, exec_context,
    ):
        results = [
            {"entry": _make_note_entry(title="Recipe A"), "score": 0.95},
            {"entry": _make_note_entry(title="Recipe B"), "score": 0.8},
        ]
        mock_ctx.note_service.search = AsyncMock(return_value=results)

        result = await plugin.execute_tool(
            "search_notes",
            {"query": "recipe"},
            exec_context,
        )

        assert result.success is True
        data = result.content
        assert data["count"] == 2
        assert data["query"] == "recipe"
        assert len(data["notes"]) == 2
        mock_ctx.note_service.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_empty_results(
        self, plugin, mock_ctx, exec_context,
    ):
        mock_ctx.note_service.search = AsyncMock(return_value=[])

        result = await plugin.execute_tool(
            "search_notes",
            {"query": "nonexistent"},
            exec_context,
        )

        assert result.success is True
        assert result.content["count"] == 0
        assert result.content["notes"] == []

    @pytest.mark.asyncio
    async def test_search_missing_query(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "search_notes", {}, exec_context,
        )
        assert result.success is False
        assert "query" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_search_dates_are_strings(
        self, plugin, mock_ctx, exec_context,
    ):
        """updated_at is returned as-is (string), not .isoformat()."""
        entry = _make_note_entry()
        mock_ctx.note_service.search = AsyncMock(
            return_value=[{"entry": entry, "score": 1.0}],
        )

        result = await plugin.execute_tool(
            "search_notes",
            {"query": "hello"},
            exec_context,
        )

        note = result.content["notes"][0]
        assert isinstance(note["updated_at"], str)
        assert note["updated_at"] == "2026-01-01T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_search_with_folder_and_tags(
        self, plugin, mock_ctx, exec_context,
    ):
        mock_ctx.note_service.search = AsyncMock(return_value=[])

        await plugin.execute_tool(
            "search_notes",
            {"query": "q", "folder": "recipes", "tags": ["italian"]},
            exec_context,
        )

        call_kw = mock_ctx.note_service.search.call_args.kwargs
        assert call_kw["folder"] == "recipes"
        assert call_kw["tags"] == ["italian"]

    @pytest.mark.asyncio
    async def test_search_service_exception(
        self, plugin, mock_ctx, exec_context,
    ):
        mock_ctx.note_service.search = AsyncMock(
            side_effect=RuntimeError("boom"),
        )

        result = await plugin.execute_tool(
            "search_notes",
            {"query": "x"},
            exec_context,
        )

        assert result.success is False
        assert "failed" in result.error_message.lower()


# ===================================================================
# 7. list_notes
# ===================================================================


class TestListNotes:
    """Tests for the list_notes tool."""

    @pytest.mark.asyncio
    async def test_list_with_results(
        self, plugin, mock_ctx, exec_context,
    ):
        entries = [_make_note_entry(), _make_note_entry(title="Second")]
        mock_ctx.note_service.list = AsyncMock(
            return_value=(entries, 2),
        )

        result = await plugin.execute_tool(
            "list_notes", {}, exec_context,
        )

        assert result.success is True
        data = result.content
        assert data["total"] == 2
        assert data["count"] == 2
        assert len(data["notes"]) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, plugin, mock_ctx, exec_context):
        mock_ctx.note_service.list = AsyncMock(return_value=([], 0))

        result = await plugin.execute_tool(
            "list_notes", {}, exec_context,
        )

        assert result.success is True
        assert result.content["count"] == 0
        assert result.content["notes"] == []

    @pytest.mark.asyncio
    async def test_list_with_folder_and_tags(
        self, plugin, mock_ctx, exec_context,
    ):
        mock_ctx.note_service.list = AsyncMock(return_value=([], 0))

        await plugin.execute_tool(
            "list_notes",
            {"folder": "work", "tags": ["urgent"], "pinned_only": True},
            exec_context,
        )

        call_kw = mock_ctx.note_service.list.call_args.kwargs
        assert call_kw["folder"] == "work"
        assert call_kw["tags"] == ["urgent"]
        assert call_kw["pinned_only"] is True

    @pytest.mark.asyncio
    async def test_list_dates_are_strings(
        self, plugin, mock_ctx, exec_context,
    ):
        """updated_at is returned as-is (string), not .isoformat()."""
        entry = _make_note_entry()
        mock_ctx.note_service.list = AsyncMock(
            return_value=([entry], 1),
        )

        result = await plugin.execute_tool(
            "list_notes", {}, exec_context,
        )

        note = result.content["notes"][0]
        assert isinstance(note["updated_at"], str)
        assert note["updated_at"] == "2026-01-01T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_list_service_exception(
        self, plugin, mock_ctx, exec_context,
    ):
        mock_ctx.note_service.list = AsyncMock(
            side_effect=RuntimeError("db error"),
        )

        result = await plugin.execute_tool(
            "list_notes", {}, exec_context,
        )

        assert result.success is False
        assert "failed" in result.error_message.lower()


# ===================================================================
# 8. note_service unavailable
# ===================================================================


class TestNoteServiceUnavailable:
    """All tools return error when note_service is None."""

    @pytest.mark.asyncio
    async def test_create_unavailable(
        self, plugin_no_service, exec_context,
    ):
        result = await plugin_no_service.execute_tool(
            "create_note",
            {"title": "T", "content": "C"},
            exec_context,
        )
        assert result.success is False
        assert "not available" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_read_unavailable(
        self, plugin_no_service, exec_context,
    ):
        result = await plugin_no_service.execute_tool(
            "read_note",
            {"note_id": _NOTE_ID},
            exec_context,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_delete_unavailable(
        self, plugin_no_service, exec_context,
    ):
        result = await plugin_no_service.execute_tool(
            "delete_note",
            {"note_id": _NOTE_ID},
            exec_context,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_search_unavailable(
        self, plugin_no_service, exec_context,
    ):
        result = await plugin_no_service.execute_tool(
            "search_notes",
            {"query": "x"},
            exec_context,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_list_unavailable(
        self, plugin_no_service, exec_context,
    ):
        result = await plugin_no_service.execute_tool(
            "list_notes", {}, exec_context,
        )
        assert result.success is False


# ===================================================================
# 9. Unknown tool
# ===================================================================


class TestUnknownTool:
    """execute_tool returns error for unknown tool names."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self, plugin, exec_context):
        result = await plugin.execute_tool(
            "nonexistent_tool", {}, exec_context,
        )
        assert result.success is False
        assert "unknown" in result.error_message.lower()
