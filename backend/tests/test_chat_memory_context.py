"""Unit tests for _format_memory_context (Fase 4: KnowledgeHit-based)."""

from __future__ import annotations

from backend.api.routes.chat._helpers import _format_memory_context
from backend.services.knowledge import KnowledgeDoc, KnowledgeHit


def _hit(content: str, category: str | None = None) -> KnowledgeHit:
    return KnowledgeHit(
        doc=KnowledgeDoc(
            id="00000000-0000-0000-0000-000000000001",
            kind="memory",
            content=content,
            metadata={"category": category, "scope": "long_term"},
        ),
        score=0.9,
    )


def test_formats_hits_with_category() -> None:
    out = _format_memory_context([_hit("likes dark mode", "preference")], 1000)
    assert "[RELEVANT MEMORIES]" in out
    assert "- [preference] likes dark mode" in out


def test_category_fallback_general() -> None:
    out = _format_memory_context([_hit("a fact", None)], 1000)
    assert "- [general] a fact" in out


def test_truncates_at_max_chars() -> None:
    hits = [_hit("x" * 50, "a"), _hit("y" * 50, "b")]
    out = _format_memory_context(hits, 60)
    assert "x" * 50 in out
    assert "y" * 50 not in out


def test_line_exactly_at_max_chars_is_included() -> None:
    # "- [a] " + 50 chars = 56; the budget check is strict (>), so a line
    # that lands exactly on max_chars must still be included.
    out = _format_memory_context([_hit("x" * 50, "a")], 56)
    assert "x" * 50 in out
