"""Unit tests for ``ClassifierService`` (Phase 2 of agent loop)."""

from __future__ import annotations

import pytest

from backend.services.agent import ClassifierConfig, ClassifierService, TaskComplexity

from ._recording_llm import RecordingLLM


@pytest.mark.asyncio
async def test_classify_returns_each_known_label() -> None:
    """Each of the four valid tokens must round-trip through the parser."""
    llm = RecordingLLM(["trivial", "open_ended", "single_tool", "multi_step"])
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=0))

    assert await svc.classify("a", has_tools=False) == TaskComplexity.TRIVIAL
    assert await svc.classify("b", has_tools=False) == TaskComplexity.OPEN_ENDED
    assert await svc.classify("c", has_tools=True) == TaskComplexity.SINGLE_TOOL
    assert await svc.classify("d", has_tools=True) == TaskComplexity.MULTI_STEP


@pytest.mark.asyncio
async def test_classify_tolerates_noisy_output() -> None:
    """Whitespace, quotes, trailing punctuation and case should not break parsing."""
    llm = RecordingLLM(["  TRIVIAL.\n"])
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=0))

    assert await svc.classify("hi", has_tools=False) == TaskComplexity.TRIVIAL


@pytest.mark.asyncio
async def test_classify_uses_cache_on_second_call() -> None:
    """Identical (content, has_tools) within the TTL should not re-hit the LLM."""
    llm = RecordingLLM(["single_tool"])
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=600))

    first = await svc.classify("same prompt", has_tools=True)
    second = await svc.classify("same prompt", has_tools=True)

    assert first == second == TaskComplexity.SINGLE_TOOL
    assert len(llm.calls) == 1, "Cache hit should skip the LLM"


@pytest.mark.asyncio
async def test_classify_cache_partitioned_by_has_tools() -> None:
    """Toggling ``has_tools`` must produce a distinct cache entry."""
    llm = RecordingLLM(["trivial", "single_tool"])
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=600))

    a = await svc.classify("hello", has_tools=False)
    b = await svc.classify("hello", has_tools=True)

    assert a == TaskComplexity.TRIVIAL
    assert b == TaskComplexity.SINGLE_TOOL
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_classify_unknown_output_falls_back() -> None:
    """Garbage output -> safe default depending on ``has_tools``."""
    llm = RecordingLLM(["banana", "banana"])
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=0))

    assert await svc.classify("x", has_tools=True) == TaskComplexity.MULTI_STEP
    assert await svc.classify("x", has_tools=False) == TaskComplexity.TRIVIAL


@pytest.mark.asyncio
async def test_classify_llm_error_falls_back() -> None:
    """LLM exception -> fail-safe value, never raises."""
    llm = RecordingLLM([], raise_on=0)
    svc = ClassifierService(llm, ClassifierConfig(cache_ttl_seconds=0))

    result = await svc.classify("anything", has_tools=True)
    assert result == TaskComplexity.MULTI_STEP


@pytest.mark.asyncio
async def test_classify_passes_system_prompt_and_max_tokens() -> None:
    """The classifier must forward its system prompt and token cap."""
    llm = RecordingLLM(["trivial"])
    cfg = ClassifierConfig(cache_ttl_seconds=0, max_output_tokens=7)
    svc = ClassifierService(llm, cfg)

    await svc.classify("ping", has_tools=False)

    call = llm.calls[0]
    assert call["max_output_tokens"] == 7
    assert call["system_prompt"] is not None
    assert "trivial" in call["system_prompt"]
