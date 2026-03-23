"""AL\\CE — PC Automation security framework.

Validates tool inputs against whitelists and manages the post-screenshot
lockout to prevent data exfiltration via tool chaining.
"""

from __future__ import annotations

import re
import time
import threading
from pathlib import Path, PureWindowsPath

from loguru import logger

from backend.plugins.pc_automation.constants import (
    ALLOWED_APPS,
    ALLOWED_KEYS,
    ALLOWED_KEY_COMBOS,
    COMMAND_WHITELIST,
    FILE_MANAGEMENT_CMDS,
    FORBIDDEN_FLAGS,
    FORBIDDEN_KEY_COMBOS,
    FORBIDDEN_PATHS,
    LOCKOUT_TOOLS,
    SCREENSHOT_LOCKOUT_S,
    SYSTEM_DIRS,
)


class ScreenshotLockout:
    """Thread-safe lockout manager for post-screenshot security.

    After a screenshot is taken, certain dangerous tools (like execute_command)
    are blocked for SCREENSHOT_LOCKOUT_S seconds to prevent prompt injection
    attacks that could exfiltrate screenshot data.
    """

    def __init__(self) -> None:
        self._last_screenshot: float = 0.0
        self._lock = threading.Lock()

    def record_screenshot(self) -> None:
        """Record that a screenshot was just taken."""
        with self._lock:
            self._last_screenshot = time.monotonic()

    def is_locked(self, tool_name: str) -> bool:
        """Check if a tool is currently locked due to recent screenshot.

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
        """Get remaining lockout seconds (0.0 if not locked)."""
        with self._lock:
            if self._last_screenshot == 0.0:
                return 0.0
            elapsed = time.monotonic() - self._last_screenshot
            remaining = SCREENSHOT_LOCKOUT_S - elapsed
            return max(0.0, remaining)


def validate_app_name(app_name: str) -> tuple[bool, str, str | None]:
    """Validate an application name against the whitelist.

    Args:
        app_name: User-provided application name (case-insensitive).

    Returns:
        Tuple of ``(is_valid, message, primary_executable_or_None)``.
        The third element is the primary (first) executable name when the
        app is whitelisted, or ``None`` when rejected.
    """
    normalized = app_name.strip().lower().replace(" ", "_")

    if normalized not in ALLOWED_APPS:
        allowed = ", ".join(sorted(ALLOWED_APPS.keys()))
        return False, f"Application '{app_name}' is not in the whitelist. Allowed: {allowed}", None

    executable = ALLOWED_APPS[normalized]
    # Resolve to the primary (first) candidate
    if isinstance(executable, list):
        primary = executable[0]
    else:
        primary = executable

    return True, f"Application '{normalized}' is whitelisted", primary


def validate_command(command: str) -> tuple[bool, str]:
    """Validate a command against the whitelist.

    Only the base command name is checked (first token). Arguments are allowed
    but the command itself must be whitelisted.

    Args:
        command: Full command string.

    Returns:
        Tuple of (is_valid, message).
    """
    if not command or not command.strip():
        return False, "Empty command"

    # Block newline/CR characters — these act as command separators
    # in cmd.exe /c context, enabling command injection.
    if "\n" in command or "\r" in command:
        return False, "Newline characters are not allowed in commands"

    # Extract base command (first token)
    parts = command.strip().split()
    base_cmd = parts[0].lower()

    # Remove .exe extension if present
    if base_cmd.endswith(".exe"):
        base_cmd = base_cmd[:-4]

    if base_cmd not in COMMAND_WHITELIST:
        allowed = ", ".join(sorted(COMMAND_WHITELIST.keys()))
        return False, f"Command '{base_cmd}' is not whitelisted. Allowed: {allowed}"

    # Block shell chaining operators (dangerous even with cmd.exe /c)
    chaining_chars = {";", "|", "&", "`", "<", ">"}
    for char in chaining_chars:
        if char in command:
            return False, f"Shell metacharacter '{char}' is not allowed in commands"

    # Block environment variable expansion (%VAR% and $VAR)
    if "%" in command or "$" in command:
        return False, "Environment variable references are not allowed in commands"

    # Block forbidden flags for destructive commands
    if base_cmd in FORBIDDEN_FLAGS:
        args_lower = command.lower().split()
        for flag in FORBIDDEN_FLAGS[base_cmd]:
            if flag in args_lower:
                return False, f"Flag '{flag}' is forbidden for command '{base_cmd}'"

    # Path validation for file management commands —
    # resolve paths and check against protected directories.
    if base_cmd in FILE_MANAGEMENT_CMDS:
        args_str = command.strip()[len(parts[0]):].strip()
        # Extract path-like tokens and validate each
        for token in _extract_path_tokens(args_str):
            valid, msg = validate_path(token)
            if not valid:
                return False, msg

    return True, f"Command '{base_cmd}' is whitelisted"


def _extract_path_tokens(args_str: str) -> list[str]:
    """Extract path-like tokens from a command argument string.

    Handles both quoted paths ("C:\\My Folder") and unquoted paths.
    Skips tokens that start with '/' (command flags).
    """
    tokens: list[str] = []
    i = 0
    while i < len(args_str):
        c = args_str[i]
        if c in ('"', "'"):
            # Quoted token — find closing quote
            end = args_str.find(c, i + 1)
            if end == -1:
                end = len(args_str)
            token = args_str[i + 1 : end]
            tokens.append(token)
            i = end + 1
        elif c == ' ':
            i += 1
        else:
            # Unquoted token — read until space
            end = args_str.find(' ', i)
            if end == -1:
                end = len(args_str)
            token = args_str[i:end]
            # Skip command flags (e.g. /E, /R:3)
            if not token.startswith('/'):
                tokens.append(token)
            i = end + 1
    return tokens


def validate_keys(keys: list[str]) -> tuple[bool, str]:
    """Validate a key combination against allowed/forbidden lists.

    Args:
        keys: List of key names (e.g. ["ctrl", "c"]).

    Returns:
        Tuple of (is_valid, message).
    """
    if not keys:
        return False, "Empty key list"

    # Normalize all keys to lowercase
    normalized = [k.strip().lower() for k in keys]

    # Check each individual key is known
    for key in normalized:
        if key not in ALLOWED_KEYS:
            return False, f"Key '{key}' is not recognized"

    # Check against forbidden combos
    sorted_combo = sorted(normalized)
    for forbidden in FORBIDDEN_KEY_COMBOS:
        if sorted(forbidden) == sorted_combo:
            return False, f"Key combination {keys} is forbidden for security reasons"

    # If it's a multi-key combo with modifiers, check it's in allowed combos
    modifiers = {"ctrl", "shift", "alt", "win"}
    has_modifier = any(k in modifiers for k in normalized)
    if has_modifier and len(normalized) > 1:
        is_allowed = False
        for allowed in ALLOWED_KEY_COMBOS:
            if sorted(allowed) == sorted_combo:
                is_allowed = True
                break
        if not is_allowed:
            return False, f"Key combination {keys} is not in the allowed combinations list"

    return True, "Key combination is valid"


def validate_path(path: str) -> tuple[bool, str]:
    """Validate a file path is not in a protected system directory.

    Blocks UNC paths (network shares) and Win32 device paths.

    Args:
        path: File path to validate.

    Returns:
        Tuple of (is_valid, message).
    """
    if not path or not path.strip():
        return False, "Empty path"

    # Block UNC paths (\\server\share), Win32 device paths (\\.\device),
    # and single-backslash-leading paths (could be UNC degraded by
    # backslash normalization in exec_command).
    if path.startswith("\\") or path.startswith("//"):
        return False, f"UNC and device paths are not allowed: {path}"

    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError) as e:
        return False, f"Invalid path: {e}"

    normalized = str(resolved).lower().replace("\\", "/")

    for sys_dir in SYSTEM_DIRS:
        if normalized == sys_dir or normalized.startswith(sys_dir + "/"):
            return False, f"Path '{path}' is in a protected system directory"

    return True, "Path is valid"
