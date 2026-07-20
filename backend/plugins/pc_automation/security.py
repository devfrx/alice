"""AL\\CE — PC Automation security framework.

Validates tool inputs (apps, keys) against whitelists.

The command-validation chain (``validate_command``, ``validate_path``,
``command_paths_within_workspace``) was removed with the retirement of
``execute_command`` (Fase 2): the scoped ``terminal.run_terminal_command``
tool is the single exec path.

The post-screenshot lockout (:class:`ScreenshotLockout`) was promoted to
:mod:`backend.core.screenshot_lockout` so a single process-wide instance
protects every dangerous tool. It is re-exported here so existing imports
(``from backend.plugins.pc_automation.security import ScreenshotLockout``)
keep working against that shared instance.
"""

from __future__ import annotations

# Re-exported from core (single source of truth, shared process-wide lockout).
from backend.core.screenshot_lockout import ScreenshotLockout  # noqa: F401
from backend.plugins.pc_automation.constants import (
    ALLOWED_APPS,
    ALLOWED_KEY_COMBOS,
    ALLOWED_KEYS,
    FORBIDDEN_KEY_COMBOS,
)


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
    primary = executable[0] if isinstance(executable, list) else executable

    return True, f"Application '{normalized}' is whitelisted", primary


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
