"""AL\\CE — PC Automation async execution wrappers.

Each function wraps a blocking Windows automation call in
``asyncio.to_thread()`` for async safety. All validation is
performed before execution via the security module.
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
from typing import Any

from loguru import logger

from backend.plugins.pc_automation.constants import (
    ALLOWED_APPS,
    CMD_BUILTINS,
    MAX_SCREENSHOT_PIXELS,
)
from backend.plugins.pc_automation.security import (
    ScreenshotLockout,
    validate_app_name,
    validate_command,
    validate_keys,
)
from backend.plugins.pc_automation.validators import (
    safe_subprocess,
    sanitize_text_input,
)

# -- Lazy imports for optional dependencies --------------------------------

try:
    import pyautogui
    pyautogui.FAILSAFE = True  # Move mouse to corner to abort
    pyautogui.PAUSE = 0.1  # Small delay between actions
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    pyautogui = None  # type: ignore[assignment]
    _PYAUTOGUI_AVAILABLE = False

try:
    import pyperclip
    _PYPERCLIP_AVAILABLE = True
except ImportError:
    pyperclip = None  # type: ignore[assignment]
    _PYPERCLIP_AVAILABLE = False

try:
    import pywinauto
    _PYWINAUTO_AVAILABLE = True
except ImportError:
    pywinauto = None  # type: ignore[assignment]
    _PYWINAUTO_AVAILABLE = False

# Shared lockout instance (one per plugin lifecycle)
_lockout = ScreenshotLockout()


def get_lockout() -> ScreenshotLockout:
    """Return the shared screenshot lockout instance."""
    return _lockout


def check_dependencies() -> list[str]:
    """Return list of missing optional dependencies."""
    missing: list[str] = []
    if not _PYAUTOGUI_AVAILABLE:
        missing.append("pyautogui")
    if not _PYWINAUTO_AVAILABLE:
        missing.append("pywinauto")
    return missing


# ---------------------------------------------------------------------------
# Command normalisation helpers
# ---------------------------------------------------------------------------

_RE_MULTI_BACKSLASH = re.compile(r"\\{2,}")


def _normalize_backslashes(command: str) -> str:
    """Collapse doubled backslashes produced by LLM JSON encoding.

    ``"C:\\\\Users\\\\Jays"`` → ``"C:\\Users\\Jays"``.
    UNC paths (``\\\\server\\share``) are preserved as ``\\server\\share``
    because the regex collapses *any* run of 2+ backslashes into one.
    """
    return _RE_MULTI_BACKSLASH.sub("\\\\", command)


def _tokenize_command(command: str) -> list[str]:
    """Tokenise a Windows command string respecting double-quoted paths.

    Backslash is NOT treated as an escape character (Windows semantics).
    Surrounding double quotes are stripped from each token.  Trailing
    backslashes are stripped **only from tokens that were originally
    quoted** to work around the cmd.exe ``\\"`` trailing-backslash
    bug where a quoted destination path ends with a backslash, e.g.::

        move "C:\\src\\a.jpg" "C:\\dest\\"

    Unquoted tokens like ``C:\\`` are preserved so that root drive
    references keep their trailing backslash.

    Args:
        command: The raw command string (e.g. from the LLM).

    Returns:
        List of string tokens with quotes removed and trailing backslashes
        stripped from quoted multi-character tokens.
    """
    tokens: list[str] = []
    current: list[str] = []
    in_quotes = False
    was_quoted = False

    for ch in command:
        if ch == '"':
            in_quotes = not in_quotes
            was_quoted = True
        elif ch == ' ' and not in_quotes:
            if current:
                token = "".join(current)
                if was_quoted and len(token) > 1:
                    token = token.rstrip("\\")
                tokens.append(token)
                current = []
                was_quoted = False
        else:
            current.append(ch)

    if current:
        token = "".join(current)
        if was_quoted and len(token) > 1:
            token = token.rstrip("\\")
        tokens.append(token)

    return tokens


def _find_executable(candidates: list[str]) -> str | None:
    """Resolve an executable from a list of candidate names.

    Search order:
    1. URI protocols (e.g. ``ms-settings:``) — returned as-is.
    2. ``shutil.which`` (system PATH).
    3. Windows App Paths registry.
    4. Common install directories (Program Files, LocalAppData\\Programs) up to
       2 directory levels deep.

    Args:
        candidates: Ordered list of executable names to try.

    Returns:
        Resolved path/URI string, or ``None`` if nothing was found.
    """
    import os
    import shutil

    for name in candidates:
        # URI protocols are handled by os.startfile — no path resolution needed
        if ":" in name and not name.endswith(".exe"):
            return name

        # 1. PATH lookup
        found = shutil.which(name)
        if found:
            return found

        # 2. Windows App Paths registry
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}"
                    with winreg.OpenKey(hive, key_path) as key:
                        val, _ = winreg.QueryValueEx(key, "")
                        if val and os.path.isfile(val):
                            return val
                except OSError:
                    continue
        except ImportError:
            pass

        # 3. Shallow scan of common install directories (2 levels deep)
        bases = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        ]
        name_lower = name.lower()
        for base in bases:
            if not base or not os.path.isdir(base):
                continue
            try:
                for entry in os.scandir(base):
                    if not entry.is_dir():
                        continue
                    candidate = os.path.join(entry.path, name)
                    if os.path.isfile(candidate):
                        return candidate
                    # One sub-level deeper
                    try:
                        for sub in os.scandir(entry.path):
                            if sub.is_dir():
                                candidate = os.path.join(sub.path, name)
                                if os.path.isfile(candidate):
                                    return candidate
                    except (OSError, PermissionError):
                        pass
            except (OSError, PermissionError):
                pass

    return None


async def exec_open_app(app_name: str) -> str:
    """Open an application by name (must be in whitelist).

    Validates against ALLOWED_APPS whitelist, resolves the executable via
    PATH / registry / common install directories, then launches it.
    URI-style entries (e.g. ``ms-settings:``) are opened via ``os.startfile``.
    """
    valid, msg, primary_exe = validate_app_name(app_name)
    if not valid:
        raise ValueError(msg)

    # Build the full candidate list for _find_executable so all alternates
    # (e.g. chrome.exe / Chrome.exe) are tried.
    _raw = ALLOWED_APPS.get(app_name.strip().lower().replace(" ", "_"))
    candidates: list[str] = _raw if isinstance(_raw, list) else ([primary_exe] if primary_exe else [])

    def _open() -> str:
        import os
        import subprocess

        resolved = _find_executable(candidates)
        if resolved is None:
            tried = ", ".join(candidates)
            raise FileNotFoundError(
                f"Could not find '{app_name}' on this system. Tried: {tried}"
            )

        # URI protocols (e.g. ms-settings:) must be launched via ShellExecute
        if ":" in resolved and not resolved.endswith(".exe"):
            os.startfile(resolved)
        else:
            try:
                subprocess.Popen(
                    [resolved],
                    shell=False,
                    close_fds=True,
                )
            except OSError as exc:
                # WinError 740: app requires elevation — re-launch via ShellExecuteEx
                # which triggers UAC prompt and runs the process as administrator.
                if getattr(exc, "winerror", None) == 740:
                    import ctypes
                    ctypes.windll.shell32.ShellExecuteW(
                        None, "runas", resolved, None, None, 1,
                    )
                else:
                    raise
        return f"Application '{app_name}' opened ({resolved})"

    return await asyncio.to_thread(_open)


async def exec_close_app(app_name: str) -> str:
    """Close an application by name.

    Uses taskkill to terminate the process gracefully.
    URI-based apps (e.g. ms-settings:) cannot be closed via taskkill.
    """
    valid, msg, primary_exe = validate_app_name(app_name)
    if not valid:
        raise ValueError(msg)

    # taskkill needs just the base exe name
    executable = primary_exe or app_name

    # URI protocols (e.g. ms-settings:) cannot be closed via taskkill
    if ":" in executable and not executable.endswith(".exe"):
        raise ValueError(
            f"Application '{app_name}' was opened via URI protocol "
            f"and cannot be closed programmatically"
        )

    try:
        output = await safe_subprocess("taskkill", ["/IM", executable, "/F"], timeout=10)
        return f"Closed '{app_name}': {output}"
    except Exception as e:
        raise RuntimeError(f"Failed to close '{app_name}': {e}")


async def exec_type_text(text: str) -> str:
    """Type text via clipboard paste (Ctrl+V).

    Uses clipboard instead of ``pyautogui.write()`` because:
    - ``write()`` drops non-ASCII / accented characters on Windows
    - ``write()`` types character-by-character (~0.02 s each) causing
      timeouts on long strings
    - On timeout the thread keeps typing uncontrollably

    Clipboard paste is instant, Unicode-safe and cancellation-safe.
    The original clipboard content is saved and restored afterward.
    """
    sanitized = sanitize_text_input(text)

    if not _PYAUTOGUI_AVAILABLE:
        raise RuntimeError("pyautogui is not installed")
    if not _PYPERCLIP_AVAILABLE:
        raise RuntimeError("pyperclip is not installed")

    def _type() -> str:
        import time as _time

        # Save current clipboard text (best-effort)
        try:
            old_clip = pyperclip.paste()
        except Exception:
            old_clip = None

        try:
            pyperclip.copy(sanitized)
            pyautogui.hotkey("ctrl", "v")
            # Small pause to let the target app process the paste
            _time.sleep(0.15)
        finally:
            # Restore previous clipboard content
            if old_clip is not None:
                try:
                    pyperclip.copy(old_clip)
                except Exception:
                    pass

        return f"Typed {len(sanitized)} characters"

    return await asyncio.to_thread(_type)


async def exec_press_keys(keys: list[str]) -> str:
    """Press a key combination using pyautogui."""
    if not keys:
        raise ValueError("keys list must not be empty")
    valid, msg = validate_keys(keys)
    if not valid:
        raise ValueError(msg)

    if not _PYAUTOGUI_AVAILABLE:
        raise RuntimeError("pyautogui is not installed")

    def _press() -> str:
        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        return f"Pressed keys: {' + '.join(keys)}"

    return await asyncio.to_thread(_press)


async def exec_take_screenshot() -> bytes:
    """Take a screenshot, downscale if > 2MP, return PNG bytes.

    Records the screenshot in the lockout manager to block
    dangerous tools for SCREENSHOT_LOCKOUT_S seconds.
    """
    if not _PYAUTOGUI_AVAILABLE:
        raise RuntimeError("pyautogui is not installed")

    def _screenshot() -> bytes:
        img = pyautogui.screenshot()
        # Record lockout IMMEDIATELY after capture (before any processing)
        # to prevent TOCTOU race with concurrent tool calls.
        _lockout.record_screenshot()

        # Downscale if > MAX_SCREENSHOT_PIXELS
        w, h = img.size
        pixels = w * h
        if pixels > MAX_SCREENSHOT_PIXELS:
            scale = (MAX_SCREENSHOT_PIXELS / pixels) ** 0.5
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = img.resize((new_w, new_h))
            logger.info(
                "Screenshot downscaled: {}x{} -> {}x{}",
                w, h, new_w, new_h,
            )

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    return await asyncio.to_thread(_screenshot)


async def exec_get_active_window() -> str:
    """Get the title of the currently active window.

    Uses ``pyautogui.getActiveWindow()`` when available, falling back
    to the Win32 API via ``ctypes``.
    """
    def _get_window() -> str:
        if _PYAUTOGUI_AVAILABLE:
            window = pyautogui.getActiveWindow()
            if window is None:
                return "(no active window)"
            return window.title or "(no title)"

        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                return buf.value or "(no title)"
            return "(no active window)"
        except Exception:
            return "(could not detect active window)"

    return await asyncio.to_thread(_get_window)


async def exec_get_running_apps() -> list[dict[str, str]]:
    """Get list of running applications with visible windows.

    Uses ``tasklist /FO CSV /NH /V`` whose columns are:
    Image Name, PID, Session Name, Session#, Mem Usage,
    Status, User Name, CPU Time, Window Title.

    Returns only processes whose window title is non-empty/non-"N/A",
    deduplicated by name, limited to 50 entries.

    Returns:
        List of application dicts with name, pid and window_title.
    """
    output = await safe_subprocess("tasklist", ["/FO", "CSV", "/NH", "/V"], timeout=15)

    apps: list[dict[str, str]] = []
    seen_names: set[str] = set()
    reader = csv.reader(io.StringIO(output))
    for row in reader:
        if len(row) < 9:
            continue
        name = row[0].strip()
        pid = row[1].strip()
        window_title = row[8].strip()
        if not name or name.startswith("System"):
            continue
        if not window_title or window_title == "N/A":
            continue
        if name in seen_names:
            continue
        seen_names.add(name)
        apps.append({"name": name, "pid": pid, "window_title": window_title})
        if len(apps) >= 50:
            break

    return apps


async def exec_command(command: str) -> str:
    """Execute a whitelisted command safely.

    Checks the screenshot lockout before execution.
    """
    if _lockout.is_locked("execute_command"):
        remaining = _lockout.get_remaining_s()
        raise RuntimeError(
            f"Command execution is locked for {remaining:.0f}s "
            "due to recent screenshot (anti-exfiltration protection)"
        )

    # LLMs often JSON-encode backslashes in Windows paths, producing
    # doubled backslashes (e.g. "C:\\\\Users\\\\..." → "C:\\Users\\...").
    # Collapse them so cmd.exe receives valid paths.
    command = _normalize_backslashes(command)

    valid, msg = validate_command(command)
    if not valid:
        raise ValueError(msg)

    tokens = _tokenize_command(command)
    base_cmd = tokens[0].lower()
    if base_cmd.endswith(".exe"):
        base_cmd = base_cmd[:-4]

    if base_cmd in CMD_BUILTINS:
        # CMD built-in commands must run through cmd.exe /c.
        # Pass tokens as a proper argument list so subprocess does not
        # re-quote already-stripped paths.
        return await safe_subprocess("cmd.exe", ["/c"] + tokens)

    # External executables: split into command + args
    return await safe_subprocess(tokens[0], tokens[1:])


async def exec_move_mouse(x: int, y: int) -> str:
    """Move mouse cursor to absolute position."""
    if not _PYAUTOGUI_AVAILABLE:
        raise RuntimeError("pyautogui is not installed")

    def _move() -> str:
        screen_w, screen_h = pyautogui.size()
        if not (0 <= x <= screen_w and 0 <= y <= screen_h):
            raise ValueError(
                f"Coordinates ({x}, {y}) out of screen bounds "
                f"({screen_w}x{screen_h})"
            )
        pyautogui.moveTo(x, y, duration=0.3)
        return f"Mouse moved to ({x}, {y})"

    return await asyncio.to_thread(_move)


async def exec_click(x: int, y: int, button: str = "left") -> str:
    """Click at absolute screen position."""
    if button not in ("left", "right", "middle"):
        raise ValueError(f"Invalid button '{button}', must be left/right/middle")

    if not _PYAUTOGUI_AVAILABLE:
        raise RuntimeError("pyautogui is not installed")

    def _click() -> str:
        screen_w, screen_h = pyautogui.size()
        if not (0 <= x <= screen_w and 0 <= y <= screen_h):
            raise ValueError(
                f"Coordinates ({x}, {y}) out of screen bounds "
                f"({screen_w}x{screen_h})"
            )
        pyautogui.click(x, y, button=button)
        return f"Clicked {button} at ({x}, {y})"

    return await asyncio.to_thread(_click)
