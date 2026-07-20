"""AL\\CE — PC Automation plugin constants.

Whitelists and configuration constants for safe PC automation.
All security-critical data is defined here for easy auditing.
"""

# The post-screenshot lockout policy lives in core (single source of truth,
# shared process-wide instance). Re-exported so existing readers of
# ``constants.SCREENSHOT_LOCKOUT_S`` / ``constants.LOCKOUT_TOOLS`` resolve to it.
from backend.core.screenshot_lockout import (  # noqa: F401
    LOCKOUT_TOOLS,
    SCREENSHOT_LOCKOUT_S,
)

# -- Application Whitelist ------------------------------------------------
# Maps friendly app names to executable names/paths.
# Only these applications can be opened/closed by the plugin.
ALLOWED_APPS: dict[str, str | list[str]] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "wordpad": "wordpad.exe",
    "task_manager": "taskmgr.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "cmd": "cmd.exe",
    "snipping_tool": "SnippingTool.exe",
    "notepad_plus": ["notepad++.exe", "notepad++"],
    "vscode": ["code.exe", "Code.exe"],
    "chrome": ["chrome.exe", "Chrome.exe"],
    "firefox": ["firefox.exe", "Firefox.exe"],
    "edge": ["msedge.exe", "MsEdge.exe"],
    "spotify": "Spotify.exe",
    "vlc": "vlc.exe",
    "vivaldi": ["vivaldi.exe", "Vivaldi.exe"],
    "discord": ["Discord.exe", "discord.exe"],
    "lmstudio": ["LM Studio.exe", "lmstudio.exe"],
    "notion": ["Notion.exe", "notion.exe"],
    "hwinfo": ["HWiNFO64.exe"],
    "steam": ["steam.exe", "Steam.exe"],
    "impostazioni": "ms-settings:",
}

# -- Key Whitelist --------------------------------------------------------
# Individual keys that are safe to press
ALLOWED_KEYS: set[str] = {
    # Letters, digits
    *"abcdefghijklmnopqrstuvwxyz",
    *"0123456789",
    # Function keys
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    # Navigation
    "enter", "return", "tab", "space", "backspace", "delete", "escape", "esc",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    # Modifiers (allowed as part of combos)
    "ctrl", "shift", "alt", "win",
    # Punctuation
    ".", ",", ";", ":", "'", '"', "/", "\\", "-", "=", "[", "]", "`",
    # Media
    "volumeup", "volumedown", "volumemute", "playpause",
    "printscreen", "insert", "pause",
}

# Key combinations that are explicitly FORBIDDEN (dangerous)
FORBIDDEN_KEY_COMBOS: list[list[str]] = [
    ["ctrl", "alt", "delete"],  # Security attention sequence
    ["alt", "f4"],              # Close window (could kill important apps)
    ["win", "r"],               # Run dialog (arbitrary command execution)
    ["win", "l"],               # Lock workstation
    ["ctrl", "shift", "escape"],# Task manager shortcut
    ["alt", "tab"],             # Switch window (could expose sensitive content)
    ["win", "d"],               # Show desktop
    ["win", "e"],               # Open Explorer
]

# Key combinations that are explicitly ALLOWED (safe shortcuts)
ALLOWED_KEY_COMBOS: list[list[str]] = [
    ["ctrl", "c"],       # Copy
    ["ctrl", "v"],       # Paste
    ["ctrl", "x"],       # Cut
    ["ctrl", "z"],       # Undo
    ["ctrl", "y"],       # Redo
    ["ctrl", "a"],       # Select all
    ["ctrl", "s"],       # Save
    ["ctrl", "shift", "s"],  # Save as
    ["ctrl", "p"],       # Print
    ["ctrl", "f"],       # Find
    ["ctrl", "h"],       # Replace
    ["ctrl", "n"],       # New
    ["ctrl", "o"],       # Open
    ["ctrl", "w"],       # Close tab
    ["ctrl", "t"],       # New tab
    ["ctrl", "shift", "t"],  # Reopen tab
    ["ctrl", "tab"],     # Next tab
    ["ctrl", "shift", "tab"],  # Previous tab
]

# The command whitelist (COMMAND_WHITELIST / FILE_MANAGEMENT_CMDS /
# CMD_BUILTINS / FORBIDDEN_PATHS / FORBIDDEN_FLAGS) was removed with the
# retirement of ``execute_command`` (Fase 2): the scoped
# ``terminal.run_terminal_command`` tool is the single exec path.

# -- Screenshot Settings --------------------------------------------------
MAX_SCREENSHOT_PIXELS: int = 2_000_000
"""Maximum screenshot resolution (width * height). Downscale if exceeded."""

# SCREENSHOT_LOCKOUT_S and LOCKOUT_TOOLS were promoted to
# backend.core.screenshot_lockout (shared process-wide lockout) and are
# re-exported at the top of this module for backward compatibility.

# -- Subprocess Settings --------------------------------------------------
MAX_COMMAND_OUTPUT_CHARS: int = 8000
"""Maximum characters of command output to return."""

COMMAND_TIMEOUT_S: int = 30
"""Maximum seconds a command can run before being killed."""
