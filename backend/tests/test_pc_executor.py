"""Tests for PC Automation executor module (Phase 5)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from backend.plugins.pc_automation.executor import (
    _tokenize_command,
    exec_open_app,
    exec_close_app,
    exec_type_text,
    exec_press_keys,
    exec_get_active_window,
    exec_get_running_apps,
    exec_command,
    exec_move_mouse,
    exec_click,
    check_dependencies,
)


class TestCheckDependencies:
    """Test dependency checking."""

    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    @patch("backend.plugins.pc_automation.executor._PYWINAUTO_AVAILABLE", True)
    def test_all_available(self):
        assert check_dependencies() == []

    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", False)
    @patch("backend.plugins.pc_automation.executor._PYWINAUTO_AVAILABLE", False)
    def test_all_missing(self):
        missing = check_dependencies()
        assert "pyautogui" in missing
        assert "pywinauto" in missing


@pytest.mark.asyncio
class TestExecOpenApp:
    """Test opening applications."""

    @patch("backend.plugins.pc_automation.executor.asyncio.to_thread")
    async def test_open_valid_app(self, mock_to_thread):
        mock_to_thread.return_value = "Application 'notepad' opened (notepad.exe)"
        result = await exec_open_app("notepad")
        assert "notepad" in result.lower()

    async def test_open_invalid_app(self):
        with pytest.raises(ValueError, match="not in the whitelist"):
            await exec_open_app("malware.exe")

    async def test_open_empty_name(self):
        with pytest.raises(ValueError):
            await exec_open_app("")


@pytest.mark.asyncio
class TestExecCloseApp:
    """Test closing applications."""

    @patch("backend.plugins.pc_automation.executor.safe_subprocess")
    async def test_close_valid_app(self, mock_subprocess):
        mock_subprocess.return_value = "SUCCESS: Terminated process notepad.exe"
        result = await exec_close_app("notepad")
        assert "notepad" in result.lower()

    async def test_close_invalid_app(self):
        with pytest.raises(ValueError, match="not in the whitelist"):
            await exec_close_app("virus.exe")


@pytest.mark.asyncio
class TestExecTypeText:
    """Test text typing."""

    @patch("backend.plugins.pc_automation.executor.pyautogui")
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    async def test_type_valid_text(self, mock_pyautogui):
        result = await exec_type_text("Hello world")
        assert "11" in result or "characters" in result

    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", False)
    async def test_type_without_pyautogui(self):
        with pytest.raises(RuntimeError, match="pyautogui is not installed"):
            await exec_type_text("test")

    async def test_type_empty_text(self):
        with pytest.raises(ValueError):
            await exec_type_text("")


@pytest.mark.asyncio
class TestExecPressKeys:
    """Test key pressing."""

    @patch("backend.plugins.pc_automation.executor.pyautogui")
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    async def test_press_allowed_combo(self, mock_pyautogui):
        result = await exec_press_keys(["ctrl", "c"])
        assert "ctrl" in result.lower()

    async def test_press_forbidden_combo(self):
        with pytest.raises(ValueError, match="forbidden"):
            await exec_press_keys(["ctrl", "alt", "delete"])

    async def test_press_unknown_key(self):
        with pytest.raises(ValueError, match="not recognized"):
            await exec_press_keys(["nonexistent_key"])

    async def test_press_empty_keys(self):
        with pytest.raises(ValueError):
            await exec_press_keys([])


class TestTokenizeCommand:
    """Test _tokenize_command helper for quote-aware splitting."""

    def test_simple_command(self):
        assert _tokenize_command("ipconfig") == ["ipconfig"]

    def test_command_with_args(self):
        assert _tokenize_command("ping 127.0.0.1") == ["ping", "127.0.0.1"]

    def test_quoted_path(self):
        result = _tokenize_command('dir "C:\\Users\\Jays\\Desktop"')
        assert result == ["dir", "C:\\Users\\Jays\\Desktop"]

    def test_quoted_path_with_spaces(self):
        result = _tokenize_command('move "C:\\My Folder\\file.jpg" "C:\\target"')
        assert result == ["move", "C:\\My Folder\\file.jpg", "C:\\target"]

    def test_trailing_backslash_stripped(self):
        """The cmd.exe \\\" bug: trailing \\ in quoted path must be stripped."""
        result = _tokenize_command('move "C:\\src\\file.jpg" "C:\\dest\\"')
        assert result == ["move", "C:\\src\\file.jpg", "C:\\dest"]

    def test_unquoted_trailing_backslash(self):
        result = _tokenize_command("mkdir C:\\Users\\Desktop\\folder\\")
        assert result == ["mkdir", "C:\\Users\\Desktop\\folder"]

    def test_mixed_quoted_unquoted(self):
        result = _tokenize_command('move file.txt "C:\\My Folder\\"')
        assert result == ["move", "file.txt", "C:\\My Folder"]

    def test_single_char_token_preserved(self):
        """Single-char tokens (like drive letter) are NOT rstripped."""
        result = _tokenize_command('dir C:')
        assert result == ["dir", "C:"]


