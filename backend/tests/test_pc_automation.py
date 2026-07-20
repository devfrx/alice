"""Tests for the PC Automation plugin (Phase 5).

Covers plugin lifecycle, tool definitions, risk levels,
and tool execution with mocked dependencies.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx() -> AppContext:
    """Minimal AppContext with real config and fresh EventBus."""
    return AppContext(config=load_config(), event_bus=EventBus())


@pytest.fixture
def exec_context() -> ExecutionContext:
    """Standard execution context for tool invocations."""
    return ExecutionContext(
        session_id="test-session",
        conversation_id="test-conv-id",
        execution_id="test-exec-id",
    )


# ---------------------------------------------------------------------------
# Expected tool catalogue (source of truth: README.md risk table)
# ---------------------------------------------------------------------------

EXPECTED_TOOLS: dict[str, dict] = {
    "get_active_window":  {"risk": "safe",      "confirm": False},
    "get_running_apps":   {"risk": "safe",      "confirm": False},
    "open_application":   {"risk": "safe",      "confirm": False},
    "close_application":  {"risk": "safe",      "confirm": False},
    "type_text":          {"risk": "medium",    "confirm": True},
    "press_keys":         {"risk": "medium",    "confirm": True},
    "take_screenshot":    {"risk": "medium",    "confirm": True},
    "move_mouse":         {"risk": "medium",    "confirm": True},
    "click":              {"risk": "medium",    "confirm": True},
}


def _get_plugin():
    """Import and return PcAutomationPlugin (lazy to avoid import errors)."""
    from backend.plugins.pc_automation.plugin import PcAutomationPlugin
    return PcAutomationPlugin()


def test_execute_command_retired():
    """Exec is unified on terminal.run_terminal_command (Fase 2, spec 5.1).

    The parallel ``execute_command`` path (command whitelist + workspace_root
    confinement) was retired; app launching stays.
    """
    names = {t.name for t in _get_plugin().get_tools()}
    assert "execute_command" not in names
    assert "open_application" in names  # il lancio app resta


def test_open_application_declares_process_exec_capability():
    """open_application still declares the process_exec capability."""
    tools = {t.name: t for t in _get_plugin().get_tools()}
    assert "process_exec" in tools["open_application"].capabilities


# ---------------------------------------------------------------------------
# TestPcAutomationPluginLifecycle
# ---------------------------------------------------------------------------


class TestPcAutomationPluginLifecycle:
    """Plugin attributes, initialisation and tool discovery."""

    def test_plugin_attributes(self):
        """plugin_name, version and description are set."""
        plugin = _get_plugin()
        assert plugin.plugin_name == "pc_automation"
        assert plugin.plugin_version
        assert plugin.plugin_description

    @pytest.mark.asyncio
    async def test_initialize(self, ctx: AppContext):
        """Plugin initialises with AppContext and sets is_initialized."""
        plugin = _get_plugin()
        assert not plugin.is_initialized
        await plugin.initialize(ctx)
        assert plugin.is_initialized
        assert plugin.ctx is ctx

    def test_get_tools(self):
        """get_tools returns 9 ToolDefinition objects with correct names."""
        plugin = _get_plugin()
        tools = plugin.get_tools()
        assert len(tools) == len(EXPECTED_TOOLS)
        tool_names = {t.name for t in tools}
        assert tool_names == set(EXPECTED_TOOLS.keys())

    def test_tool_definitions_valid(self):
        """Every ToolDefinition passes validate() without raising."""
        plugin = _get_plugin()
        for td in plugin.get_tools():
            assert isinstance(td, ToolDefinition)
            td.validate()  # raises ValueError on bad name/description

    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", False)
    @patch("backend.plugins.pc_automation.executor._PYWINAUTO_AVAILABLE", False)
    def test_check_dependencies_missing(self):
        """check_dependencies reports missing deps when pyautogui unavailable."""
        from backend.plugins.pc_automation.executor import check_dependencies
        missing = check_dependencies()
        assert "pyautogui" in missing


# ---------------------------------------------------------------------------
# TestPcAutomationToolRiskLevels
# ---------------------------------------------------------------------------


class TestPcAutomationToolRiskLevels:
    """Verify risk_level and requires_confirmation per tool."""

    def _tool_map(self) -> dict[str, ToolDefinition]:
        plugin = _get_plugin()
        return {t.name: t for t in plugin.get_tools()}

    def test_safe_tools(self):
        """get_active_window, get_running_apps, open_application and
        close_application are risk 'safe'."""
        tm = self._tool_map()
        for name in (
            "get_active_window", "get_running_apps",
            "open_application", "close_application",
        ):
            assert tm[name].risk_level == "safe", f"{name} should be safe"

    def test_medium_tools(self):
        """type_text, press_keys, take_screenshot,
        move_mouse, click are risk 'medium'."""
        tm = self._tool_map()
        medium_names = [
            "type_text",
            "press_keys", "take_screenshot", "move_mouse", "click",
        ]
        for name in medium_names:
            assert tm[name].risk_level == "medium", f"{name} should be medium"

    def test_no_dangerous_tools(self):
        """No pc_automation tool is risk 'dangerous' since the exec retirement."""
        tm = self._tool_map()
        assert all(td.risk_level != "dangerous" for td in tm.values())

    def test_confirmation_required(self):
        """All medium/dangerous tools have requires_confirmation=True."""
        tm = self._tool_map()
        for name, td in tm.items():
            if td.risk_level in ("medium", "dangerous"):
                assert td.requires_confirmation, (
                    f"{name} ({td.risk_level}) must require confirmation"
                )

    def test_safe_no_confirmation(self):
        """Safe and low-risk tools have requires_confirmation=False."""
        tm = self._tool_map()
        for name, td in tm.items():
            if td.risk_level == "safe":
                assert not td.requires_confirmation, (
                    f"{name} ({td.risk_level}) should NOT require confirmation"
                )


# ---------------------------------------------------------------------------
# TestPcAutomationExecuteTool
# ---------------------------------------------------------------------------


class TestPcAutomationExecuteTool:
    """Tool execution with mocked system dependencies."""

    # -- open_application --------------------------------------------------

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.executor.validate_app_name")
    @patch("backend.plugins.pc_automation.executor.asyncio.to_thread")
    async def test_exec_open_app_valid(
        self, mock_to_thread, mock_validate, ctx, exec_context,
    ):
        """Opening a whitelisted app succeeds."""
        mock_validate.return_value = (True, "ok", ["notepad.exe"])
        mock_to_thread.return_value = "Application 'notepad' opened (notepad.exe)"

        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "open_application", {"app_name": "notepad"}, exec_context,
        )
        assert result.success
        assert "notepad" in str(result.content).lower()

    @pytest.mark.asyncio
    async def test_exec_open_app_blocked(self, ctx, exec_context):
        """Opening a non-whitelisted app returns error."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "open_application", {"app_name": "malware.exe"}, exec_context,
        )
        assert not result.success
        assert result.error_message

    # -- get_active_window -------------------------------------------------

    @pytest.mark.asyncio
    async def test_exec_get_active_window(
        self, ctx, exec_context,
    ):
        """get_active_window returns the current window title via Win32 API."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "get_active_window", {}, exec_context,
        )
        assert result.success
        # Win32 API returns actual foreground window title or fallback
        assert isinstance(result.content, str)
        assert len(result.content) > 0

    # -- get_running_apps --------------------------------------------------

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.executor.safe_subprocess")
    async def test_exec_get_running_apps(
        self, mock_subprocess, ctx, exec_context,
    ):
        """get_running_apps parses tasklist CSV output."""
        # tasklist /FO CSV /NH /V columns:
        # Image Name, PID, Session Name, Session#, Mem Usage,
        # Status, User Name, CPU Time, Window Title
        mock_subprocess.return_value = (
            '"chrome.exe","1234","Console","1","100,000 K",'
            '"Running","USER","0:00:05","Google Chrome"\n'
            '"notepad.exe","5678","Console","1","10,000 K",'
            '"Running","USER","0:00:01","Untitled - Notepad"\n'
        )

        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "get_running_apps", {}, exec_context,
        )
        assert result.success
        content_str = str(result.content)
        assert "chrome" in content_str or "notepad" in content_str

    # -- type_text ---------------------------------------------------------

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.executor.pyautogui")
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    @patch("backend.plugins.pc_automation.executor._PYPERCLIP_AVAILABLE", True)
    async def test_exec_type_text(
        self, mock_pyautogui, ctx, exec_context,
    ):
        """type_text pastes sanitized text via clipboard (Ctrl+V)."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        with patch(
            "backend.plugins.pc_automation.executor.pyperclip",
            create=True,
        ) as mock_clip:
            mock_clip.paste.return_value = ""
            result = await plugin.execute_tool(
                "type_text", {"text": "Hello AL\\CE"}, exec_context,
            )
            assert result.success
            mock_clip.copy.assert_called()
            mock_pyautogui.hotkey.assert_called_once_with("ctrl", "v")

    # -- press_keys --------------------------------------------------------

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.executor.pyautogui")
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    async def test_exec_press_keys_valid(
        self, mock_pyautogui, ctx, exec_context,
    ):
        """Pressing an allowed combo (ctrl+c) succeeds."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "press_keys", {"keys": ["ctrl", "c"]}, exec_context,
        )
        assert result.success
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "c")

    @pytest.mark.asyncio
    async def test_exec_press_keys_blocked(self, ctx, exec_context):
        """Pressing a forbidden combo (ctrl+alt+delete) returns error."""
        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "press_keys", {"keys": ["ctrl", "alt", "delete"]}, exec_context,
        )
        assert not result.success
        assert result.error_message

    # -- take_screenshot ---------------------------------------------------

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.executor._lockout")
    @patch("backend.plugins.pc_automation.executor.pyautogui")
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    async def test_exec_take_screenshot(
        self, mock_pyautogui, mock_lockout, ctx, exec_context,
    ):
        """take_screenshot returns base64-encoded PNG data."""
        # Build a minimal fake image that writes PNG-like bytes
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        mock_img = MagicMock()
        mock_img.size = (800, 600)
        mock_img.save = MagicMock(
            side_effect=lambda f, **kw: f.write(fake_png),
        )
        mock_pyautogui.screenshot.return_value = mock_img
        mock_lockout.record_screenshot = MagicMock()

        plugin = _get_plugin()
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "take_screenshot", {}, exec_context,
        )
        assert result.success
        # The content should be base64 encoded or raw bytes were produced
        content_str = str(result.content)
        assert len(content_str) > 0


# ---------------------------------------------------------------------------
# TestPcAutomationConnectionStatus
# ---------------------------------------------------------------------------


class TestPcAutomationConnectionStatus:
    """Verify get_connection_status returns correct state."""

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.plugin.check_executor_deps")
    async def test_connected_when_deps_available(
        self, mock_check_deps, ctx,
    ):
        """Status is CONNECTED when all deps are present."""
        mock_check_deps.return_value = []

        plugin = _get_plugin()
        await plugin.initialize(ctx)

        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.plugin.check_executor_deps")
    async def test_disconnected_when_deps_missing(
        self, mock_check_deps, ctx,
    ):
        """Status is DISCONNECTED when dependencies are missing."""
        mock_check_deps.return_value = ["pyautogui"]

        plugin = _get_plugin()
        await plugin.initialize(ctx)

        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.DISCONNECTED
