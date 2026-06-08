"""Tests for the shared core screenshot lockout (Fase 6d).

Verifies the lockout was promoted to :mod:`backend.core.screenshot_lockout`
as a single process-wide instance covering both ``execute_command`` and the
scoped terminal's ``run_terminal_command``, and that the ``pc_automation``
re-export shims resolve to the very same class and singleton.
"""

from __future__ import annotations

from backend.core.screenshot_lockout import (
    LOCKOUT_TOOLS,
    SCREENSHOT_LOCKOUT_S,
    ScreenshotLockout,
    get_lockout,
)


def test_lockout_tools_cover_both_dangerous_tools() -> None:
    """Both the PC-automation and terminal tools are in the lockout set."""
    assert "execute_command" in LOCKOUT_TOOLS
    assert "run_terminal_command" in LOCKOUT_TOOLS


def test_fresh_lockout_not_locked_before_screenshot() -> None:
    """A fresh lockout blocks nothing until a screenshot is recorded."""
    lockout = ScreenshotLockout()
    assert lockout.is_locked("execute_command") is False
    assert lockout.is_locked("run_terminal_command") is False


def test_screenshot_locks_both_tools() -> None:
    """One screenshot locks out every tracked tool, but not untracked ones."""
    lockout = ScreenshotLockout()
    lockout.record_screenshot()

    assert lockout.is_locked("execute_command") is True
    assert lockout.is_locked("run_terminal_command") is True
    # A tool name that is not part of the lockout set is never blocked.
    assert lockout.is_locked("something_else") is False


def test_remaining_seconds_shape() -> None:
    """``get_remaining_s`` is 0.0 before, and within (0, window] after."""
    lockout = ScreenshotLockout()
    assert lockout.get_remaining_s() == 0.0

    lockout.record_screenshot()
    remaining = lockout.get_remaining_s()
    assert 0.0 < remaining <= SCREENSHOT_LOCKOUT_S


def test_get_lockout_returns_process_singleton() -> None:
    """``get_lockout`` hands back the same instance every call."""
    assert get_lockout() is get_lockout()
    assert isinstance(get_lockout(), ScreenshotLockout)


def test_pc_automation_security_reexports_same_class() -> None:
    """The pc_automation re-export is the very same class object."""
    from backend.plugins.pc_automation.security import ScreenshotLockout as PcSL

    assert PcSL is ScreenshotLockout


def test_pc_automation_executor_shares_core_singleton() -> None:
    """executor.get_lockout resolves to the core process singleton."""
    from backend.plugins.pc_automation.executor import get_lockout as pc_get_lockout

    assert pc_get_lockout() is get_lockout()


def test_pc_automation_constants_reexport_core_values() -> None:
    """constants.* now point at the single core source of truth."""
    from backend.plugins.pc_automation import constants

    assert constants.LOCKOUT_TOOLS is LOCKOUT_TOOLS
    assert constants.SCREENSHOT_LOCKOUT_S == SCREENSHOT_LOCKOUT_S
