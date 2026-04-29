"""Comprehensive tests for backend.services.note_service.NoteService.

Covers CRUD, FTS5 search, folders, helpers, edge-cases and bug-fix
scenarios.  Each test gets its own in-memory/temp SQLite DB for
full isolation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.core.config import NotesConfig
from backend.services.note_service import (
    NoteEntry,
    NoteService,
    _LIST_SEP,
    _extract_wikilinks,
    _sanitize_tags,
)


# ----------------------------------------------------------------------- #
# Helpers / fixtures
# ----------------------------------------------------------------------- #

def _make_config(**overrides) -> NotesConfig:
    """Return a ``NotesConfig`` with embeddings disabled by default."""
    defaults = {
        "enabled": True,
        "embedding_enabled": False,
        "db_path": "notes.db",
    }
    defaults.update(overrides)
    return NotesConfig(**defaults)


@pytest.fixture
async def note_svc(tmp_path: Path, mock_qdrant_service, mock_embedding_client):
    """Create, initialise, yield, and close a NoteService per test."""
    db_file = tmp_path / "notes.db"
    cfg = _make_config(db_path=str(db_file))
    svc = NoteService(
        config=cfg,
        qdrant_service=mock_qdrant_service,
        embedding_client=mock_embedding_client,
    )
    await svc.initialize()
    yield svc
    await svc.close()


# ----------------------------------------------------------------------- #
# Module-level helpers
# ----------------------------------------------------------------------- #

class TestSanitizeTags:
    """Tests for ``_sanitize_tags``."""

    def test_basic(self):
        assert _sanitize_tags(["a", "b", "c"]) == ["a", "b", "c"]

    def test_deduplication_case_sensitive(self):
        """Dedup is case-sensitive: 'a' and 'A' are both kept."""
        assert _sanitize_tags(["a", "b", "a", "B"]) == ["a", "b", "B"]

    def test_strips_commas(self):
        """Commas inside a tag string are removed."""
        assert _sanitize_tags(["C++,Java"]) == ["C++Java"]

    def test_strips_list_separator(self):
        assert _sanitize_tags([f"foo{_LIST_SEP}bar"]) == ["foobar"]

    def test_strips_whitespace(self):
        assert _sanitize_tags(["  hello  ", "world "]) == ["hello", "world"]

    def test_empty_after_clean_skipped(self):
        assert _sanitize_tags([",", "", "  "]) == []

    def test_preserves_order(self):
        assert _sanitize_tags(["z", "a", "m"]) == ["z", "a", "m"]

    def test_empty_input(self):
        assert _sanitize_tags([]) == []


class TestExtractWikilinks:
    """Tests for ``_extract_wikilinks``."""

    def test_simple(self):
        assert _extract_wikilinks("See [[Foo]] and [[Bar]]") == ["Foo", "Bar"]

    def test_with_alias(self):
        """``[[Target|alias]]`` → only target is extracted."""
        assert _extract_wikilinks("[[Page|display text]]") == ["Page"]

    def test_deduplication(self):
        assert _extract_wikilinks("[[A]] then [[A]]") == ["A"]

    def test_no_links(self):
        assert _extract_wikilinks("plain text") == []

    def test_wikilink_with_comma(self):
        """Bug-fix: ``[[Hello, World]]`` → single target, not split."""
        result = _extract_wikilinks("Link to [[Hello, World]]")
        assert result == ["Hello, World"]


class TestListSep:
    """Ensure the module-level separator constant is correct."""

    def test_is_unit_separator(self):
        assert _LIST_SEP == "\x1f"


# ----------------------------------------------------------------------- #
# NoteEntry
# ----------------------------------------------------------------------- #

class TestNoteEntry:
    """Tests for the NoteEntry data class."""

    def test_to_dict_roundtrip(self):
        entry = NoteEntry(
            id="abc-123",
            title="Test",
            content="body",
            folder_path="docs",
            tags=["a", "b"],
            wikilinks=["Foo"],
            pinned=True,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-02T00:00:00+00:00",
        )
        d = entry.to_dict()
        assert d["id"] == "abc-123"
        assert d["title"] == "Test"
        assert d["content"] == "body"
        assert d["folder_path"] == "docs"
        assert d["tags"] == ["a", "b"]
        assert d["wikilinks"] == ["Foo"]
        assert d["pinned"] is True
        assert d["created_at"] == "2026-01-01T00:00:00+00:00"
        assert d["updated_at"] == "2026-01-02T00:00:00+00:00"

    def test_slots(self):
        assert hasattr(NoteEntry, "__slots__")


# ----------------------------------------------------------------------- #
# Lifecycle
# ----------------------------------------------------------------------- #

class TestLifecycle:
    """Constructor, initialize, close, and pre-init guard."""

    @pytest.mark.asyncio
    async def test_initialize_creates_db(
        self, tmp_path: Path, mock_qdrant_service, mock_embedding_client,
    ):
        db_file = tmp_path / "test.db"
        cfg = _make_config(db_path=str(db_file))
        svc = NoteService(
            config=cfg,
            qdrant_service=mock_qdrant_service,
            embedding_client=mock_embedding_client,
        )
        await svc.initialize()
        assert db_file.exists()
        await svc.close()

    @pytest.mark.asyncio
    async def test_double_initialize_is_idempotent(self, note_svc: NoteService):
        """Calling initialize() twice should not raise."""
        await note_svc.initialize()

    @pytest.mark.asyncio
    async def test_crud_before_initialize_raises(
        self, tmp_path: Path, mock_qdrant_service, mock_embedding_client,
    ):
        db_file = tmp_path / "test.db"
        cfg = _make_config(db_path=str(db_file))
        svc = NoteService(
            config=cfg,
            qdrant_service=mock_qdrant_service,
            embedding_client=mock_embedding_client,
        )
        with pytest.raises(RuntimeError, match="not initialised"):
            await svc.create("t", "c")

    @pytest.mark.asyncio
    async def test_get_before_initialize_raises(
        self, tmp_path: Path, mock_qdrant_service, mock_embedding_client,
    ):
        cfg = _make_config(db_path=str(tmp_path / "x.db"))
        svc = NoteService(
            config=cfg,
            qdrant_service=mock_qdrant_service,
            embedding_client=mock_embedding_client,
        )
        with pytest.raises(RuntimeError):
            await svc.get("some-id")

    @pytest.mark.asyncio
    async def test_close_idempotent(
        self, tmp_path: Path, mock_qdrant_service, mock_embedding_client,
    ):
        db_file = tmp_path / "test.db"
        cfg = _make_config(db_path=str(db_file))
        svc = NoteService(
            config=cfg,
            qdrant_service=mock_qdrant_service,
            embedding_client=mock_embedding_client,
        )
        await svc.initialize()
        await svc.close()
        await svc.close()  # should not raise


# ----------------------------------------------------------------------- #
# CRUD: create / get
# ----------------------------------------------------------------------- #

class TestCreate:
    """Tests for ``NoteService.create``."""

    @pytest.mark.asyncio
    async def test_create_returns_entry(self, note_svc: NoteService):
        entry = await note_svc.create("Title", "Body text")
        assert isinstance(entry, NoteEntry)
        assert entry.title == "Title"
        assert entry.content == "Body text"
        assert entry.folder_path == ""
        assert entry.tags == []
        assert entry.pinned is False
        assert entry.id  # UUID assigned

    @pytest.mark.asyncio
    async def test_create_with_folder_and_tags(self, note_svc: NoteService):
        entry = await note_svc.create(
            "T", "C", folder_path="work/projects", tags=["python", "ai"],
        )
        assert entry.folder_path == "work/projects"
        assert entry.tags == ["python", "ai"]

    @pytest.mark.asyncio
    async def test_create_extracts_wikilinks(self, note_svc: NoteService):
        entry = await note_svc.create("T", "See [[PageA]] and [[PageB]]")
        assert entry.wikilinks == ["PageA", "PageB"]

    @pytest.mark.asyncio
    async def test_wikilinks_with_commas(self, note_svc: NoteService):
        """Bug-fix: wikilinks containing commas must not be split."""
        entry = await note_svc.create("T", "Link to [[Hello, World]]")
        assert entry.wikilinks == ["Hello, World"]
        # Verify persisted correctly via get()
        fetched = await note_svc.get(entry.id)
        assert fetched is not None
        assert fetched.wikilinks == ["Hello, World"]

    @pytest.mark.asyncio
    async def test_create_persists_to_db(self, note_svc: NoteService):
        entry = await note_svc.create("Persisted", "content")
        fetched = await note_svc.get(entry.id)
        assert fetched is not None
        assert fetched.title == "Persisted"


class TestGet:
    """Tests for ``NoteService.get``."""

    @pytest.mark.asyncio
    async def test_get_existing(self, note_svc: NoteService):
        entry = await note_svc.create("X", "Y")
        got = await note_svc.get(entry.id)
        assert got is not None
        assert got.id == entry.id

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, note_svc: NoteService):
        assert await note_svc.get("nonexistent-uuid") is None


# ----------------------------------------------------------------------- #
# CRUD: update
# ----------------------------------------------------------------------- #

class TestUpdate:
    """Tests for ``NoteService.update``."""

    @pytest.mark.asyncio
    async def test_update_title(self, note_svc: NoteService):
        entry = await note_svc.create("Old", "content")
        updated = await note_svc.update(entry.id, title="New")
        assert updated is not None
        assert updated.title == "New"
        assert updated.content == "content"  # unchanged

    @pytest.mark.asyncio
    async def test_update_content(self, note_svc: NoteService):
        entry = await note_svc.create("T", "old body")
        updated = await note_svc.update(entry.id, content="new body")
        assert updated is not None
        assert updated.content == "new body"

    @pytest.mark.asyncio
    async def test_update_folder_path(self, note_svc: NoteService):
        entry = await note_svc.create("T", "C", folder_path="a")
        updated = await note_svc.update(entry.id, folder_path="b")
        assert updated is not None
        assert updated.folder_path == "b"

    @pytest.mark.asyncio
    async def test_update_tags(self, note_svc: NoteService):
        entry = await note_svc.create("T", "C", tags=["old"])
        updated = await note_svc.update(entry.id, tags=["new", "tags"])
        assert updated is not None
        assert updated.tags == ["new", "tags"]

    @pytest.mark.asyncio
    async def test_update_pinned(self, note_svc: NoteService):
        entry = await note_svc.create("T", "C")
        updated = await note_svc.update(entry.id, pinned=True)
        assert updated is not None
        assert updated.pinned is True

    @pytest.mark.asyncio
    async def test_update_preserves_created_at(self, note_svc: NoteService):
        """Bug-fix: ``created_at`` must not change on update."""
        entry = await note_svc.create("T", "C")
        original_created = entry.created_at

        # Small delay so updated_at differs
        await asyncio.sleep(0.05)

        updated = await note_svc.update(entry.id, title="Changed")
        assert updated is not None
        assert updated.created_at == original_created
        assert updated.updated_at > original_created

    @pytest.mark.asyncio
    async def test_update_nonexistent_returns_none(self, note_svc: NoteService):
        assert await note_svc.update("nonexistent-id", title="X") is None

    @pytest.mark.asyncio
    async def test_update_wikilinks_recalculated(self, note_svc: NoteService):
        entry = await note_svc.create("T", "no links")
        assert entry.wikilinks == []
        updated = await note_svc.update(entry.id, content="now [[Link]]")
        assert updated is not None
        assert updated.wikilinks == ["Link"]


# ----------------------------------------------------------------------- #
# CRUD: delete
# ----------------------------------------------------------------------- #

class TestDelete:
    """Tests for ``NoteService.delete``."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, note_svc: NoteService):
        entry = await note_svc.create("T", "C")
        assert await note_svc.delete(entry.id) is True
        assert await note_svc.get(entry.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, note_svc: NoteService):
        assert await note_svc.delete("nonexistent-uuid") is False


