"""Tests for the Continuum plugin's note CRUD tools.

These six tools — ``create_note``, ``read_note``, ``update_note``,
``delete_note``, ``search_notes``, ``list_notes`` — route through the
application's :class:`KnowledgeBackend` (``kind="note"``), which delegates
note storage to Continuum. The backend is replaced by an ``AsyncMock`` so
the tests exercise validation, markdown rendering, payload shaping and
event emission without a live server.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.plugin_models import ExecutionContext
from backend.services.knowledge import KnowledgeDoc, KnowledgeHit

_NOTE_ID = str(uuid.uuid4())

_NOTE_TOOLS = {
    "create_note",
    "read_note",
    "update_note",
    "delete_note",
    "search_notes",
    "list_notes",
}


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="s", conversation_id="c", execution_id="e",
    )


def _make_doc(
    *,
    note_id: str = _NOTE_ID,
    title: str = "Test Note",
    content: str = "<h1>Hello</h1>",
    folder_path: str = "",
    tags: list[str] | None = None,
    pinned: bool = False,
) -> KnowledgeDoc:
    """Build a note ``KnowledgeDoc`` with sensible defaults."""
    return KnowledgeDoc(
        id=note_id,
        kind="note",
        content=content,
        title=title,
        tags=tags or ["test"],
        metadata={
            "folder_path": folder_path,
            "pinned": pinned,
            "wikilinks": [],
        },
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def mock_ctx():
    """Mock AppContext with a mocked knowledge service and event bus."""
    ctx = MagicMock()
    ctx.knowledge_service = AsyncMock()
    ctx.event_bus = AsyncMock()
    ctx.config = MagicMock()
    ctx.config.continuum.note_max_content_chars_llm = 50_000
    return ctx


@pytest.fixture
def plugin(mock_ctx):
    """Return an initialised ContinuumPlugin with a mocked context/client."""
    from backend.plugins.continuum.plugin import ContinuumPlugin

    p = ContinuumPlugin()
    p._ctx = mock_ctx
    p._initialized = True
    # A non-None client passes the plugin's availability guard; note CRUD
    # itself goes through the knowledge backend, not this client.
    p._client = AsyncMock()
    return p


# ===================================================================
# 1. Tool registration
# ===================================================================


class TestNoteToolDefinitions:
    """Note tool metadata exposed through the Continuum plugin."""

    def test_all_six_note_tools_present(self, plugin):
        names = {t.name for t in plugin.get_tools()}
        assert _NOTE_TOOLS <= names

    def test_safe_tools_risk_level(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        for name in (
            "create_note", "read_note", "update_note",
            "search_notes", "list_notes",
        ):
            assert tools[name].risk_level == "safe", f"{name} risk_level"
            assert tools[name].requires_confirmation is False, name

    def test_delete_note_requires_confirmation(self, plugin):
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["delete_note"].risk_level == "medium"
        assert tools["delete_note"].requires_confirmation is True

    def test_create_note_maxlength(self, plugin):
        props = {
            t.name: t for t in plugin.get_tools()
        }["create_note"].parameters["properties"]
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
    async def test_create_success(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.create = AsyncMock(return_value=_make_doc())

        result = await plugin.execute_tool(
            "create_note",
            {"title": "Test Note", "content": "# Hello", "tags": ["test"]},
            _exec_ctx(),
        )

        assert result.success is True
        assert _NOTE_ID in result.content
        payload = mock_ctx.knowledge_service.create.call_args.args[0]
        assert payload.kind == "note"
        assert payload.title == "Test Note"
        # Markdown is rendered to editor-compatible HTML before storage.
        assert payload.content == "<h1>Hello</h1>"
        mock_ctx.event_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_renders_markdown_to_html(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.create = AsyncMock(return_value=_make_doc())

        await plugin.execute_tool(
            "create_note",
            {
                "title": "Guide",
                "content": (
                    "## Section\n\nPara with **bold** and `code`.\n\n"
                    "- one\n- two\n\n```c\nint main(){}\n```"
                ),
            },
            _exec_ctx(),
        )

        html = mock_ctx.knowledge_service.create.call_args.args[0].content
        assert "<h2>Section</h2>" in html
        assert "<strong>bold</strong>" in html
        assert "<code>code</code>" in html
        assert "<ul>" in html
        assert '<code class="language-c">' in html
        assert "## Section" not in html
        assert "**bold**" not in html

    @pytest.mark.asyncio
    async def test_create_missing_title(self, plugin):
        result = await plugin.execute_tool(
            "create_note", {"content": "some text"}, _exec_ctx(),
        )
        assert result.success is False
        assert "title" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_create_empty_title(self, plugin):
        result = await plugin.execute_tool(
            "create_note", {"title": "   ", "content": "x"}, _exec_ctx(),
        )
        assert result.success is False
        assert "title" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_create_content_exceeds_limit(self, plugin):
        result = await plugin.execute_tool(
            "create_note",
            {"title": "Big", "content": "x" * 100_001},
            _exec_ctx(),
        )
        assert result.success is False
        assert "too long" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_create_backend_exception(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.create = AsyncMock(
            side_effect=RuntimeError("db error"),
        )
        result = await plugin.execute_tool(
            "create_note", {"title": "Fail", "content": "x"}, _exec_ctx(),
        )
        assert result.success is False
        assert "failed" in result.error_message.lower()


# ===================================================================
# 3. read_note
# ===================================================================


class TestReadNote:
    """Tests for the read_note tool."""

    @pytest.mark.asyncio
    async def test_read_success(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.get = AsyncMock(return_value=_make_doc())

        result = await plugin.execute_tool(
            "read_note", {"note_id": _NOTE_ID}, _exec_ctx(),
        )

        assert result.success is True
        assert result.content["title"] == "Test Note"
        assert result.content["content"] == "<h1>Hello</h1>"
        mock_ctx.knowledge_service.get.assert_awaited_once_with(
            _NOTE_ID, kind="note",
        )

    @pytest.mark.asyncio
    async def test_read_truncates_long_content(self, plugin, mock_ctx):
        long = "a" * 60_000
        mock_ctx.knowledge_service.get = AsyncMock(
            return_value=_make_doc(content=long),
        )
        mock_ctx.config.continuum.note_max_content_chars_llm = 1_000

        result = await plugin.execute_tool(
            "read_note", {"note_id": _NOTE_ID}, _exec_ctx(),
        )

        assert result.success is True
        assert len(result.content["content"]) < len(long)
        assert result.content["content"].endswith("…(truncated)")

    @pytest.mark.asyncio
    async def test_read_not_found(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.get = AsyncMock(return_value=None)
        result = await plugin.execute_tool(
            "read_note", {"note_id": _NOTE_ID}, _exec_ctx(),
        )
        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_read_missing_note_id(self, plugin):
        result = await plugin.execute_tool("read_note", {}, _exec_ctx())
        assert result.success is False
        assert "note_id" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_read_invalid_uuid(self, plugin):
        result = await plugin.execute_tool(
            "read_note", {"note_id": "not-a-uuid"}, _exec_ctx(),
        )
        assert result.success is False
        assert "invalid" in result.error_message.lower()


# ===================================================================
# 4. update_note
# ===================================================================


class TestUpdateNote:
    """Tests for the update_note tool."""

    @pytest.mark.asyncio
    async def test_update_partial(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.update = AsyncMock(
            return_value=_make_doc(title="Updated"),
        )

        result = await plugin.execute_tool(
            "update_note", {"note_id": _NOTE_ID, "title": "Updated"},
            _exec_ctx(),
        )

        assert result.success is True
        assert _NOTE_ID in result.content
        call = mock_ctx.knowledge_service.update.call_args
        assert call.args[0] == _NOTE_ID
        assert call.args[1].title == "Updated"
        assert call.kwargs["kind"] == "note"
        mock_ctx.event_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_renders_markdown(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.update = AsyncMock(return_value=_make_doc())
        await plugin.execute_tool(
            "update_note",
            {"note_id": _NOTE_ID, "content": "# Title"},
            _exec_ctx(),
        )
        patch = mock_ctx.knowledge_service.update.call_args.args[1]
        assert patch.content == "<h1>Title</h1>"

    @pytest.mark.asyncio
    async def test_update_not_found(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.update = AsyncMock(return_value=None)
        result = await plugin.execute_tool(
            "update_note", {"note_id": _NOTE_ID, "title": "X"}, _exec_ctx(),
        )
        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_update_missing_note_id(self, plugin):
        result = await plugin.execute_tool(
            "update_note", {"title": "X"}, _exec_ctx(),
        )
        assert result.success is False
        assert "note_id" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_update_invalid_uuid(self, plugin):
        result = await plugin.execute_tool(
            "update_note", {"note_id": "bad", "title": "X"}, _exec_ctx(),
        )
        assert result.success is False
        assert "invalid" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_update_content_exceeds_limit(self, plugin):
        result = await plugin.execute_tool(
            "update_note",
            {"note_id": _NOTE_ID, "content": "x" * 100_001},
            _exec_ctx(),
        )
        assert result.success is False
        assert "too long" in result.error_message.lower()


# ===================================================================
# 5. delete_note
# ===================================================================


class TestDeleteNote:
    """Tests for the delete_note tool."""

    @pytest.mark.asyncio
    async def test_delete_success(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.delete = AsyncMock(return_value=True)

        result = await plugin.execute_tool(
            "delete_note", {"note_id": _NOTE_ID}, _exec_ctx(),
        )

        assert result.success is True
        assert "deleted" in result.content.lower()
        mock_ctx.knowledge_service.delete.assert_awaited_once_with(
            _NOTE_ID, kind="note",
        )
        mock_ctx.event_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_not_found(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.delete = AsyncMock(return_value=False)
        result = await plugin.execute_tool(
            "delete_note", {"note_id": _NOTE_ID}, _exec_ctx(),
        )
        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_delete_invalid_uuid(self, plugin):
        result = await plugin.execute_tool(
            "delete_note", {"note_id": "nope"}, _exec_ctx(),
        )
        assert result.success is False
        assert "invalid" in result.error_message.lower()


# ===================================================================
# 6. search_notes / list_notes
# ===================================================================


class TestSearchNotes:
    """Tests for the search_notes tool."""

    @pytest.mark.asyncio
    async def test_search_with_results(self, plugin, mock_ctx):
        hits = [
            KnowledgeHit(doc=_make_doc(title="Recipe A"), score=0.95),
            KnowledgeHit(doc=_make_doc(title="Recipe B"), score=0.8),
        ]
        mock_ctx.knowledge_service.search = AsyncMock(return_value=hits)

        result = await plugin.execute_tool(
            "search_notes", {"query": "recipe"}, _exec_ctx(),
        )

        assert result.success is True
        assert result.content["count"] == 2
        assert result.content["query"] == "recipe"
        mock_ctx.knowledge_service.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_empty_results(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.search = AsyncMock(return_value=[])
        result = await plugin.execute_tool(
            "search_notes", {"query": "nothing"}, _exec_ctx(),
        )
        assert result.success is True
        assert result.content["count"] == 0
        assert result.content["notes"] == []

    @pytest.mark.asyncio
    async def test_search_missing_query(self, plugin):
        result = await plugin.execute_tool("search_notes", {}, _exec_ctx())
        assert result.success is False
        assert "query" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_search_dates_are_strings(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.search = AsyncMock(
            return_value=[KnowledgeHit(doc=_make_doc(), score=1.0)],
        )
        result = await plugin.execute_tool(
            "search_notes", {"query": "hello"}, _exec_ctx(),
        )
        note = result.content["notes"][0]
        assert note["updated_at"] == "2026-01-01T00:00:00+00:00"

    @pytest.mark.asyncio
    async def test_search_passes_folder_and_tags(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.search = AsyncMock(return_value=[])
        await plugin.execute_tool(
            "search_notes",
            {"query": "q", "folder": "recipes", "tags": ["italian"]},
            _exec_ctx(),
        )
        filters = mock_ctx.knowledge_service.search.call_args.kwargs["filters"]
        assert filters["folder"] == "recipes"
        assert filters["tags"] == ["italian"]


class TestListNotes:
    """Tests for the list_notes tool."""

    @pytest.mark.asyncio
    async def test_list_with_results(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.list = AsyncMock(
            return_value=([_make_doc(), _make_doc()], 2),
        )
        result = await plugin.execute_tool("list_notes", {}, _exec_ctx())
        assert result.success is True
        assert result.content["total"] == 2
        assert result.content["count"] == 2

    @pytest.mark.asyncio
    async def test_list_empty(self, plugin, mock_ctx):
        mock_ctx.knowledge_service.list = AsyncMock(return_value=([], 0))
        result = await plugin.execute_tool("list_notes", {}, _exec_ctx())
        assert result.success is True
        assert result.content["count"] == 0


# ===================================================================
# 7. Backend unavailable
# ===================================================================


@pytest.mark.asyncio
async def test_note_tool_without_knowledge_backend(plugin, mock_ctx):
    """With no knowledge backend, note tools report unavailability."""
    mock_ctx.knowledge_service = None
    result = await plugin.execute_tool(
        "list_notes", {}, _exec_ctx(),
    )
    assert result.success is False
    assert "not available" in result.error_message.lower()
