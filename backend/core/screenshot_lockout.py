"""AL\\CE — shared post-screenshot security lockout (core).

After a screenshot is captured, certain dangerous tools are temporarily
blocked to prevent prompt-injection attacks from exfiltrating screen
contents via tool chaining. This policy is owned by ``core`` so that a
single process-wide instance protects **every** dangerous tool from one
screenshot event — today the scoped terminal's ``run_terminal_command``,
the single exec path since ``pc_automation.execute_command`` was retired
(Fase 2).

The lockout is intentionally synchronous and guarded by a
``threading.Lock``: it is recorded from inside the blocking screenshot
worker thread (``asyncio.to_thread``) and read from the async event loop.

This module is pure ``core`` and must not import from ``backend.plugins``.
The ``pc_automation`` package re-exports these names so all existing imports
keep working against the single shared instance.
"""

from __future__ import annotations

import threading
import time

SCREENSHOT_LOCKOUT_S: float = 60.0
"""Seconds to block dangerous tools after a screenshot is taken."""

LOCKOUT_TOOLS: frozenset[str] = frozenset({"run_terminal_command"})
"""Raw tool names blocked while a screenshot lockout is active (anti-exfiltration)."""


class ScreenshotLockout:
    """Thread-safe lockout manager for post-screenshot security.

    After a screenshot is taken, the tools in :data:`LOCKOUT_TOOLS` (such as
    ``run_terminal_command``) are blocked for :data:`SCREENSHOT_LOCKOUT_S`
    seconds to prevent prompt-injection attacks that could exfiltrate
    screenshot data.
    """

    def __init__(self) -> None:
        self._last_screenshot: float = 0.0
        self._lock = threading.Lock()

    def record_screenshot(self) -> None:
        """Record that a screenshot was just taken."""
        with self._lock:
            self._last_screenshot = time.monotonic()

    def is_locked(self, tool_name: str) -> bool:
        """Check if a tool is currently locked due to a recent screenshot.

        Args:
            tool_name: The raw tool name (without plugin prefix).

        Returns:
            True if the tool is blocked, False otherwise.
        """
        if tool_name not in LOCKOUT_TOOLS:
            return False
        with self._lock:
            if self._last_screenshot == 0.0:
                return False
            return (time.monotonic() - self._last_screenshot) < SCREENSHOT_LOCKOUT_S

    def get_remaining_s(self) -> float:
        """Return remaining lockout seconds (0.0 if not locked)."""
        with self._lock:
            if self._last_screenshot == 0.0:
                return 0.0
            elapsed = time.monotonic() - self._last_screenshot
            remaining = SCREENSHOT_LOCKOUT_S - elapsed
            return max(0.0, remaining)


# Process-wide singleton — owned by core so a single screenshot locks out
# every dangerous tool across all plugins (pc_automation + terminal).
_lockout = ScreenshotLockout()


def get_lockout() -> ScreenshotLockout:
    """Return the shared process-wide screenshot lockout instance."""
    return _lockout
