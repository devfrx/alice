"""Shared mock LLM for agent service tests.

Mirrors the streaming contract of ``LLMService.chat`` (yields
``{"type": "token"|"done", ...}`` events) but lets each test fix the
exact text the model "produces" on every call.
"""

from __future__ import annotations

import asyncio
from typing import Any


class RecordingLLM:
    """Async-iterator chat mock that returns a queued list of texts.

    Each entry of ``responses`` is the *full* assistant text emitted by
    one call to ``chat``.  Once the queue is exhausted, an empty
    response is returned so tests don't crash on accidental extra calls.
    """

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        raise_on: int | None = None,
    ) -> None:
        self._responses: list[str] = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        self._raise_on = raise_on

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Any = None,
        cancel_event: asyncio.Event | None = None,
        *,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ):
        """Yield events that mimic ``LLMService.chat``."""
        idx = len(self.calls)
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "system_prompt": system_prompt,
                "max_output_tokens": max_output_tokens,
                "extra": kwargs,
            }
        )
        if self._raise_on is not None and idx == self._raise_on:
            raise RuntimeError("simulated LLM failure")

        text = self._responses[idx] if idx < len(self._responses) else ""
        if text:
            yield {"type": "token", "content": text}
        yield {"type": "done"}
