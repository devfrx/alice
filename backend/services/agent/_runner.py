"""Internal helper that consumes ``LLMService.chat`` async streams.

The agent services need a non-streaming interface (they collect the
final text answer before parsing JSON or matching keywords).  This
helper concentrates the streaming-to-string adapter in one place so
the three services stay tiny and trivially testable.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class _LLMLike(Protocol):
    """Minimal async-iterator chat protocol used by the agent services."""

    def chat(  # noqa: D401 — protocol stub
        self,
        messages: list[dict[str, Any]],
        tools: Any = None,
        cancel_event: asyncio.Event | None = None,
        *,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ) -> Any: ...


async def collect_text(
    llm: _LLMLike,
    messages: list[dict[str, Any]],
    *,
    system_prompt: str | None,
    max_output_tokens: int | None,
    cancel_event: asyncio.Event | None,
) -> str:
    """Run an LLM chat call and return the concatenated assistant text.

    Consumes the async iterator yielded by ``llm.chat``, accumulates the
    ``token`` events' ``content`` into one string and stops as soon as a
    ``done`` event arrives.  Other event types (``thinking``, ``tool_call``,
    ``error``) are intentionally ignored — agent components only need the
    visible answer.

    Args:
        llm: Object that exposes ``chat(...)``.
        messages: Full prompt list.
        system_prompt: Optional system prompt forwarded to ``llm.chat``.
        max_output_tokens: Cap on generated tokens.
        cancel_event: Optional cooperative cancellation event.

    Returns:
        The plain-text response.  Empty string if the stream produced no
        ``token`` events (caller decides how to handle that).
    """
    chunks: list[str] = []
    async for event in llm.chat(
        messages,
        tools=None,
        cancel_event=cancel_event,
        system_prompt=system_prompt,
        max_output_tokens=max_output_tokens,
    ):
        etype = event.get("type")
        if etype == "token":
            content = event.get("content")
            if content:
                chunks.append(content)
        elif etype == "done":
            break
    return "".join(chunks).strip()


__all__ = ["collect_text"]