@pytest.mark.asyncio
class TestExecCommand:
    """Test command execution."""

    @patch("backend.plugins.pc_automation.executor._lockout")
    @patch("backend.plugins.pc_automation.executor.safe_subprocess")
    async def test_valid_command(self, mock_subprocess, mock_lockout):
        mock_lockout.is_locked.return_value = False
        mock_subprocess.return_value = "Windows IP Configuration\n..."
        result = await exec_command("ipconfig")
        assert "Windows" in result or "IP" in result

    @patch("backend.plugins.pc_automation.executor._lockout")
    async def test_blocked_command(self, mock_lockout):
        mock_lockout.is_locked.return_value = False
        with pytest.raises(ValueError, match="not whitelisted"):
            await exec_command("rm -rf /")

    @patch("backend.plugins.pc_automation.executor._lockout")
    async def test_shell_injection(self, mock_lockout):
        mock_lockout.is_locked.return_value = False
        with pytest.raises(ValueError):
            await exec_command("ipconfig; rm -rf /")

    @patch("backend.plugins.pc_automation.executor._lockout")
    async def test_command_during_lockout(self, mock_lockout):
        mock_lockout.is_locked.return_value = True
        mock_lockout.get_remaining_s.return_value = 45.0
        with pytest.raises(RuntimeError, match="locked"):
            await exec_command("ipconfig")

    @patch("backend.plugins.pc_automation.executor._lockout")
    @patch("backend.plugins.pc_automation.executor.safe_subprocess")
    async def test_move_with_quoted_trailing_backslash(
        self, mock_subprocess, mock_lockout,
    ):
        """Regression: cmd.exe \\\" bug with trailing backslash in destination."""
        mock_lockout.is_locked.return_value = False
        mock_subprocess.return_value = "1 file spostato/i."
        await exec_command(
            'move "C:\\Users\\Jays\\Desktop\\file.jpg" "C:\\Users\\Jays\\Desktop\\immagini\\"'
        )
        mock_subprocess.assert_called_once_with(
            "cmd.exe",
            ["/c", "move", "C:\\Users\\Jays\\Desktop\\file.jpg",
             "C:\\Users\\Jays\\Desktop\\immagini"],
        )

    @patch("backend.plugins.pc_automation.executor._lockout")
    @patch("backend.plugins.pc_automation.executor.safe_subprocess")
    async def test_move_with_spaces_in_path(
        self, mock_subprocess, mock_lockout,
    ):
        """Quoted paths with spaces must be kept as single tokens."""
        mock_lockout.is_locked.return_value = False
        mock_subprocess.return_value = "1 file spostato/i."
        await exec_command(
            'move "C:\\Users\\Jays\\Desktop\\my file.jpg" "C:\\target"'
        )
        mock_subprocess.assert_called_once_with(
            "cmd.exe",
            ["/c", "move", "C:\\Users\\Jays\\Desktop\\my file.jpg", "C:\\target"],
        )


@pytest.mark.asyncio
class TestExecGetActiveWindow:
    """Test active window detection."""

    @patch("backend.plugins.pc_automation.executor.pyautogui")
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    async def test_get_window_title(self, mock_pyautogui):
        mock_window = MagicMock()
        mock_window.title = "My Window"
        mock_pyautogui.getActiveWindow.return_value = mock_window
        result = await exec_get_active_window()
        assert "My Window" in result

    @patch("backend.plugins.pc_automation.executor.pyautogui")
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    async def test_get_window_none(self, mock_pyautogui):
        mock_pyautogui.getActiveWindow.return_value = None
        result = await exec_get_active_window()
        assert "no active window" in result.lower()


@pytest.mark.asyncio
class TestExecMouseOperations:
    """Test mouse move and click."""

    @patch("backend.plugins.pc_automation.executor.pyautogui")
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    async def test_move_mouse(self, mock_pyautogui):
        mock_pyautogui.size.return_value = (1920, 1080)
        result = await exec_move_mouse(100, 200)
        assert "100" in result and "200" in result

    @patch("backend.plugins.pc_automation.executor.pyautogui")
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", True)
    async def test_click_valid(self, mock_pyautogui):
        mock_pyautogui.size.return_value = (1920, 1080)
        result = await exec_click(100, 200, "left")
        assert "left" in result

    async def test_click_invalid_button(self):
        with pytest.raises(ValueError, match="Invalid button"):
            await exec_click(100, 200, "invalid")
