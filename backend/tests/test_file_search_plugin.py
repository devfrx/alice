"""Tests for backend.plugins.file_search — FileSearchPlugin."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import ConnectionStatus, ExecutionContext, ToolResult
from backend.plugins.file_search.plugin import FileSearchPlugin
from backend.plugins.file_search.readers import (
    _TEXT_EXTENSIONS,
    read_text_file,
)
from backend.plugins.file_search.searcher import (
    ForbiddenPathError,
    _sync_walk,
    _validate_path,
    search_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="test",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


def _make_app_context(
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
) -> AppContext:
    """Build a minimal AppContext with controllable file_search config."""
    cfg = load_config()
    if allowed_paths is not None:
        cfg.file_search.allowed_paths = allowed_paths
    if forbidden_paths is not None:
        cfg.file_search.forbidden_paths = forbidden_paths
    return AppContext(config=cfg, event_bus=EventBus())


async def _init_plugin(
    allowed: list[str] | None = None,
    forbidden: list[str] | None = None,
) -> FileSearchPlugin:
    """Create, initialise and return a FileSearchPlugin."""
    plugin = FileSearchPlugin()
    ctx = _make_app_context(allowed_paths=allowed, forbidden_paths=forbidden)
    await plugin.initialize(ctx)
    return plugin


# ===========================================================================
# 1.  Plugin lifecycle
# ===========================================================================


class TestFileSearchPluginLifecycle:
    """Verify plugin attributes, init, tools and connection status."""

    def test_plugin_class_attributes(self):
        plugin = FileSearchPlugin()
        assert plugin.plugin_name == "file_search"
        assert plugin.plugin_priority == 25
        assert plugin.plugin_version == "1.0.0"
        assert plugin.plugin_dependencies == []

    @pytest.mark.asyncio
    async def test_initialize(self):
        plugin = FileSearchPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)
        assert plugin.ctx is ctx

    @pytest.mark.asyncio
    async def test_initialize_sets_allowed_paths(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"])
        assert len(plugin._allowed_paths) == 1
        assert plugin._allowed_paths[0] == Path("/tmp/allowed")

    @pytest.mark.asyncio
    async def test_initialize_defaults_allowed_to_home(self):
        plugin = await _init_plugin(allowed=[])
        # With empty config, defaults to all available drive roots on Windows
        # or home on other platforms.
        import sys
        if sys.platform == "win32":
            # Must contain at least C:\
            assert any(
                str(p).upper().startswith("C") for p in plugin._allowed_paths
            )
            # All paths should be drive roots
            for p in plugin._allowed_paths:
                assert p.parent == p  # drive root has no parent above itself
        else:
            assert Path.home() in plugin._allowed_paths

    def test_get_tools_returns_five(self):
        plugin = FileSearchPlugin()
        tools = plugin.get_tools()
        assert len(tools) == 5

    def test_tool_names(self):
        plugin = FileSearchPlugin()
        names = {t.name for t in plugin.get_tools()}
        assert names == {
            "search_files", "get_file_info", "read_text_file",
            "open_file", "write_text_file",
        }

    def test_search_files_risk_level(self):
        plugin = FileSearchPlugin()
        tool = next(t for t in plugin.get_tools() if t.name == "search_files")
        assert tool.risk_level == "safe"
        assert tool.requires_confirmation is False

    def test_get_file_info_risk_level(self):
        plugin = FileSearchPlugin()
        tool = next(t for t in plugin.get_tools() if t.name == "get_file_info")
        assert tool.risk_level == "safe"
        assert tool.requires_confirmation is False

    def test_read_text_file_risk_level(self):
        plugin = FileSearchPlugin()
        tool = next(t for t in plugin.get_tools() if t.name == "read_text_file")
        assert tool.risk_level == "medium"
        assert tool.requires_confirmation is True

    def test_open_file_risk_level(self):
        plugin = FileSearchPlugin()
        tool = next(t for t in plugin.get_tools() if t.name == "open_file")
        assert tool.risk_level == "medium"
        assert tool.requires_confirmation is True

    def test_write_text_file_risk_level(self):
        plugin = FileSearchPlugin()
        tool = next(t for t in plugin.get_tools() if t.name == "write_text_file")
        assert tool.risk_level == "medium"
        assert tool.requires_confirmation is True

    @pytest.mark.asyncio
    @patch("backend.plugins.file_search.plugin._PDF_AVAILABLE", True)
    @patch("backend.plugins.file_search.plugin._DOCX_AVAILABLE", True)
    async def test_check_dependencies_all_available(self):
        plugin = FileSearchPlugin()
        assert plugin.check_dependencies() == []

    @pytest.mark.asyncio
    @patch("backend.plugins.file_search.plugin._PDF_AVAILABLE", False)
    @patch("backend.plugins.file_search.plugin._DOCX_AVAILABLE", False)
    async def test_check_dependencies_missing(self):
        plugin = FileSearchPlugin()
        missing = plugin.check_dependencies()
        assert "pdfplumber" in missing
        assert "python-docx" in missing

    @pytest.mark.asyncio
    async def test_connection_status(self):
        plugin = FileSearchPlugin()
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp"])
        result = await plugin.execute_tool("nonexistent", {}, _make_exec_ctx())
        assert result.success is False
        assert "Unknown tool" in result.error_message


# ===========================================================================
# 2.  search_files tool
# ===========================================================================

# Fake os.walk data:  (dirpath, dirnames, filenames)
_FAKE_WALK = [
    ("/tmp/allowed", ["sub"], ["readme.txt", "notes.md", "report.pdf"]),
    ("/tmp/allowed/sub", [], ["results.txt", "image.png", "summary.docx"]),
]


def _fake_stat(size: int = 1024, mtime: float = 1700000000.0):
    """Return a mock stat_result."""
    s = MagicMock()
    s.st_size = size
    s.st_mtime = mtime
    s.st_ctime = mtime
    return s


class TestSearchFilesTool:
    """Test the search_files tool executed through the plugin."""

    @pytest.mark.asyncio
    async def test_find_files_matching_query(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        with (
            patch("backend.plugins.file_search.searcher.os.walk", return_value=iter(_FAKE_WALK)),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat", return_value=_fake_stat()),
        ):
            result = await plugin.execute_tool(
                "search_files",
                {"query": "readme"},
                _make_exec_ctx(),
            )

        assert result.success is True
        items = result.content
        assert len(items) == 1
        assert items[0]["name"] == "readme.txt"

    @pytest.mark.asyncio
    async def test_no_results_returns_empty(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        with (
            patch("backend.plugins.file_search.searcher.os.walk", return_value=iter(_FAKE_WALK)),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat", return_value=_fake_stat()),
        ):
            result = await plugin.execute_tool(
                "search_files",
                {"query": "nonexistent_xyz"},
                _make_exec_ctx(),
            )

        assert result.success is True
        assert result.content == []

    @pytest.mark.asyncio
    async def test_max_results_limit(self):
        # Build walk data with many matching files
        many_files = [f"match_{i}.txt" for i in range(100)]
        walk_data = [("/tmp/allowed", [], many_files)]

        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        with (
            patch("backend.plugins.file_search.searcher.os.walk", return_value=iter(walk_data)),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat", return_value=_fake_stat()),
        ):
            result = await plugin.execute_tool(
                "search_files",
                {"query": "match", "max_results": 5},
                _make_exec_ctx(),
            )

        assert result.success is True
        assert len(result.content) == 5

    @pytest.mark.asyncio
    async def test_extension_filter_pdf(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        with (
            patch("backend.plugins.file_search.searcher.os.walk", return_value=iter(_FAKE_WALK)),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat", return_value=_fake_stat()),
        ):
            result = await plugin.execute_tool(
                "search_files",
                {"query": "report", "extensions": [".pdf"]},
                _make_exec_ctx(),
            )

        assert result.success is True
        assert len(result.content) == 1
        assert result.content[0]["name"] == "report.pdf"

    @pytest.mark.asyncio
    async def test_extension_filter_docx(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        with (
            patch("backend.plugins.file_search.searcher.os.walk", return_value=iter(_FAKE_WALK)),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat", return_value=_fake_stat()),
        ):
            result = await plugin.execute_tool(
                "search_files",
                {"query": "summary", "extensions": [".docx"]},
                _make_exec_ctx(),
            )

        assert result.success is True
        assert len(result.content) == 1
        assert result.content[0]["name"] == "summary.docx"

    @pytest.mark.asyncio
    async def test_search_validates_custom_path(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        result = await plugin.execute_tool(
            "search_files",
            {"query": "test", "path": "/not/allowed"},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "outside all allowed" in result.error_message

    @pytest.mark.asyncio
    async def test_search_forbidden_path_blocked(self):
        plugin = await _init_plugin(
            allowed=["/tmp/allowed"],
            forbidden=["/tmp/allowed/secret"],
        )

        result = await plugin.execute_tool(
            "search_files",
            {"query": "test", "path": "/tmp/allowed/secret"},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "forbidden" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_empty_query_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        result = await plugin.execute_tool(
            "search_files",
            {"query": ""},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "required" in result.error_message.lower()


# ===========================================================================
# 3.  get_file_info tool
# ===========================================================================


class TestGetFileInfoTool:
    """Test the get_file_info tool executed through the plugin."""

    @pytest.mark.asyncio
    async def test_file_exists_returns_metadata(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/readme.txt").resolve()

        mock_stat = _fake_stat(size=2048, mtime=1700000000.0)

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "is_dir", return_value=False),
            patch.object(Path, "stat", return_value=mock_stat),
        ):
            result = await plugin.execute_tool(
                "get_file_info",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is True
        info = result.content
        assert info["name"] == "readme.txt"
        assert info["size_bytes"] == 2048
        assert info["extension"] == ".txt"
        assert "mime_type" in info

    @pytest.mark.asyncio
    async def test_file_not_found_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/missing.txt").resolve()

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "exists", return_value=False),
        ):
            result = await plugin.execute_tool(
                "get_file_info",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_path_outside_allowed_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        result = await plugin.execute_tool(
            "get_file_info",
            {"path": "/etc/passwd"},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "outside" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_empty_path_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        result = await plugin.execute_tool(
            "get_file_info",
            {"path": ""},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "required" in result.error_message.lower()


# ===========================================================================
# 4.  read_text_file tool
# ===========================================================================


class TestReadTextFileTool:
    """Test the read_text_file tool executed through the plugin."""

    @pytest.mark.asyncio
    async def test_read_txt_file(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/readme.txt").resolve()
        content_data = {
            "content": "Hello world",
            "truncated": False,
            "chars_read": 11,
            "path": str(target),
        }

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "stat", return_value=_fake_stat(size=100)),
            patch(
                "backend.plugins.file_search.plugin.read_text_file",
                new_callable=AsyncMock,
                return_value=content_data,
            ),
        ):
            result = await plugin.execute_tool(
                "read_text_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is True
        assert result.content["content"] == "Hello world"
        assert result.content["truncated"] is False

    @pytest.mark.asyncio
    async def test_read_md_file(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/notes.md").resolve()
        content_data = {
            "content": "# Title\nSome markdown",
            "truncated": False,
            "chars_read": 21,
            "path": str(target),
        }

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "stat", return_value=_fake_stat(size=200)),
            patch(
                "backend.plugins.file_search.plugin.read_text_file",
                new_callable=AsyncMock,
                return_value=content_data,
            ),
        ):
            result = await plugin.execute_tool(
                "read_text_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is True
        assert "# Title" in result.content["content"]

    @pytest.mark.asyncio
    async def test_pdf_without_pdfplumber_errors(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/report.pdf").resolve()
        error_result = ToolResult.error(
            "pdfplumber is not installed — cannot read PDF files. "
            "Install with: pip install pdfplumber"
        )

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "stat", return_value=_fake_stat(size=500)),
            patch(
                "backend.plugins.file_search.plugin.read_text_file",
                new_callable=AsyncMock,
                return_value=error_result,
            ),
        ):
            result = await plugin.execute_tool(
                "read_text_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is False
        assert "pdfplumber" in result.error_message

    @pytest.mark.asyncio
    async def test_content_truncation(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/big.txt").resolve()
        content_data = {
            "content": "A" * 8000,
            "truncated": True,
            "chars_read": 8000,
            "path": str(target),
        }

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "stat", return_value=_fake_stat(size=500_000)),
            patch(
                "backend.plugins.file_search.plugin.read_text_file",
                new_callable=AsyncMock,
                return_value=content_data,
            ),
        ):
            result = await plugin.execute_tool(
                "read_text_file",
                {"path": str(target), "max_chars": 8000},
                _make_exec_ctx(),
            )

        assert result.success is True
        assert result.content["truncated"] is True
        assert len(result.content["content"]) == 8000

    @pytest.mark.asyncio
    async def test_file_too_large_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/huge.txt").resolve()

        # max_file_size_read_bytes defaults to 1_048_576
        huge_size = 2_000_000

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "stat", return_value=_fake_stat(size=huge_size)),
        ):
            result = await plugin.execute_tool(
                "read_text_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is False
        assert "too large" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_not_a_file_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/nofile").resolve()

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "is_file", return_value=False),
        ):
            result = await plugin.execute_tool(
                "read_text_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is False
        assert "not a file" in result.error_message.lower()


# ===========================================================================
# 5.  open_file tool
# ===========================================================================


class TestOpenFileTool:
    """Test the open_file tool executed through the plugin."""

    @pytest.mark.asyncio
    async def test_valid_file_opened(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/readme.txt").resolve()

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "exists", return_value=True),
            patch("os.startfile") as mock_start,
        ):
            result = await plugin.execute_tool(
                "open_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is True
        assert "readme.txt" in result.content
        mock_start.assert_called_once_with(target)

    @pytest.mark.asyncio
    async def test_file_not_found_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/missing.txt").resolve()

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "exists", return_value=False),
        ):
            result = await plugin.execute_tool(
                "open_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is False
        assert "not found" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_path_outside_allowed_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        result = await plugin.execute_tool(
            "open_file",
            {"path": "/etc/passwd"},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "outside" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_executable_exe_blocked(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/malware.exe").resolve()

        with patch.object(Path, "resolve", return_value=target):
            result = await plugin.execute_tool(
                "open_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is False
        assert "executable" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_executable_bat_blocked(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/script.bat").resolve()

        with patch.object(Path, "resolve", return_value=target):
            result = await plugin.execute_tool(
                "open_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is False
        assert "executable" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_executable_ps1_blocked(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])
        target = Path("/tmp/allowed/script.ps1").resolve()

        with patch.object(Path, "resolve", return_value=target):
            result = await plugin.execute_tool(
                "open_file",
                {"path": str(target)},
                _make_exec_ctx(),
            )

        assert result.success is False
        assert "executable" in result.error_message.lower()


# ===========================================================================
# 5b. write_text_file tool
# ===========================================================================


class TestWriteTextFileTool:
    """Test the write_text_file tool executed through the plugin."""

    @pytest.mark.asyncio
    async def test_write_creates_file(self, tmp_path):
        plugin = await _init_plugin(allowed=[str(tmp_path)], forbidden=[])
        target = tmp_path / "hello.txt"

        result = await plugin.execute_tool(
            "write_text_file",
            {"path": str(target), "content": "Ciao mondo!"},
            _make_exec_ctx(),
        )

        assert result.success is True
        assert target.read_text(encoding="utf-8") == "Ciao mondo!"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, tmp_path):
        plugin = await _init_plugin(allowed=[str(tmp_path)], forbidden=[])
        target = tmp_path / "sub" / "deep" / "file.txt"

        result = await plugin.execute_tool(
            "write_text_file",
            {"path": str(target), "content": "nested"},
            _make_exec_ctx(),
        )

        assert result.success is True
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "nested"

    @pytest.mark.asyncio
    async def test_write_missing_path_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp"], forbidden=[])

        result = await plugin.execute_tool(
            "write_text_file",
            {"content": "some text"},
            _make_exec_ctx(),
        )

        assert result.success is False

    @pytest.mark.asyncio
    async def test_write_missing_content_returns_error(self, tmp_path):
        plugin = await _init_plugin(allowed=[str(tmp_path)], forbidden=[])
        target = tmp_path / "empty.txt"

        result = await plugin.execute_tool(
            "write_text_file",
            {"path": str(target), "content": ""},
            _make_exec_ctx(),
        )

        assert result.success is False

    @pytest.mark.asyncio
    async def test_write_outside_allowed_returns_error(self):
        plugin = await _init_plugin(allowed=["/tmp/allowed"], forbidden=[])

        result = await plugin.execute_tool(
            "write_text_file",
            {"path": "/etc/secret.txt", "content": "hack"},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "outside" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_write_executable_extension_blocked(self, tmp_path):
        plugin = await _init_plugin(allowed=[str(tmp_path)], forbidden=[])

        for ext in (".exe", ".bat", ".cmd", ".ps1"):
            result = await plugin.execute_tool(
                "write_text_file",
                {"path": str(tmp_path / f"bad{ext}"), "content": "payload"},
                _make_exec_ctx(),
            )
            assert result.success is False, f"Should block {ext}"
            assert "executable" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_write_too_large_returns_error(self, tmp_path):
        plugin = await _init_plugin(allowed=[str(tmp_path)], forbidden=[])
        huge = "x" * (1_048_576 + 1)

        result = await plugin.execute_tool(
            "write_text_file",
            {"path": str(tmp_path / "big.txt"), "content": huge},
            _make_exec_ctx(),
        )

        assert result.success is False
        assert "too large" in result.error_message.lower()


# ===========================================================================
# 6.  Path security
# ===========================================================================


class TestPathSecurity:
    """Test path validation logic in the searcher module."""

    def test_unc_paths_blocked(self):
        with pytest.raises(ValueError, match="UNC paths are not allowed"):
            _validate_path(
                "\\\\server\\share\\file.txt",
                allowed_roots=[Path("/tmp/allowed")],
                forbidden=[],
                follow_symlinks=False,
            )

    def test_path_traversal_blocked(self):
        """Path traversal attempt (../../) that resolves outside allowed."""
        with pytest.raises(ValueError, match="outside all allowed"):
            _validate_path(
                "/tmp/allowed/../../etc/passwd",
                allowed_roots=[Path("/tmp/allowed")],
                forbidden=[],
                follow_symlinks=False,
            )

    def test_forbidden_path_blocked(self):
        with pytest.raises(ForbiddenPathError, match="forbidden directory"):
            _validate_path(
                "C:\\Windows\\System32\\cmd.exe",
                allowed_roots=[Path("C:\\")],
                forbidden=[Path("C:\\Windows")],
                follow_symlinks=False,
            )

    def test_forbidden_program_files_blocked(self):
        with pytest.raises(ForbiddenPathError, match="forbidden directory"):
            _validate_path(
                "C:\\Program Files\\app\\test.exe",
                allowed_roots=[Path("C:\\")],
                forbidden=[Path("C:\\Program Files")],
                follow_symlinks=False,
            )

    def test_valid_path_inside_allowed(self):
        allowed = Path("/tmp/allowed").resolve()
        target_str = str(allowed / "subdir" / "file.txt")

        with patch.object(Path, "resolve", return_value=allowed / "subdir" / "file.txt"):
            result = _validate_path(
                target_str,
                allowed_roots=[allowed],
                forbidden=[],
                follow_symlinks=False,
            )

        assert result is not None

    def test_path_outside_all_allowed_roots(self):
        with pytest.raises(ValueError, match="outside all allowed"):
            _validate_path(
                "/var/secret/data.txt",
                allowed_roots=[Path("/tmp/allowed")],
                forbidden=[],
                follow_symlinks=False,
            )

    def test_symlink_resolution(self):
        """Even with follow_symlinks=False, resolve() is called to normalize."""
        allowed = Path("/tmp/allowed").resolve()
        target_resolved = allowed / "real_file.txt"

        with (
            patch.object(Path, "resolve", return_value=target_resolved),
            patch.object(Path, "is_symlink", return_value=False),
        ):
            result = _validate_path(
                str(target_resolved),
                allowed_roots=[allowed],
                forbidden=[],
                follow_symlinks=False,
            )

        assert result == target_resolved

    def test_symlink_rejected_when_follow_symlinks_false(self):
        """Symlinks must be rejected when follow_symlinks=False."""
        allowed = Path("/tmp/allowed").resolve()
        target = allowed / "link.txt"

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "is_symlink", return_value=True),
        ):
            with pytest.raises(ValueError, match="Symlinks not allowed"):
                _validate_path(
                    str(target),
                    allowed_roots=[allowed],
                    forbidden=[],
                    follow_symlinks=False,
                )

    def test_symlink_allowed_when_follow_symlinks_true(self):
        """Symlinks should be accepted when follow_symlinks=True."""
        allowed = Path("/tmp/allowed").resolve()
        target = allowed / "link.txt"

        with (
            patch.object(Path, "resolve", return_value=target),
            patch.object(Path, "is_symlink", return_value=True),
        ):
            result = _validate_path(
                str(target),
                allowed_roots=[allowed],
                forbidden=[],
                follow_symlinks=True,
            )

        assert result == target


# ===========================================================================
# 7.  Search performance / edge cases
# ===========================================================================


class TestSearchPerformance:
    """Test timeout behaviour and error resilience of search_files."""

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self):
        """If os.walk takes >5 seconds, search_files returns []."""

        def slow_walk(*args, **kwargs):
            import time
            time.sleep(10)
            return iter([])

        with (
            patch("backend.plugins.file_search.searcher.os.walk", side_effect=slow_walk),
            patch("pathlib.Path.is_dir", return_value=True),
        ):
            results = await search_files(
                query="test",
                roots=[Path("/tmp/allowed")],
                extensions=None,
                max_results=50,
                forbidden=[],
                follow_symlinks=False,
            )

        assert results == []

    @pytest.mark.asyncio
    async def test_permission_error_continues_search(self):
        """PermissionError on stat() should skip the file, not crash."""
        walk_data = [("/tmp/allowed", [], ["ok.txt", "denied.txt", "also_ok.txt"])]

        call_count = 0

        def mock_stat_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # second file raises PermissionError
            if call_count == 2:
                raise PermissionError("Access denied")
            return _fake_stat()

        with (
            patch("backend.plugins.file_search.searcher.os.walk", return_value=iter(walk_data)),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat", side_effect=mock_stat_side_effect),
        ):
            results = await search_files(
                query=".txt",
                roots=[Path("/tmp/allowed")],
                extensions=None,
                max_results=50,
                forbidden=[],
                follow_symlinks=False,
            )

        # ok.txt and also_ok.txt succeed; denied.txt is skipped
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_os_error_on_stat_continues(self):
        """Generic OSError on stat() should skip the file gracefully."""
        walk_data = [("/tmp/allowed", [], ["good.txt", "bad.txt"])]

        call_count = 0

        def mock_stat_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("Disk error")
            return _fake_stat()

        with (
            patch("backend.plugins.file_search.searcher.os.walk", return_value=iter(walk_data)),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat", side_effect=mock_stat_side_effect),
        ):
            results = await search_files(
                query=".txt",
                roots=[Path("/tmp/allowed")],
                extensions=None,
                max_results=50,
                forbidden=[],
                follow_symlinks=False,
            )

        assert len(results) == 1
        assert results[0]["name"] == "good.txt"

    @pytest.mark.asyncio
    async def test_non_existent_root_is_skipped(self):
        """If root directory doesn't exist, search returns empty."""
        with patch("pathlib.Path.is_dir", return_value=False):
            results = await search_files(
                query="test",
                roots=[Path("/nonexistent")],
                extensions=None,
                max_results=50,
                forbidden=[],
                follow_symlinks=False,
            )

        assert results == []


