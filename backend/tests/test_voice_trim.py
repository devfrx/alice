"""Tests for the Fase 8 voice toolset trim (agent.voice.max_tools)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.api.routes.chat._assembly import _apply_voice_trim


def _tools(n: int) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": f"tool_{i}", "parameters": {}}}
        for i in range(n)
    ]


class _FakeRegistry:
    def limit_tools(
        self,
        tools: list[dict[str, Any]],
        *,
        max_tools: int,
        priority_plugins: list[str],
    ) -> list[dict[str, Any]]:
        return tools[:max_tools]


def _ctx(voice_cap: int) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(
            agent=SimpleNamespace(voice=SimpleNamespace(max_tools=voice_cap)),
            llm=SimpleNamespace(priority_plugins=[]),
        ),
        tool_registry=_FakeRegistry(),
    )


def test_voice_source_trims_toolset() -> None:
    trimmed = _apply_voice_trim(_ctx(3), _tools(10), source="voice")
    assert trimmed is not None
    assert len(trimmed) == 3


def test_text_source_is_untouched() -> None:
    tools = _tools(10)
    assert _apply_voice_trim(_ctx(3), tools, source="text") is tools
    assert _apply_voice_trim(_ctx(3), tools, source=None) is tools


def test_zero_cap_disables_trim() -> None:
    tools = _tools(10)
    assert _apply_voice_trim(_ctx(0), tools, source="voice") is tools


def test_small_toolset_is_untouched() -> None:
    tools = _tools(2)
    assert _apply_voice_trim(_ctx(3), tools, source="voice") is tools


def test_none_tools_pass_through() -> None:
    assert _apply_voice_trim(_ctx(3), None, source="voice") is None
