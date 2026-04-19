"""Shared helpers for ``DirectTurnExecutor`` unit tests.

Provides minimal mocks for ``LLMService`` (event-stream chat),
``AppContext`` (config sub-tree only), and a ``TurnInput`` factory so
each test stays focused on one behaviour.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

from backend.services.turn.models import TurnInput


class StreamingMockLLM:
    """Mock ``LLMService`` whose ``chat`` yields a fixed event list.

    Args:
        events: Sequence of ``dict`` events to yield in order.  Each
            event mirrors the contract of the real ``LLMService.chat``
            generator (``{"type": "token", "content": "..."}`` etc.).
        raise_exc: Optional exception raised before yielding anything;
            used to exercise the executor's LLM error path.
        sleep_per_event: Optional ``asyncio.sleep`` between yields.
            Lets the cancel-event path race the stream deterministically.
    """

    def __init__(
        self,
        events: Iterable[dict[str, Any]] | None = None,
        *,
        raise_exc: Exception | None = None,
        sleep_per_event: float = 0.0,
    ) -> None:
        self._events = list(events or [])
        self._raise_exc = raise_exc
        self._sleep = sleep_per_event
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any):
        """Async-iterator emulation of ``LLMService.chat``."""
        self.calls.append({"messages": messages, **kwargs})
        if self._raise_exc is not None:
            raise self._raise_exc
        for event in self._events:
            if self._sleep:
                await asyncio.sleep(self._sleep)
            yield event


def make_ctx() -> Any:
    """Build a minimal ``AppContext`` stub for the executor.

    Only the attributes accessed by ``DirectTurnExecutor`` are populated
    (``config.llm.max_tool_iterations`` and
    ``config.pc_automation.confirmation_timeout_s``).
    """
    return SimpleNamespace(
        config=SimpleNamespace(
            llm=SimpleNamespace(max_tool_iterations=4),
            pc_automation=SimpleNamespace(confirmation_timeout_s=60),
        ),
    )


def make_turn(
    *,
    user_content: str = "ciao",
    history: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    was_compressed: bool = False,
) -> TurnInput:
    """Build a ``TurnInput`` with sensible defaults for tests."""
    conv_id = uuid.uuid4()
    return TurnInput(
        conv_id=conv_id,
        user_msg_id=uuid.uuid4(),
        user_content=user_content,
        history=history or [],
        messages=messages or [{"role": "user", "content": user_content}],
        tools=tools,
        memory_context=None,
        cached_sys_prompt=None,
        attachment_info=None,
        context_window=4096,
        version_group_id=None,
        version_index=0,
        client_ip="127.0.0.1",
        resolved_max_tokens=None,
        was_compressed=was_compressed,
        compressed_history=None,
        tool_tokens=0,
    )
