"""O.M.N.I.A. — PC Automation plugin constants.

Whitelists and configuration constants for safe PC automation.
All security-critical data is defined here for easy auditing.
"""

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

# -- Command Whitelist ----------------------------------------------------
# Only these commands can be executed. Maps command name to description.
COMMAND_WHITELIST: dict[str, str] = {
    # Informational
    "ipconfig": "Show network configuration",
    "systeminfo": "Show system information",
    "tasklist": "List running processes",
    "hostname": "Show computer name",
    "whoami": "Show current user",
    "date": "Show current date",
    "time": "Show current time",
    "dir": "List directory contents",
    "echo": "Print text",
    "type": "Display file contents",
    "ping": "Test network connectivity",
    "nslookup": "DNS lookup",
    "netstat": "Network statistics",
    "ver": "Show Windows version",
    "vol": "Show disk volume label",
    "where": "Locate executables in PATH",
    "tree": "Show directory tree structure",
    "findstr": "Search text in files",
    # File management
    "mkdir": "Create a directory",
    "md": "Create a directory (alias)",
    "copy": "Copy files",
    "move": "Move or rename files and directories",
    "rename": "Rename a file or directory",
    "ren": "Rename a file or directory (alias)",
    "rmdir": "Remove an empty directory",
    "rd": "Remove an empty directory (alias)",
    "robocopy": "Robust file copy",
}

# Commands that operate on file paths (validated against FORBIDDEN_PATHS)
FILE_MANAGEMENT_CMDS: set[str] = {
    "mkdir", "md", "copy", "move", "rename", "ren",
    "rmdir", "rd", "robocopy", "dir", "type", "tree",
}

# CMD.exe built-in commands that cannot run as standalone executables.
# These must be executed via 'cmd.exe /c <command>'.
CMD_BUILTINS: set[str] = {
    "dir", "echo", "type", "date", "time", "ver", "vol",
    "mkdir", "md", "copy", "move", "rename", "ren", "rmdir", "rd",
    "cls", "color", "title", "pushd", "popd", "cd",
}

# -- Path Security --------------------------------------------------------
# Directories that tools CANNOT target or access
FORBIDDEN_PATHS: list[str] = [
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
    r"C:\$Recycle.Bin",
    r"C:\System Volume Information",
    r"C:\Recovery",
    r"C:\Boot",
]

# System directories (normalized lowercase for comparison)
SYSTEM_DIRS: list[str] = [p.lower().replace("\\", "/") for p in FORBIDDEN_PATHS]

# -- Screenshot Settings --------------------------------------------------
MAX_SCREENSHOT_PIXELS: int = 2_000_000
"""Maximum screenshot resolution (width * height). Downscale if exceeded."""

SCREENSHOT_LOCKOUT_S: int = 60
"""Seconds to lock dangerous tools after a screenshot is taken."""

# Tools that are blocked after a screenshot (anti-exfiltration)
LOCKOUT_TOOLS: set[str] = {
    "execute_command",
}

# Per-command forbidden flags (prevent destructive operations)
FORBIDDEN_FLAGS: dict[str, set[str]] = {
    "rmdir": {"/s", "/q"},
    "rd": {"/s", "/q"},
    "robocopy": {"/mir", "/purge", "/move", "/mov"},
}

# -- Subprocess Settings --------------------------------------------------
MAX_COMMAND_OUTPUT_CHARS: int = 8000
"""Maximum characters of command output to return."""

COMMAND_TIMEOUT_S: int = 30
"""Maximum seconds a command can run before being killed."""
