"""Tests for PC Automation security framework (Phase 5)."""

import pytest
import time
from unittest.mock import patch

from backend.plugins.pc_automation.constants import (
    ALLOWED_APPS,
    ALLOWED_KEY_COMBOS,
    COMMAND_WHITELIST,
    FORBIDDEN_KEY_COMBOS,
    FORBIDDEN_PATHS,
)
from backend.plugins.pc_automation.security import (
    ScreenshotLockout,
    validate_app_name,
    validate_command,
    validate_keys,
    validate_path,
)
from backend.core.plugin_models import ToolDefinition


# ===================================================================
# TestValidateAppName
# ===================================================================


class TestValidateAppName:
    """Validate application name resolution against the whitelist."""

    def test_valid_app(self) -> None:
        ok, msg, exe = validate_app_name("notepad")
        assert ok is True
        assert exe == "notepad.exe"
        assert "resolved" in msg.lower() or "notepad" in msg.lower()

    def test_valid_app_case_insensitive(self) -> None:
        ok, _msg, exe = validate_app_name("Notepad")
        assert ok is True
        assert exe == "notepad.exe"

    def test_invalid_app(self) -> None:
        ok, msg, exe = validate_app_name("malware")
        assert ok is False
        assert exe is None
        assert "not in the whitelist" in msg

    def test_empty_app(self) -> None:
        ok, _msg, exe = validate_app_name("")
        assert ok is False
        assert exe is None

    def test_app_with_list_executable(self) -> None:
        """Apps mapped to a list of candidates resolve to the first entry."""
        ok, _msg, exe = validate_app_name("chrome")
        assert ok is True
        # ALLOWED_APPS["chrome"] is a list — resolved exe is its first element
        expected = ALLOWED_APPS["chrome"]
        assert isinstance(expected, list)
        assert exe == expected[0]


# ===================================================================
# TestValidateCommand
# ===================================================================


class TestValidateCommand:
    """Validate command whitelist and shell-injection blocking."""

    def test_valid_command(self) -> None:
        ok, msg = validate_command("ipconfig")
        assert ok is True
        assert "whitelisted" in msg.lower()

    def test_valid_command_with_args(self) -> None:
        ok, _msg = validate_command("ping 127.0.0.1")
        assert ok is True

    def test_invalid_command(self) -> None:
        ok, msg = validate_command("rm")
        assert ok is False
        assert "not whitelisted" in msg.lower()

    def test_shell_injection_semicolon(self) -> None:
        ok, msg = validate_command("ipconfig; rm -rf /")
        assert ok is False
        # Rejected either as unrecognised command or shell metacharacter
        assert "not whitelisted" in msg.lower() or "not allowed" in msg.lower()

    def test_shell_injection_pipe(self) -> None:
        ok, msg = validate_command("ipconfig | evil")
        assert ok is False
        assert "not allowed" in msg.lower()

    def test_shell_injection_ampersand(self) -> None:
        ok, msg = validate_command("ipconfig & evil")
        assert ok is False
        assert "not allowed" in msg.lower()

    def test_shell_injection_backtick(self) -> None:
        ok, msg = validate_command("ipconfig `evil`")
        assert ok is False
        assert "not allowed" in msg.lower()

    def test_empty_command(self) -> None:
        ok, msg = validate_command("")
        assert ok is False
        assert "empty" in msg.lower()

    def test_newline_injection(self) -> None:
        ok, msg = validate_command("dir C:\\Users\necho pwned")
        assert ok is False
        assert "newline" in msg.lower()

    def test_carriage_return_injection(self) -> None:
        ok, msg = validate_command("dir C:\\Users\r\necho pwned")
        assert ok is False
        assert "newline" in msg.lower()


# ===================================================================
# TestValidateKeys
# ===================================================================