# ----------------------------------------------------------------------- #
# list
# ----------------------------------------------------------------------- #

class TestList:
    """Tests for ``NoteService.list``."""

    @pytest.mark.asyncio
    async def test_list_empty(self, note_svc: NoteService):
        entries, total = await note_svc.list()
        assert entries == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_all(self, note_svc: NoteService):
        await note_svc.create("A", "a")
        await note_svc.create("B", "b")
        entries, total = await note_svc.list()
        assert total == 2
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_list_folder_filter(self, note_svc: NoteService):
        await note_svc.create("A", "a", folder_path="docs")
        await note_svc.create("B", "b", folder_path="work")
        entries, total = await note_svc.list(folder="docs")
        assert total == 1
        assert entries[0].folder_path == "docs"

    @pytest.mark.asyncio
    async def test_list_pinned_only(self, note_svc: NoteService):
        e1 = await note_svc.create("A", "a")
        await note_svc.create("B", "b")
        await note_svc.update(e1.id, pinned=True)
        entries, total = await note_svc.list(pinned_only=True)
        assert total == 1
        assert entries[0].id == e1.id

    @pytest.mark.asyncio
    async def test_list_pagination(self, note_svc: NoteService):
        for i in range(5):
            await note_svc.create(f"Note {i}", f"content {i}")
        entries, total = await note_svc.list(limit=2, offset=0)
        assert total == 5
        assert len(entries) == 2
        entries2, total2 = await note_svc.list(limit=2, offset=2)
        assert total2 == 5
        assert len(entries2) == 2
        # No overlap
        ids1 = {e.id for e in entries}
        ids2 = {e.id for e in entries2}
        assert ids1.isdisjoint(ids2)

    @pytest.mark.asyncio
    async def test_list_case_insensitive_tag_filter(self, note_svc: NoteService):
        """Bug-fix: tag filter must be case-insensitive."""
        await note_svc.create("T", "C", tags=["Python"])
        entries, total = await note_svc.list(tags=["python"])
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_like_escaping(self, note_svc: NoteService):
        """Bug-fix: LIKE wildcards in tag names must be escaped."""
        await note_svc.create("T", "C", tags=["100%_done"])
        # Should match exact tag, not a LIKE wildcard
        entries, total = await note_svc.list(tags=["100%_done"])
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_tag_filter_no_false_positive(self, note_svc: NoteService):
        """Tag filter should not match partial tags."""
        await note_svc.create("T", "C", tags=["java"])
        entries, total = await note_svc.list(tags=["javascript"])
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_multiple_folders(self, note_svc: NoteService):
        await note_svc.create("A", "a", folder_path="docs")
        await note_svc.create("B", "b", folder_path="docs")
        await note_svc.create("C", "c", folder_path="work")
        await note_svc.create("D", "d", folder_path="")

        entries_docs, total_docs = await note_svc.list(folder="docs")
        assert total_docs == 2
        entries_work, total_work = await note_svc.list(folder="work")
        assert total_work == 1
        entries_root, total_root = await note_svc.list(folder="")
        assert total_root == 1


