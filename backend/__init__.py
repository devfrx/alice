"""AL\\CE backend package.

This module is intentionally tiny but **must** apply one workaround before any
sub-module is imported, so it cannot be left empty.

Python 3.14 + Windows WMI hang
------------------------------
On Python 3.14, ``platform.machine()`` was reimplemented to delegate to
``platform.uname()``, which on Windows now calls ``platform.win32_ver()`` →
``platform._wmi_query()``.  When the local WMI service is slow or stuck (a
common Windows issue), that query can hang for minutes or forever, freezing
*any* import of SQLAlchemy — its ``util.compat`` module evaluates
``"aarch" in platform.machine().lower()`` at import time.

Symptom: ``python -m backend`` reaches uvicorn's "Started reloader process"
log line and then never produces "Started server process" / "Application
startup complete", because the worker child is blocked inside
``import sqlalchemy``.

Workaround: pre-populate ``platform._uname_cache`` with values sourced from
environment variables and ``sys.getwindowsversion()`` (both instantaneous
and WMI-free).  Subsequent calls to ``platform.uname()`` /
``platform.machine()`` / ``platform.win32_ver()`` short-circuit on the cache
instead of issuing the WMI query.

This is safe and idempotent on Python <= 3.13 (the cache attribute exists
there too and behaves identically).
"""

from __future__ import annotations

import os
import platform
import sys


def _prime_platform_cache_windows() -> None:
    """Populate ``platform._uname_cache`` to bypass the Windows WMI query.

    Returns silently on non-Windows platforms or if anything unexpected
    happens — this is a best-effort speed-up, never a hard requirement.
    """
    if not sys.platform.startswith("win"):
        return

    # Skip if a cache already exists (some other code primed it first).
    if getattr(platform, "_uname_cache", None) is not None:
        return

    # Use COMPUTERNAME env var (always set by Windows) — calling
    # ``platform.node()`` here would itself route through ``uname()`` →
    # ``win32_ver()`` → WMI on Python 3.14 and re-trigger the hang we are
    # trying to prevent.
    node = os.environ.get("COMPUTERNAME", "")

    # sys.getwindowsversion() is a fast Win32 call, never touches WMI.
    try:
        wv = sys.getwindowsversion()
        release = f"{wv.major}"
        version = f"{wv.major}.{wv.minor}.{wv.build}"
    except Exception:
        release = ""
        version = ""

    machine = (
        os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
        or "AMD64"
    )
    processor = os.environ.get("PROCESSOR_IDENTIFIER", "")

    try:
        platform._uname_cache = platform.uname_result(  # type: ignore[attr-defined]
            system="Windows",
            node=node,
            release=release,
            version=version,
            machine=machine,
            processor=processor,
        )
    except TypeError:
        # Older signature (no ``processor`` keyword) — fall back gracefully.
        try:
            platform._uname_cache = platform.uname_result(  # type: ignore[attr-defined]
                system="Windows",
                node=node,
                release=release,
                version=version,
                machine=machine,
            )
        except Exception:
            return
    except Exception:
        return

    # Also stub win32_ver() in case any caller invokes it directly.
    def _fast_win32_ver(_release: str = release, _version: str = version) -> tuple:
        return (_release, _version, "", "")

    platform.win32_ver = _fast_win32_ver  # type: ignore[assignment]


_prime_platform_cache_windows()

