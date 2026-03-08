"""Tests for backend.plugins.clipboard — ClipboardPlugin."""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import ConnectionStatus, ExecutionContext, ToolResult
from backend.plugins.clipboard.plugin import ClipboardPlugin, _MAX_SET_LENGTH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="test",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


def _make_app_context() -> AppContext:
    """Build a minimal AppContext with default config."""
    return AppContext(config=load_config(), event_bus=EventBus())


# ---------------------------------------------------------------------------
# Fake pyperclip module used by all tests
# ---------------------------------------------------------------------------


def _make_pyperclip_mock() -> MagicMock:
    """Return a MagicMock that behaves like the pyperclip module."""
    mod = MagicMock()
    mod.paste = MagicMock(return_value="")
    mod.copy = MagicMock()
    mod.PyperclipException = type("PyperclipException", (Exception,), {})
    return mod


# ===========================================================================
# 1.  Plugin lifecycle
# ===========================================================================


class TestClipboardPluginLifecycle:
    """Verify plugin attributes, init, tools and connection status."""

    def test_plugin_class_attributes(self):
        plugin = ClipboardPlugin()
        assert plugin.plugin_name == "clipboard"
        assert plugin.plugin_priority == 20
        assert plugin.plugin_version == "1.0.0"
        assert plugin.plugin_dependencies == []

    @pytest.mark.asyncio
    async def test_initialize(self):
        plugin = ClipboardPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)
        assert plugin.ctx is ctx

    def test_get_tools_returns_two(self):
        plugin = ClipboardPlugin()
        tools = plugin.get_tools()
        assert len(tools) == 2

    def test_tool_names(self):
        plugin = ClipboardPlugin()
        names = {t.name for t in plugin.get_tools()}
        assert names == {"get_clipboard", "set_clipboard"}

    def test_get_clipboard_risk_level(self):
        plugin = ClipboardPlugin()
        tool = next(t for t in plugin.get_tools() if t.name == "get_clipboard")
        assert tool.risk_level == "safe"
        assert tool.requires_confirmation is False

    def test_set_clipboard_risk_level(self):
        plugin = ClipboardPlugin()
        tool = next(t for t in plugin.get_tools() if t.name == "set_clipboard")
        assert tool.risk_level == "medium"
        assert tool.requires_confirmation is True

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_check_dependencies_available(self):
        plugin = ClipboardPlugin()
        assert plugin.check_dependencies() == []

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", False)
    async def test_check_dependencies_missing(self):
        plugin = ClipboardPlugin()
        assert plugin.check_dependencies() == ["pyperclip"]

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_connection_status_connected(self):
        plugin = ClipboardPlugin()
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", False)
    async def test_connection_status_error(self):
        plugin = ClipboardPlugin()
        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.ERROR


# ===========================================================================
# 2.  get_clipboard
# ===========================================================================


class TestGetClipboard:
    """Test the get_clipboard tool execution path."""

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_normal_text(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        mock_pyperclip = _make_pyperclip_mock()
        mock_pyperclip.paste.return_value = "hello world"

        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool("get_clipboard", {}, _make_exec_ctx())

        assert result.success is True
        assert result.content["content"] == "hello world"
        assert result.content["truncated"] is False
        assert result.content["length"] == 11

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_empty_clipboard(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        mock_pyperclip = _make_pyperclip_mock()
        mock_pyperclip.paste.return_value = ""

        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool("get_clipboard", {}, _make_exec_ctx())

        assert result.success is True
        assert result.content["content"] == ""
        assert result.content["truncated"] is False
        assert result.content["length"] == 0

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_long_text_truncated(self):
        plugin = ClipboardPlugin()
        ctx = _make_app_context()
        await plugin.initialize(ctx)
        max_chars = ctx.config.clipboard.max_content_chars  # 4000

        long_text = "A" * (max_chars + 500)
        mock_pyperclip = _make_pyperclip_mock()
        mock_pyperclip.paste.return_value = long_text

        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool("get_clipboard", {}, _make_exec_ctx())

        assert result.success is True
        assert result.content["truncated"] is True
        assert result.content["length"] == len(long_text)
        assert len(result.content["content"]) == max_chars

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_binary_content_pyperclip_exception(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        mock_pyperclip = _make_pyperclip_mock()
        mock_pyperclip.paste.side_effect = mock_pyperclip.PyperclipException("binary")

        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool("get_clipboard", {}, _make_exec_ctx())

        assert result.success is False
        assert "non-text" in result.error_message


# ===========================================================================
# 3.  set_clipboard
# ===========================================================================


class TestSetClipboard:
    """Test the set_clipboard tool execution path."""

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_normal_text(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        mock_pyperclip = _make_pyperclip_mock()

        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool(
                "set_clipboard", {"text": "copied!"}, _make_exec_ctx()
            )

        assert result.success is True
        assert result.content == "Clipboard updated"
        mock_pyperclip.copy.assert_called_once_with("copied!")

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_text_too_long(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        huge_text = "X" * (_MAX_SET_LENGTH + 1)

        mock_pyperclip = _make_pyperclip_mock()
        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool(
                "set_clipboard", {"text": huge_text}, _make_exec_ctx()
            )

        assert result.success is False
        assert "maximum length" in result.error_message
        mock_pyperclip.copy.assert_not_called()

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_missing_text_param(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        mock_pyperclip = _make_pyperclip_mock()
        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool(
                "set_clipboard", {}, _make_exec_ctx()
            )

        assert result.success is False
        assert "Missing" in result.error_message

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_pyperclip_write_failure(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        mock_pyperclip = _make_pyperclip_mock()
        mock_pyperclip.copy.side_effect = mock_pyperclip.PyperclipException("fail")

        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool(
                "set_clipboard", {"text": "test"}, _make_exec_ctx()
            )

        assert result.success is False
        assert "write failed" in result.error_message


# ===========================================================================
# 4.  Edge cases
# ===========================================================================


class TestClipboardEdgeCases:
    """Miscellaneous edge cases and guard rails."""

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", False)
    async def test_pyperclip_not_installed_returns_error(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        result = await plugin.execute_tool("get_clipboard", {}, _make_exec_ctx())
        assert result.success is False
        assert "not installed" in result.error_message

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", False)
    async def test_set_clipboard_not_installed_returns_error(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        result = await plugin.execute_tool(
            "set_clipboard", {"text": "x"}, _make_exec_ctx()
        )
        assert result.success is False
        assert "not installed" in result.error_message

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_unknown_tool_name(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        mock_pyperclip = _make_pyperclip_mock()
        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool(
                "delete_clipboard", {}, _make_exec_ctx()
            )

        assert result.success is False
        assert "Unknown tool" in result.error_message

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_execution_time_ms_returned(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        mock_pyperclip = _make_pyperclip_mock()
        mock_pyperclip.paste.return_value = "timing"

        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool("get_clipboard", {}, _make_exec_ctx())

        assert result.success is True
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    @patch("backend.plugins.clipboard.plugin._PYPERCLIP_AVAILABLE", True)
    async def test_set_execution_time_ms_returned(self):
        plugin = ClipboardPlugin()
        await plugin.initialize(_make_app_context())

        mock_pyperclip = _make_pyperclip_mock()

        with patch("backend.plugins.clipboard.plugin.pyperclip", mock_pyperclip):
            result = await plugin.execute_tool(
                "set_clipboard", {"text": "t"}, _make_exec_ctx()
            )

        assert result.success is True
        assert result.execution_time_ms >= 0