class TestValidateKeys:
    """Validate key combos against allowed/forbidden lists."""

    def test_single_key(self) -> None:
        ok, _msg = validate_keys(["enter"])
        assert ok is True

    def test_allowed_combo(self) -> None:
        ok, _msg = validate_keys(["ctrl", "c"])
        assert ok is True

    def test_forbidden_combo_ctrl_alt_del(self) -> None:
        ok, msg = validate_keys(["ctrl", "alt", "delete"])
        assert ok is False
        assert "forbidden" in msg.lower()

    def test_forbidden_combo_win_r(self) -> None:
        ok, msg = validate_keys(["win", "r"])
        assert ok is False
        assert "forbidden" in msg.lower()

    def test_unknown_key(self) -> None:
        ok, msg = validate_keys(["zzzz"])
        assert ok is False
        assert "not recognized" in msg.lower()

    def test_disallowed_modifier_combo(self) -> None:
        """A modifier combo not in the allowed list is rejected."""
        ok, msg = validate_keys(["alt", "f4"])
        assert ok is False
        # Should be caught as forbidden or not allowed
        assert "forbidden" in msg.lower() or "not in the allowed" in msg.lower()

    def test_empty_keys(self) -> None:
        ok, msg = validate_keys([])
        assert ok is False
        assert "empty" in msg.lower()


# ===================================================================
# TestValidatePath
# ===================================================================


class TestValidatePath:
    """Validate path traversal blocking against FORBIDDEN_PATHS."""

    def test_valid_path(self) -> None:
        ok, _msg = validate_path("C:\\Users\\Test\\file.txt")
        assert ok is True

    def test_forbidden_windows_dir(self) -> None:
        ok, msg = validate_path("C:\\Windows\\System32\\config")
        assert ok is False
        assert "protected" in msg.lower()

    def test_forbidden_program_files(self) -> None:
        ok, msg = validate_path("C:\\Program Files\\test")
        assert ok is False
        assert "protected" in msg.lower()

    def test_relative_path_ok(self) -> None:
        """A relative path that does not resolve into a system dir passes."""
        # This resolves against cwd which should be the project root,
        # not a system directory.
        ok, _msg = validate_path("relative/path.txt")
        assert ok is True

    def test_empty_path(self) -> None:
        ok, msg = validate_path("")
        assert ok is False
        assert "empty" in msg.lower()


# ===================================================================
# TestScreenshotLockout
# ===================================================================


class TestScreenshotLockout:
    """Post-screenshot temporal lockout for dangerous tools."""

    def test_not_locked_initially(self) -> None:
        lockout = ScreenshotLockout()
        assert lockout.is_locked("execute_command") is False

    def test_locked_after_screenshot(self) -> None:
        lockout = ScreenshotLockout()
        lockout.record_screenshot()
        assert lockout.is_locked("execute_command") is True

    def test_unlocked_after_timeout(self) -> None:
        lockout = ScreenshotLockout()
        lockout.record_screenshot()
        # Fast-forward time past the lockout window
        with patch("backend.core.screenshot_lockout.time") as mock_time:
            # First call to monotonic() is the record (already happened),
            # subsequent calls simulate time after lockout expiry.
            t0 = time.monotonic()
            lockout._last_screenshot = t0
            mock_time.monotonic.return_value = t0 + 61
            assert lockout.is_locked("execute_command") is False

    def test_non_lockout_tool_not_affected(self) -> None:
        lockout = ScreenshotLockout()
        lockout.record_screenshot()
        assert lockout.is_locked("get_active_window") is False

    def test_remaining_seconds(self) -> None:
        lockout = ScreenshotLockout()
        lockout.record_screenshot()
        remaining = lockout.get_remaining_s()
        assert remaining > 0


# ===================================================================
# TestForbiddenToolEnforcement
# ===================================================================


class TestForbiddenToolEnforcement:
    """Verify ToolDefinition accepts all risk levels including forbidden."""

    def test_tool_definition_forbidden(self) -> None:
        td = ToolDefinition(
            name="dangerous_tool",
            description="A forbidden tool",
            risk_level="forbidden",
        )
        assert td.risk_level == "forbidden"

    def test_all_risk_levels_valid(self) -> None:
        for level in ("safe", "medium", "dangerous", "forbidden"):
            td = ToolDefinition(
                name=f"tool_{level}",
                description=f"Tool with risk {level}",
                risk_level=level,
            )
            assert td.risk_level == level

    def test_forbidden_combined_with_confirmation(self) -> None:
        td = ToolDefinition(
            name="forbidden_confirmed",
            description="Forbidden tool that also requires confirmation",
            risk_level="forbidden",
            requires_confirmation=True,
        )
        assert td.risk_level == "forbidden"
        assert td.requires_confirmation is True


# ===================================================================
# TestForbiddenFlags
# ===================================================================