# ===========================================================================
# 8.  Reader functions (unit)
# ===========================================================================


class TestReaders:
    """Direct tests on the reader functions from readers.py."""

    @pytest.mark.asyncio
    async def test_read_plain_text(self):
        fake_content = b"Line 1\nLine 2\n"
        mock_open = MagicMock()
        mock_open.return_value.__enter__ = MagicMock(return_value=MagicMock(
            read=MagicMock(return_value=fake_content)
        ))
        mock_open.return_value.__exit__ = MagicMock(return_value=False)

        with patch("builtins.open", mock_open):
            result = await read_text_file(
                path=Path("/tmp/allowed/test.txt"),
                max_bytes=1_000_000,
                max_chars=8000,
            )

        assert isinstance(result, dict)
        assert result["content"] == fake_content.decode("utf-8")
        assert result["truncated"] is False

    @pytest.mark.asyncio
    async def test_read_unsupported_extension(self):
        result = await read_text_file(
            path=Path("/tmp/allowed/file.xyz"),
            max_bytes=1_000_000,
            max_chars=8000,
        )

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "Unsupported file type" in result.error_message

    @pytest.mark.asyncio
    @patch("backend.plugins.file_search.readers._PDF_AVAILABLE", False)
    async def test_read_pdf_not_available(self):
        result = await read_text_file(
            path=Path("/tmp/allowed/doc.pdf"),
            max_bytes=1_000_000,
            max_chars=8000,
        )

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "pdfplumber" in result.error_message

    @pytest.mark.asyncio
    @patch("backend.plugins.file_search.readers._DOCX_AVAILABLE", False)
    async def test_read_docx_not_available(self):
        result = await read_text_file(
            path=Path("/tmp/allowed/doc.docx"),
            max_bytes=1_000_000,
            max_chars=8000,
        )

        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "python-docx" in result.error_message

    def test_text_extensions_include_common_types(self):
        for ext in [".txt", ".md", ".py", ".json", ".yaml", ".csv", ".log"]:
            assert ext in _TEXT_EXTENSIONS
