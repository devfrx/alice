"""Tests for PC Automation validators module (Phase 5)."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from backend.plugins.pc_automation.constants import (
    COMMAND_TIMEOUT_S,
    MAX_COMMAND_OUTPUT_CHARS,
)
from backend.plugins.pc_automation.validators import (
    safe_subprocess,
    sanitize_text_input,
)


class TestSafeSubprocess:
    """Test hardened subprocess execution."""

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.validators.subprocess.run")
    async def test_basic_command(self, mock_run):
        """Executes command and returns stdout."""
        mock_run.return_value = MagicMock(
            stdout="output text", stderr="", returncode=0
        )
        result = await safe_subprocess("echo", ["hello"])
        assert result == "output text"
        mock_run.assert_called_once()
        # Verify shell=False
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("shell") is False or call_kwargs[1].get("shell") is False

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.validators.subprocess.run")
    async def test_includes_stderr(self, mock_run):
        """Includes stderr in output."""
        mock_run.return_value = MagicMock(
            stdout="out", stderr="err", returncode=0
        )
        result = await safe_subprocess("cmd")
        assert "out" in result
        assert "err" in result

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.validators.subprocess.run")
    async def test_output_truncation(self, mock_run):
        """Output exceeding MAX_COMMAND_OUTPUT_CHARS is truncated."""
        long_output = "x" * (MAX_COMMAND_OUTPUT_CHARS + 100)
        mock_run.return_value = MagicMock(
            stdout=long_output, stderr="", returncode=0
        )
        result = await safe_subprocess("cmd")
        assert len(result) <= MAX_COMMAND_OUTPUT_CHARS + 50  # allow for truncation message
        assert "truncated" in result

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.validators.subprocess.run")
    async def test_timeout_raises(self, mock_run):
        """TimeoutExpired raises TimeoutError."""
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
        with pytest.raises(TimeoutError, match="timed out"):
            await safe_subprocess("cmd", timeout=30)

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.validators.subprocess.run")
    async def test_not_found_raises(self, mock_run):
        """FileNotFoundError raises OSError."""
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(OSError, match="not found"):
            await safe_subprocess("nonexistent_cmd")

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.validators.subprocess.run")
    async def test_uses_default_timeout(self, mock_run):
        """Uses COMMAND_TIMEOUT_S as default timeout."""
        mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        await safe_subprocess("echo")
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("timeout") == COMMAND_TIMEOUT_S or call_kwargs[1].get("timeout") == COMMAND_TIMEOUT_S

    @pytest.mark.asyncio
    @patch("backend.plugins.pc_automation.validators.subprocess.run")
    async def test_shell_always_false(self, mock_run):
        """shell parameter is always False."""
        mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        await safe_subprocess("echo", ["test"])
        call_kwargs = mock_run.call_args
        shell_val = call_kwargs.kwargs.get("shell", call_kwargs[1].get("shell", None))
        assert shell_val is False


class TestSanitizeTextInput:
    """Test text input sanitization."""

    def test_normal_text(self):
        """Normal text passes through."""
        assert sanitize_text_input("Hello world") == "Hello world"

    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        assert sanitize_text_input("  hello  ") == "hello"

    def test_preserves_internal_whitespace(self):
        """Internal spaces and newlines are preserved."""
        result = sanitize_text_input("line 1\nline 2")
        assert "\n" in result

    def test_empty_text_raises(self):
        """Empty text raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            sanitize_text_input("")

    def test_too_long_raises(self):
        """Text exceeding max_length raises ValueError."""
        with pytest.raises(ValueError, match="too long"):
            sanitize_text_input("x" * 1001)

    def test_custom_max_length(self):
        """Custom max_length is respected."""
        with pytest.raises(ValueError, match="too long"):
            sanitize_text_input("x" * 11, max_length=10)

    def test_control_chars_removed(self):
        """Control characters (except newline/tab) are removed."""
        result = sanitize_text_input("hello\x00world\x01test")
        assert "\x00" not in result
        assert "\x01" not in result
        assert "hello" in result

    def test_tabs_preserved(self):
        """Tab characters are preserved."""
        result = sanitize_text_input("col1\tcol2")
        assert "\t" in result