class TestForbiddenFlags:
    """FORBIDDEN_FLAGS must block dangerous flags for destructive commands."""

    def test_rmdir_s_blocked(self) -> None:
        valid, msg = validate_command("rmdir /s /q C:\\temp")
        assert not valid
        assert "/s" in msg or "/q" in msg

    def test_rmdir_q_blocked(self) -> None:
        valid, msg = validate_command("rmdir /q C:\\temp")
        assert not valid
        assert "/q" in msg

    def test_rd_s_blocked(self) -> None:
        valid, msg = validate_command("rd /s /q C:\\temp")
        assert not valid
        assert "/s" in msg or "/q" in msg

    def test_robocopy_mir_blocked(self) -> None:
        valid, msg = validate_command("robocopy C:\\src C:\\dst /mir")
        assert not valid
        assert "/mir" in msg

    def test_robocopy_purge_blocked(self) -> None:
        valid, msg = validate_command("robocopy C:\\src C:\\dst /purge")
        assert not valid
        assert "/purge" in msg

    def test_robocopy_move_blocked(self) -> None:
        valid, msg = validate_command("robocopy C:\\src C:\\dst /move")
        assert not valid
        assert "/move" in msg

    def test_rmdir_without_forbidden_flags_allowed(self) -> None:
        """rmdir without /s or /q should pass the flag check."""
        valid, msg = validate_command("rmdir C:\\temp\\empty_dir")
        # Should not be blocked by forbidden-flag logic.
        # It may still be blocked by path validation, but NOT by flag check.
        assert "forbidden" not in msg.lower() or valid

    def test_robocopy_with_safe_flags_allowed(self) -> None:
        """robocopy with non-destructive flags should pass flag check."""
        valid, msg = validate_command("robocopy C:\\src C:\\dst /e /r:3")
        assert "forbidden" not in msg.lower() or valid


# ===================================================================
# TestShellMetacharacters
# ===================================================================


class TestShellMetacharacters:
    """Shell chaining operators must be blocked by the metacharacter check.

    Uses whitelisted base commands (dir, echo) so the test reaches the
    metacharacter check instead of failing at the whitelist check.
    """

    def test_pipe_blocked(self) -> None:
        valid, msg = validate_command("dir | findstr test")
        assert not valid
        assert "metacharacter" in msg.lower() or "|" in msg

    def test_ampersand_blocked(self) -> None:
        valid, msg = validate_command("dir & echo pwned")
        assert not valid
        assert "metacharacter" in msg.lower() or "&" in msg

    def test_semicolon_blocked(self) -> None:
        valid, msg = validate_command("echo hello; echo world")
        assert not valid
        assert "metacharacter" in msg.lower() or ";" in msg

    def test_backtick_blocked(self) -> None:
        valid, msg = validate_command("echo `whoami`")
        assert not valid
        assert "metacharacter" in msg.lower() or "`" in msg

    def test_redirect_out_blocked(self) -> None:
        valid, msg = validate_command("echo secret > file.txt")
        assert not valid
        assert "metacharacter" in msg.lower() or ">" in msg

    def test_redirect_in_blocked(self) -> None:
        valid, msg = validate_command("findstr pattern < input.txt")
        assert not valid
        assert "metacharacter" in msg.lower() or "<" in msg

    def test_env_var_percent_blocked(self) -> None:
        valid, msg = validate_command("echo %USERNAME%")
        assert not valid
        assert "variable" in msg.lower() or "%" in msg

    def test_env_var_dollar_blocked(self) -> None:
        valid, msg = validate_command("echo $HOME")
        assert not valid
        assert "variable" in msg.lower() or "$" in msg


# ===================================================================
# TestPathValidationExtended
# ===================================================================


class TestPathValidationExtended:
    """Extended path validation: UNC, device and extended-length paths."""

    def test_unc_path_blocked(self) -> None:
        valid, _msg = validate_path("\\\\server\\share\\file.txt")
        assert not valid

    def test_device_path_blocked(self) -> None:
        valid, _msg = validate_path("\\\\.\\PhysicalDrive0")
        assert not valid

    def test_system_dir_blocked(self) -> None:
        valid, msg = validate_path("C:\\Windows\\System32\\cmd.exe")
        assert not valid
        assert "protected" in msg.lower()

    def test_safe_user_path_allowed(self) -> None:
        valid, msg = validate_path("C:\\Users\\test\\Documents\\file.txt")
        assert valid