# ----------------------------------------------------------------------- #
# search (FTS5)
# ----------------------------------------------------------------------- #

class TestSearch:
    """Tests for ``NoteService.search`` (FTS5 text search)."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, note_svc: NoteService):
        await note_svc.create("T", "content with words")
        assert await note_svc.search("") == []

    @pytest.mark.asyncio
    async def test_whitespace_query_returns_empty(self, note_svc: NoteService):
        await note_svc.create("T", "content with words")
        assert await note_svc.search("   ") == []

    @pytest.mark.asyncio
    async def test_search_finds_by_title(self, note_svc: NoteService):
        await note_svc.create("Unique Banana Title", "nothing special")
        results = await note_svc.search("Banana")
        assert len(results) >= 1
        assert results[0]["entry"].title == "Unique Banana Title"

    @pytest.mark.asyncio
    async def test_search_finds_by_content(self, note_svc: NoteService):
        await note_svc.create("Title", "The quick brown fox jumps")
        results = await note_svc.search("fox")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_scores_in_valid_range(self, note_svc: NoteService):
        """FTS5 scores should be normalised to (0, 1]."""
        await note_svc.create("Alpha", "alpha keyword repeated alpha alpha")
        await note_svc.create("Beta", "beta only once")
        results = await note_svc.search("alpha")
        assert len(results) >= 1
        for r in results:
            assert 0 < r["score"] <= 1.0

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, note_svc: NoteService):
        for i in range(10):
            await note_svc.create(f"Test {i}", f"searchable term {i}")
        results = await note_svc.search("searchable", limit=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_search_result_has_entry_and_score(self, note_svc: NoteService):
        await note_svc.create("Test", "searchable content")
        results = await note_svc.search("searchable")
        assert len(results) >= 1
        r = results[0]
        assert "entry" in r
        assert "score" in r
        assert isinstance(r["entry"], NoteEntry)

    @pytest.mark.asyncio
    async def test_search_no_match(self, note_svc: NoteService):
        await note_svc.create("Test", "some content")
        results = await note_svc.search("zzzznonexistent")
        assert results == []


# ----------------------------------------------------------------------- #
# get_folders / delete_folder
# ----------------------------------------------------------------------- #

class TestFolders:
    """Tests for folder operations."""

    @pytest.mark.asyncio
    async def test_get_folders_empty(self, note_svc: NoteService):
        folders = await note_svc.get_folders()
        assert folders == []

    @pytest.mark.asyncio
    async def test_get_folders_counts(self, note_svc: NoteService):
        await note_svc.create("A", "a", folder_path="docs")
        await note_svc.create("B", "b", folder_path="docs")
        await note_svc.create("C", "c", folder_path="work")
        folders = await note_svc.get_folders()
        folder_map = {f["path"]: f["count"] for f in folders}
        assert folder_map["docs"] == 2
        assert folder_map["work"] == 1

    @pytest.mark.asyncio
    async def test_get_folders_includes_root(self, note_svc: NoteService):
        await note_svc.create("A", "a", folder_path="")
        folders = await note_svc.get_folders()
        assert any(f["path"] == "" for f in folders)

    @pytest.mark.asyncio
    async def test_delete_folder_mode_move(self, note_svc: NoteService):
        """Mode 'move' moves notes to root folder."""
        await note_svc.create("A", "a", folder_path="old")
        await note_svc.create("B", "b", folder_path="old")
        affected = await note_svc.delete_folder("old", mode="move")
        assert affected == 2
        # Notes still exist, now in root
        entries, total = await note_svc.list(folder="")
        assert total == 2
        # Old folder is empty
        entries_old, total_old = await note_svc.list(folder="old")
        assert total_old == 0

    @pytest.mark.asyncio
    async def test_delete_folder_mode_delete(self, note_svc: NoteService):
        """Mode 'delete' removes notes entirely."""
        await note_svc.create("A", "a", folder_path="trash")
        await note_svc.create("B", "b", folder_path="trash")
        affected = await note_svc.delete_folder("trash", mode="delete")
        assert affected == 2
        entries, total = await note_svc.list()
        assert total == 0

    @pytest.mark.asyncio
    async def test_delete_folder_invalid_mode_raises(self, note_svc: NoteService):
        with pytest.raises(ValueError, match="Invalid mode"):
            await note_svc.delete_folder("any", mode="archive")

    @pytest.mark.asyncio
    async def test_delete_folder_returns_zero_for_empty(self, note_svc: NoteService):
        affected = await note_svc.delete_folder("nonexistent", mode="move")
        assert affected == 0

    @pytest.mark.asyncio
    async def test_delete_folder_does_not_affect_others(self, note_svc: NoteService):
        await note_svc.create("A", "a", folder_path="keep")
        await note_svc.create("B", "b", folder_path="remove")
        await note_svc.delete_folder("remove", mode="delete")
        entries, total = await note_svc.list()
        assert total == 1
        assert entries[0].folder_path == "keep"

    @pytest.mark.asyncio
    async def test_delete_folder_move_syncs_qdrant_payload(
        self, tmp_path: Path, mock_qdrant_service, mock_embedding_client,
    ):
        """Bug-fix: ``mode='move'`` must rewrite Qdrant ``folder_path``.

        Without the fix, semantic search filtered by folder kept
        returning the moved notes under their old folder name.
        """
        cfg = _make_config(
            db_path=str(tmp_path / "notes.db"),
            embedding_enabled=True,
        )
        svc = NoteService(
            config=cfg,
            qdrant_service=mock_qdrant_service,
            embedding_client=mock_embedding_client,
        )
        await svc.initialize()
        try:
            n1 = await svc.create("A", "a", folder_path="old")
            n2 = await svc.create("B", "b", folder_path="old")

            mock_qdrant_service.set_payload.reset_mock()
            affected = await svc.delete_folder("old", mode="move")

            assert affected == 2
            mock_qdrant_service.set_payload.assert_awaited_once()
            kwargs = mock_qdrant_service.set_payload.await_args.kwargs
            assert kwargs["payload"] == {"folder_path": ""}
            assert sorted(kwargs["ids"]) == sorted([n1.id, n2.id])
        finally:
            await svc.close()


# ----------------------------------------------------------------------- #
# Edge cases and integration
# ----------------------------------------------------------------------- #

class TestEdgeCases:
    """Miscellaneous edge cases and integration scenarios."""

    @pytest.mark.asyncio
    async def test_create_empty_content(self, note_svc: NoteService):
        entry = await note_svc.create("Empty", "")
        assert entry.content == ""
        assert entry.wikilinks == []

    @pytest.mark.asyncio
    async def test_create_with_special_characters_in_title(self, note_svc: NoteService):
        entry = await note_svc.create("Title's \"special\" <chars>&", "body")
        fetched = await note_svc.get(entry.id)
        assert fetched is not None
        assert fetched.title == "Title's \"special\" <chars>&"

    @pytest.mark.asyncio
    async def test_to_dict_after_get(self, note_svc: NoteService):
        """Verify to_dict works after a full DB round-trip."""
        entry = await note_svc.create(
            "Title", "Body [[Link]]",
            folder_path="docs", tags=["a", "b"],
        )
        fetched = await note_svc.get(entry.id)
        assert fetched is not None
        d = fetched.to_dict()
        assert d["title"] == "Title"
        assert d["folder_path"] == "docs"
        assert d["tags"] == ["a", "b"]
        assert d["wikilinks"] == ["Link"]
        assert d["pinned"] is False
        assert isinstance(d["created_at"], str)
        assert isinstance(d["updated_at"], str)

    @pytest.mark.asyncio
    async def test_multiple_tags_roundtrip(self, note_svc: NoteService):
        entry = await note_svc.create("T", "C", tags=["x", "y", "z"])
        fetched = await note_svc.get(entry.id)
        assert fetched is not None
        assert fetched.tags == ["x", "y", "z"]

    @pytest.mark.asyncio
    async def test_list_before_initialize_raises(
        self, tmp_path: Path, mock_qdrant_service, mock_embedding_client,
    ):
        cfg = _make_config(db_path=str(tmp_path / "x.db"))
        svc = NoteService(
            config=cfg,
            qdrant_service=mock_qdrant_service,
            embedding_client=mock_embedding_client,
        )
        with pytest.raises(RuntimeError):
            await svc.list()

    @pytest.mark.asyncio
    async def test_search_before_initialize_raises(
        self, tmp_path: Path, mock_qdrant_service, mock_embedding_client,
    ):
        cfg = _make_config(db_path=str(tmp_path / "x.db"))
        svc = NoteService(
            config=cfg,
            qdrant_service=mock_qdrant_service,
            embedding_client=mock_embedding_client,
        )
        with pytest.raises(RuntimeError):
            await svc.search("query")

    @pytest.mark.asyncio
    async def test_delete_before_initialize_raises(
        self, tmp_path: Path, mock_qdrant_service, mock_embedding_client,
    ):
        cfg = _make_config(db_path=str(tmp_path / "x.db"))
        svc = NoteService(
            config=cfg,
            qdrant_service=mock_qdrant_service,
            embedding_client=mock_embedding_client,
        )
        with pytest.raises(RuntimeError):
            await svc.delete("some-id")

    @pytest.mark.asyncio
    async def test_update_multiple_fields_at_once(self, note_svc: NoteService):
        entry = await note_svc.create("T", "C", folder_path="a", tags=["old"])
        updated = await note_svc.update(
            entry.id,
            title="New Title",
            content="New Body [[Link]]",
            folder_path="b",
            tags=["new"],
            pinned=True,
        )
        assert updated is not None
        assert updated.title == "New Title"
        assert updated.content == "New Body [[Link]]"
        assert updated.folder_path == "b"
        assert updated.tags == ["new"]
        assert updated.wikilinks == ["Link"]
        assert updated.pinned is True
