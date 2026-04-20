"""Tests for the local degeneration detector used by ``CriticService``.

The detector is a pure function — these tests pin its behaviour on
explicit fixtures (paragraph repetition, ``<tool_code>`` markers,
fenced JSON tool-call literals, and ``finish_reason='length'``) so
regressions are caught without spinning up an LLM.
"""

from __future__ import annotations

import pytest

from backend.services.agent._degeneration import (
    MIN_REPEATED_PARAGRAPH_LEN,
    detect_degeneration,
)
from backend.services.agent.models import VerdictAction


# ---------------------------------------------------------------------------
# Happy path: detector stays silent on healthy outputs.
# ---------------------------------------------------------------------------


def test_no_degeneration_on_short_clean_text() -> None:
    """A short, well-formed answer must not trigger any rule."""
    assert detect_degeneration("Risposta breve e pulita.", "stop") is None


def test_no_degeneration_on_long_unique_paragraphs() -> None:
    """Multiple long paragraphs without repetition must pass."""
    content = "\n\n".join(
        [
            "Primo paragrafo lungo e dettagliato che spiega un concetto importante " * 2,
            "Secondo paragrafo completamente diverso dal primo con altre informazioni " * 2,
        ]
    )
    assert detect_degeneration(content, "stop") is None


def test_empty_content_returns_none() -> None:
    """Empty content with finish_reason=stop must not crash and return None."""
    assert detect_degeneration("", "stop") is None
    assert detect_degeneration("", None) is None


# ---------------------------------------------------------------------------
# (a) Repeated paragraph
# ---------------------------------------------------------------------------


def test_repeated_long_paragraph_triggers_replan() -> None:
    """A duplicated long paragraph must yield REPLAN."""
    paragraph = "Questo è un paragrafo abbastanza lungo per superare la soglia minima di rilevazione " * 2
    assert len(paragraph) >= MIN_REPEATED_PARAGRAPH_LEN
    content = f"{paragraph}\n\n{paragraph}"
    verdict = detect_degeneration(content, "stop")
    assert verdict is not None
    assert verdict.action == VerdictAction.REPLAN
    assert verdict.source == "detector"
    assert "ripetuto" in verdict.reason.lower()


def test_short_repeated_paragraph_is_ignored() -> None:
    """Short duplicated lines (e.g. 'OK') must NOT trigger the rule."""
    content = "OK\n\nOK\n\nOK"
    assert detect_degeneration(content, "stop") is None


def test_whitespace_normalisation_catches_repetition() -> None:
    """Whitespace differences must not hide a repetition."""
    p1 = "Paragrafo  con   spazi    multipli e abbastanza lungo per scattare la regola di duplicazione"
    p2 = "Paragrafo con spazi multipli e abbastanza lungo per scattare la regola di duplicazione"
    verdict = detect_degeneration(f"{p1}\n\n{p2}", "stop")
    assert verdict is not None
    assert verdict.action == VerdictAction.REPLAN


# ---------------------------------------------------------------------------
# (b) Inline <tool_code> markers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        "<tool_code>print('hi')</tool_code>",
        "ecco una chiamata: <tool_code> read_file('x') </tool_code>",
        "<TOOL_CODE>weird casing</TOOL_CODE>",
        "</tool_code>",
    ],
)
def test_tool_code_marker_triggers_replan(snippet: str) -> None:
    """Any ``<tool_code>`` / ``</tool_code>`` tag in the text must REPLAN."""
    verdict = detect_degeneration(f"Risposta: {snippet} fine.", "stop")
    assert verdict is not None
    assert verdict.action == VerdictAction.REPLAN
    assert verdict.source == "detector"
    assert "tool call inline" in verdict.reason.lower()


# ---------------------------------------------------------------------------
# (c) Fake JSON tool-call literal
# ---------------------------------------------------------------------------


def test_fenced_json_tool_call_triggers_replan() -> None:
    """A fenced block that looks like a tool-call JSON literal must REPLAN."""
    content = (
        "Vorrei eseguire questo:\n"
        "```json\n"
        '{"name": "web_search", "arguments": {"q": "ai"}}\n'
        "```\n"
    )
    verdict = detect_degeneration(content, "stop")
    assert verdict is not None
    assert verdict.action == VerdictAction.REPLAN
    assert verdict.source == "detector"


def test_fenced_tool_code_block_triggers_replan() -> None:
    """A ```tool_code fenced block must trigger as well."""
    content = (
        "```tool_code\n"
        '{"name": "read_file", "arguments": {"path": "/x"}}\n'
        "```"
    )
    verdict = detect_degeneration(content, "stop")
    assert verdict is not None
    assert verdict.action == VerdictAction.REPLAN


def test_plain_json_object_without_fence_is_ignored() -> None:
    """A regular JSON-looking sentence without code fence must not trigger."""
    content = 'La configurazione contiene name: "value" come campo.'
    assert detect_degeneration(content, "stop") is None


# ---------------------------------------------------------------------------
# (d) finish_reason == "length"
# ---------------------------------------------------------------------------


def test_finish_reason_length_always_triggers_replan() -> None:
    """Truncated output must REPLAN regardless of content."""
    verdict = detect_degeneration("qualunque testo", "length")
    assert verdict is not None
    assert verdict.action == VerdictAction.REPLAN
    assert verdict.source == "detector"
    assert "troncato" in verdict.reason.lower()


def test_finish_reason_length_takes_priority_over_content() -> None:
    """Even an otherwise clean response must REPLAN if truncated."""
    verdict = detect_degeneration("Risposta pulita e breve.", "length")
    assert verdict is not None
    assert verdict.action == VerdictAction.REPLAN
