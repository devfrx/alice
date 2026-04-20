"""Local rule-based degeneration detector.

The detector inspects a step's textual output (and the optional
``finish_reason`` reported by the LLM) for *objective* signs of model
collapse — repeated paragraphs, inline ``<tool_code>`` markers, fake
JSON tool calls embedded in prose, or a truncated response.  When any
of these triggers fires the function returns a :class:`Verdict` with
``action=REPLAN`` so the orchestrator can recover *without* burning a
critic LLM call.

The detector is deliberately conservative: only patterns that the
backend can NEVER produce on the happy path are flagged, so false
positives stay close to zero.

Attributes
----------
``MIN_REPEATED_PARAGRAPH_LEN``
    Minimum length (after whitespace normalisation) for a paragraph to
    count as a repetition trigger.  Short lines like ``"OK"`` are
    ignored.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

from .models import Verdict, VerdictAction

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

MIN_REPEATED_PARAGRAPH_LEN: Final[int] = 80
"""Minimum paragraph length (after normalisation) to count as duplicate."""

_PARAGRAPH_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")
"""Splits content into paragraphs on blank lines."""

_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
"""Collapses any run of whitespace into a single space."""

_TOOL_CODE_TAG_RE: Final[re.Pattern[str]] = re.compile(
    r"<\s*/?\s*tool_code\b", re.IGNORECASE,
)
"""Matches ``<tool_code>`` / ``</tool_code>`` tags emitted as plain text."""

_INLINE_JSON_TOOL_CALL_RE: Final[re.Pattern[str]] = re.compile(
    r"```(?:json|tool_code)?\s*\n\s*\{[^}]*\"name\"\s*:\s*\"[a-z_][a-z0-9_]*\"",
    re.IGNORECASE,
)
"""Matches a fenced JSON block that *looks* like a tool call literal."""

_FINISH_REASON_LENGTH: Final[str] = "length"


def _normalise(paragraph: str) -> str:
    """Collapse whitespace inside ``paragraph`` for comparison purposes."""
    return _WS_RE.sub(" ", paragraph).strip()


def _has_repeated_paragraph(content: str) -> str | None:
    """Return the offending paragraph when one is duplicated, else ``None``.

    A paragraph counts as a duplication trigger only when its
    normalised form is at least :data:`MIN_REPEATED_PARAGRAPH_LEN`
    characters long *and* it appears two or more times.
    """
    if not content:
        return None
    paragraphs = (
        _normalise(p) for p in _PARAGRAPH_SPLIT_RE.split(content) if p.strip()
    )
    counts = Counter(p for p in paragraphs if len(p) >= MIN_REPEATED_PARAGRAPH_LEN)
    for paragraph, count in counts.items():
        if count >= 2:
            return paragraph
    return None


def detect_degeneration(
    content: str,
    finish_reason: str | None,
) -> Verdict | None:
    """Return a ``REPLAN`` verdict when ``content`` shows degeneration.

    Args:
        content: The plain-text assistant output to inspect.
        finish_reason: The ``finish_reason`` reported by the underlying
            LLM call (``"stop"``, ``"length"``, ``"tool_calls"`` …).
            Pass ``None`` when unknown.

    Returns:
        A :class:`Verdict` with ``action=REPLAN`` and a short
        diagnostic ``reason`` when a degeneration pattern is detected.
        ``None`` otherwise — the caller should then proceed with the
        regular LLM-driven critic call.
    """
    # --- (d) truncated output --------------------------------------------
    if finish_reason == _FINISH_REASON_LENGTH:
        return Verdict(
            action=VerdictAction.REPLAN,
            reason="output troncato per cap di token (finish_reason=length)",
            source="detector",
        )

    if not content:
        return None

    # --- (b) inline <tool_code> markers ----------------------------------
    if _TOOL_CODE_TAG_RE.search(content):
        return Verdict(
            action=VerdictAction.REPLAN,
            reason=(
                "il modello ha tentato tool call inline non eseguibili "
                "(tag <tool_code> nel testo)"
            ),
            source="detector",
        )

    # --- (c) fake JSON tool call literal ---------------------------------
    if _INLINE_JSON_TOOL_CALL_RE.search(content):
        return Verdict(
            action=VerdictAction.REPLAN,
            reason=(
                "il modello ha emesso un blocco JSON tool-call testuale "
                "anziché una vera function call strutturata"
            ),
            source="detector",
        )

    # --- (a) repeated paragraph ------------------------------------------
    duplicate = _has_repeated_paragraph(content)
    if duplicate is not None:
        snippet = duplicate[:60].rstrip() + ("…" if len(duplicate) > 60 else "")
        return Verdict(
            action=VerdictAction.REPLAN,
            reason=f"paragrafo ripetuto rilevato (\"{snippet}\")",
            source="detector",
        )

    return None


__all__ = ["detect_degeneration", "MIN_REPEATED_PARAGRAPH_LEN"]
