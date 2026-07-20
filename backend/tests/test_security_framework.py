"""Tests for PC Automation security framework (Phase 5)."""

import time
from unittest.mock import patch

from backend.core.plugin_models import ToolDefinition
from backend.plugins.pc_automation.constants import (
    ALLOWED_APPS,
)
from backend.plugins.pc_automation.security import (
    ScreenshotLockout,
    validate_app_name,
    validate_keys,
)

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
# TestScreenshotLockout
# ===================================================================


class TestScreenshotLockout:
    """Post-screenshot temporal lockout for dangerous tools."""

    def test_not_locked_initially(self) -> None:
        lockout = ScreenshotLockout()
        assert lockout.is_locked("run_terminal_command") is False

    def test_locked_after_screenshot(self) -> None:
        lockout = ScreenshotLockout()
        lockout.record_screenshot()
        assert lockout.is_locked("run_terminal_command") is True

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
            assert lockout.is_locked("run_terminal_command") is False

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
