"""Tests for PC Automation screenshot functionality (Phase 5)."""

import io
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from backend.plugins.pc_automation.constants import (
    MAX_SCREENSHOT_PIXELS,
    SCREENSHOT_LOCKOUT_S,
)
from backend.plugins.pc_automation.security import ScreenshotLockout


class TestScreenshotDownscale:
    """Test screenshot resolution management."""

    @pytest.mark.asyncio
    async def test_small_screenshot_not_downscaled(self):
        """Screenshots under MAX_SCREENSHOT_PIXELS keep original size."""
        import backend.plugins.pc_automation.executor as _exec_mod
        from backend.plugins.pc_automation.executor import exec_take_screenshot

        mock_img = MagicMock()
        mock_img.size = (1000, 1000)

        buf = io.BytesIO()
        buf.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
        buf.seek(0)
        mock_img.save = MagicMock(side_effect=lambda f, **kw: f.write(buf.getvalue()))
        mock_img.resize = MagicMock(return_value=mock_img)

        mock_pyautogui = MagicMock()
        mock_pyautogui.screenshot.return_value = mock_img

        orig_avail = _exec_mod._PYAUTOGUI_AVAILABLE
        orig_pyag = _exec_mod.pyautogui
        try:
            _exec_mod._PYAUTOGUI_AVAILABLE = True
            _exec_mod.pyautogui = mock_pyautogui
            result = await exec_take_screenshot()
        finally:
            _exec_mod._PYAUTOGUI_AVAILABLE = orig_avail
            _exec_mod.pyautogui = orig_pyag

        assert isinstance(result, bytes)
        assert len(result) > 0
        mock_img.resize.assert_not_called()

    @pytest.mark.asyncio
    async def test_large_screenshot_downscaled(self):
        """Screenshots over MAX_SCREENSHOT_PIXELS are downscaled."""
        import backend.plugins.pc_automation.executor as _exec_mod
        from backend.plugins.pc_automation.executor import exec_take_screenshot

        mock_img = MagicMock()
        mock_img.size = (1920, 1080)

        resized_img = MagicMock()
        resized_img.size = (1860, 1046)
        resized_img.save = MagicMock(
            side_effect=lambda f, **kw: f.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 50)
        )
        mock_img.resize.return_value = resized_img

        mock_pyautogui = MagicMock()
        mock_pyautogui.screenshot.return_value = mock_img

        orig_avail = _exec_mod._PYAUTOGUI_AVAILABLE
        orig_pyag = _exec_mod.pyautogui
        try:
            _exec_mod._PYAUTOGUI_AVAILABLE = True
            _exec_mod.pyautogui = mock_pyautogui
            result = await exec_take_screenshot()
        finally:
            _exec_mod._PYAUTOGUI_AVAILABLE = orig_avail
            _exec_mod.pyautogui = orig_pyag

        assert isinstance(result, bytes)
        mock_img.resize.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.executor._PYAUTOGUI_AVAILABLE", False)
    async def test_screenshot_without_pyautogui(self):
        """Screenshot fails gracefully without pyautogui."""
        from backend.plugins.pc_automation.executor import exec_take_screenshot
        
        with pytest.raises(RuntimeError, match="pyautogui is not installed"):
            await exec_take_screenshot()


class TestPostScreenshotLockout:
    """Test that dangerous tools are blocked after screenshots."""

    def test_lockout_initial_state(self):
        """No lockout initially."""
        lockout = ScreenshotLockout()
        assert not lockout.is_locked("execute_command")
        assert lockout.get_remaining_s() == 0.0

    def test_lockout_after_screenshot(self):
        """Only execute_command is locked after screenshot."""
        lockout = ScreenshotLockout()
        lockout.record_screenshot()
        assert lockout.is_locked("execute_command")
        assert lockout.get_remaining_s() > 0

    def test_non_lockout_tool_unaffected(self):
        """Tools not in LOCKOUT_TOOLS are never locked."""
        lockout = ScreenshotLockout()
        lockout.record_screenshot()
        assert not lockout.is_locked("get_active_window")
        assert not lockout.is_locked("get_running_apps")
        assert not lockout.is_locked("type_text")
        assert not lockout.is_locked("open_application")
        assert not lockout.is_locked("press_keys")
        assert not lockout.is_locked("click")
        assert not lockout.is_locked("move_mouse")

    @patch("backend.core.screenshot_lockout.time.monotonic")
    def test_lockout_expires(self, mock_time):
        """Lockout expires after SCREENSHOT_LOCKOUT_S seconds."""
        lockout = ScreenshotLockout()
        
        mock_time.return_value = 100.0
        lockout.record_screenshot()
        
        # Still locked at 100 + 30s
        mock_time.return_value = 130.0
        assert lockout.is_locked("execute_command")
        
        # Unlocked at 100 + 61s
        mock_time.return_value = 161.0
        assert not lockout.is_locked("execute_command")

    @patch("backend.core.screenshot_lockout.time.monotonic")
    def test_remaining_seconds_accuracy(self, mock_time):
        """get_remaining_s returns correct remaining time."""
        lockout = ScreenshotLockout()
        
        mock_time.return_value = 100.0
        lockout.record_screenshot()
        
        mock_time.return_value = 120.0
        remaining = lockout.get_remaining_s()
        assert 39.0 <= remaining <= 41.0  # ~40s remaining

    def test_lockout_thread_safety(self):
        """Lockout is thread-safe (uses threading.Lock)."""
        import threading
        lockout = ScreenshotLockout()
        
        errors = []
        def worker():
            try:
                for _ in range(100):
                    lockout.record_screenshot()
                    lockout.is_locked("execute_command")
                    lockout.get_remaining_s()
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
