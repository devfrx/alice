"""AL\\CE — Shared calendar utilities.

Contains validation helpers and constants shared between the calendar
plugin and the calendar REST routes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from dateutil.rrule import rrulestr

# Maximum RRULE occurrences per event to prevent DoS.
MAX_OCCURRENCES = 500

# Allowed RRULE frequency values.
_ALLOWED_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}


def validate_rrule(rule_str: str) -> str | None:
    """Validate an RRULE string.

    Args:
        rule_str: An RFC 5545 RRULE string to validate.

    Returns:
        An error message string if the rule is invalid, or ``None``
        if the rule is valid (or empty/blank).
    """
    if not rule_str or not rule_str.strip():
        return None
    upper = rule_str.upper()
    freq_found = False
    for part in upper.replace(";", "\n").split("\n"):
        part = part.strip()
        if part.startswith("FREQ="):
            freq = part.split("=", 1)[1]
            if freq not in _ALLOWED_FREQUENCIES:
                return (
                    f"Frequency '{freq}' not allowed "
                    "(use DAILY, WEEKLY, MONTHLY, YEARLY)"
                )
            freq_found = True
    if not freq_found:
        return "RRULE must contain a FREQ= clause"
    try:
        rrulestr(rule_str, dtstart=datetime.now(timezone.utc))
    except Exception as exc:
        return f"Invalid RRULE: {exc}"
    return None
