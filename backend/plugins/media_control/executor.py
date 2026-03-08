"""O.M.N.I.A. — Media Control async execution wrappers.

Each function wraps a blocking Windows API call (COM / win32) in
``asyncio.to_thread()`` for async safety.  COM interfaces are cached
and re-initialised when the audio device is disconnected.

Windows-only — raises ``RuntimeError`` on other platforms.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Platform & optional dependency detection
# ---------------------------------------------------------------------------

_IS_WINDOWS: bool = sys.platform == "win32"

_PYCAW_AVAILABLE: bool = False
_WIN32_AVAILABLE: bool = False

if _IS_WINDOWS:
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from comtypes import CLSCTX_ALL

        _PYCAW_AVAILABLE = True
    except ImportError:
        pass

    try:
        import win32api
        import win32con

        _WIN32_AVAILABLE = True
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Dependency checks
# ---------------------------------------------------------------------------


def check_platform() -> None:
    """Raise if not running on Windows.

    Raises:
        RuntimeError: When the platform is not Windows.
    """
    if not _IS_WINDOWS:
        raise RuntimeError("Media control is Windows-only")


def check_dependencies() -> list[str]:
    """Return a list of missing optional dependency names.

    Returns:
        List of missing package names (empty when everything is installed).
    """
    missing: list[str] = []
    if not _PYCAW_AVAILABLE:
        missing.append("pycaw")
    if not _WIN32_AVAILABLE:
        missing.append("pywin32")
    return missing


# ---------------------------------------------------------------------------
# COM volume interface (cached, auto-reinit on disconnect)
# ---------------------------------------------------------------------------

_volume_interface: Any | None = None
_volume_lock = threading.Lock()


def _get_volume_interface() -> Any:
    """Return a cached ``IAudioEndpointVolume`` COM interface.

    Re-initialises when the cached device has been disconnected.
    Thread-safe: uses ``_volume_lock`` to guard initialisation.

    Returns:
        The COM volume control interface.

    Raises:
        RuntimeError: If pycaw is not available or no audio device found.
    """
    global _volume_interface  # noqa: PLW0603

    check_platform()
    if not _PYCAW_AVAILABLE:
        raise RuntimeError("pycaw is not installed — cannot control volume")

    with _volume_lock:
        if _volume_interface is not None:
            try:
                # Probe the interface to check it's still valid
                _volume_interface.GetMasterVolumeLevelScalar()
                return _volume_interface
            except Exception:
                logger.debug("Audio device disconnected — reinitialising COM")
                _volume_interface = None

        devices = AudioUtilities.GetSpeakers()
        if devices is None:
            raise RuntimeError("No audio output device found")

        # GetSpeakers() may return an AudioDevice wrapper — get the raw IMMDevice
        raw_device = getattr(devices, "_dev", devices)
        interface = raw_device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        _volume_interface = interface.QueryInterface(IAudioEndpointVolume)
        return _volume_interface


# ---------------------------------------------------------------------------
# Volume control
# ---------------------------------------------------------------------------


async def exec_get_volume() -> int:
    """Get the current master volume level (0–100).

    Returns:
        Integer volume percentage.
    """
    def _get() -> int:
        vol = _get_volume_interface()
        scalar = vol.GetMasterVolumeLevelScalar()  # 0.0 – 1.0
        return round(scalar * 100)

    return await asyncio.to_thread(_get)


async def exec_set_volume(level: int) -> str:
    """Set the master volume to *level* (0–100).

    Args:
        level: Target volume percentage, clamped to 0–100.

    Returns:
        Confirmation message with the new level.

    Raises:
        ValueError: If *level* is not in the 0–100 range.
    """
    level = int(level)
    if not 0 <= level <= 100:
        raise ValueError(f"Volume level must be 0–100, got {level}")

    def _set() -> str:
        vol = _get_volume_interface()
        vol.SetMasterVolumeLevelScalar(float(level) / 100.0, None)
        return f"Volume set to {level}%"

    return await asyncio.to_thread(_set)


async def exec_mute() -> str:
    """Mute the master audio output.

    Returns:
        Confirmation message.
    """
    def _mute() -> str:
        vol = _get_volume_interface()
        vol.SetMute(True, None)
        return "Audio muted"

    return await asyncio.to_thread(_mute)


async def exec_unmute() -> str:
    """Unmute the master audio output.

    Returns:
        Confirmation message.
    """
    def _unmute() -> str:
        vol = _get_volume_interface()
        vol.SetMute(False, None)
        return "Audio unmuted"

    return await asyncio.to_thread(_unmute)


# ---------------------------------------------------------------------------
# Media playback (virtual key events)
# ---------------------------------------------------------------------------


def _send_media_key(vk_code: int, key_name: str) -> str:
    """Send a media virtual-key press/release event.

    Args:
        vk_code: Win32 virtual key code (e.g. ``0xB3``).
        key_name: Human-readable name for the log message.

    Returns:
        Confirmation message.

    Raises:
        RuntimeError: If pywin32 is not installed or not on Windows.
    """
    check_platform()
    if not _WIN32_AVAILABLE:
        raise RuntimeError("pywin32 is not installed — cannot send media keys")

    win32api.keybd_event(vk_code, 0, 0, 0)
    win32api.keybd_event(vk_code, 0, win32con.KEYEVENTF_KEYUP, 0)
    return f"Media key sent: {key_name}"


async def exec_media_play_pause() -> str:
    """Send media play/pause key event.

    Returns:
        Confirmation message.
    """
    return await asyncio.to_thread(_send_media_key, 0xB3, "play/pause")


async def exec_media_next() -> str:
    """Send media next-track key event.

    Returns:
        Confirmation message.
    """
    return await asyncio.to_thread(_send_media_key, 0xB0, "next track")


async def exec_media_prev() -> str:
    """Send media previous-track key event.

    Returns:
        Confirmation message.
    """
    return await asyncio.to_thread(_send_media_key, 0xB1, "previous track")


# ---------------------------------------------------------------------------
# Display brightness (WMI via PowerShell subprocess)
# ---------------------------------------------------------------------------


async def exec_set_brightness(level: int) -> str:
    """Set the display brightness to *level* (0–100).

    Uses WMI through a PowerShell subprocess because the
    ``WmiMonitorBrightnessMethods`` class is the most reliable
    approach on Windows laptops.

    Args:
        level: Target brightness percentage (0–100).

    Returns:
        Confirmation message.

    Raises:
        ValueError: If *level* is not in the 0–100 range.
        RuntimeError: If the monitor doesn't support WMI brightness or
            the platform is not Windows.
    """
    check_platform()

    level = int(level)
    if not 0 <= level <= 100:
        raise ValueError(f"Brightness level must be 0–100, got {level}")

    ps_script = (
        "(Get-WmiObject -Namespace root/WMI "
        "-Class WmiMonitorBrightnessMethods)"
        f".WmiSetBrightness(1, {level})"
    )

    def _set() -> str:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not supported" in stderr.lower() or "not found" in stderr.lower():
                raise RuntimeError(
                    "Monitor does not support brightness control via WMI. "
                    "This typically works only on laptop displays."
                )
            raise RuntimeError(f"Brightness command failed: {stderr[:200]}")
        return f"Brightness set to {level}%"

    return await asyncio.to_thread(_set)
