"""Test ``LLMServiceAdapter`` — mapping chunk dict piattaforma -> ``LLMEvent``.

``FakeLLMService`` riproduce il contratto REALE di
``backend.services.llm_service.LLMService.chat`` (che delega a
``backend/services/llm/client.py``), verificato leggendo il codice prima di
scrivere questo fake (vedi anche le citazioni riga-per-riga nella docstring
di modulo di ``backend/services/agent/adapters/llm.py``):

- ``{"type": "token", "content": str}`` (client.py righe 403/756)
- ``{"type": "thinking", "content": str}`` (righe 389/744)
- ``{"type": "tool_call", "id": str, "function": {"name": str, "arguments": str}}``
  — UNA tool-call già completa per chunk (righe 678-685, 804-811); non un
  delta parziale indicizzato come nell'esempio illustrativo del brief di
  Task 12. L'adapter accumula comunque per ``id`` in forma difensiva — un
  test qui sotto lo esercita esplicitamente con frammenti parziali per
  provare che il comportamento "incrementale" richiesto dal brief è
  implementato, anche se il servizio reale oggi non lo produce.
- ``{"type": "usage", "input_tokens": int, "output_tokens": int, "cost"?: float}``
  (righe 686-692; nessun ``cost`` nel path nativo, righe 422-429).
- ``{"type": "error", "content": str}`` (righe 711-726 / 453-475) — nessuno
  status HTTP è mai incluso nel contratto attuale; l'adapter cerca
  comunque ``status_code``/``status``/``http_status`` in modo difensivo, ed è
  quello che i test sotto esercitano per coprire entrambi i rami di
  ``retryable``.
- ``{"type": "done", "finish_reason": str}`` (riga 812 e altrove).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from backend.services.agent import ports
from backend.services.agent.adapters.llm import LLMServiceAdapter


class FakeLLMService:
    """Fake locale: riproduce il contratto reale di ``LLMService.chat``."""

    def __init__(
        self, chunks: list[dict[str, Any]], *, supports_vision: bool = False,
    ) -> None:
        self._chunks = chunks
        self.calls: list[dict[str, Any]] = []
        self.supports_vision = supports_vision

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        cancel_event: asyncio.Event | None = None,
        *,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
        **_kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append({
            "messages": messages, "tools": tools,
            "system_prompt": system_prompt, "max_output_tokens": max_output_tokens,
        })
        for chunk in self._chunks:
            yield chunk


async def _collect(adapter: LLMServiceAdapter) -> list[ports.LLMEvent]:
    events: list[ports.LLMEvent] = []
    async for event in adapter.stream_step(
        system_prompt="sys", messages=[{"role": "user", "content": "hi"}],
        tools=[], max_tokens=None, cancel=asyncio.Event(),
    ):
        events.append(event)
    return events


async def test_token_and_thinking_chunks_become_deltas() -> None:
    fake = FakeLLMService(chunks=[
        {"type": "thinking", "content": "penso..."},
        {"type": "token", "content": "ciao"},
        {"type": "token", "content": " mondo"},
        {"type": "done", "finish_reason": "stop"},
    ])
    events = await _collect(LLMServiceAdapter(fake))

    thinking = [e for e in events if isinstance(e, ports.LLMThinkingDelta)]
    tokens = [e for e in events if isinstance(e, ports.LLMTextDelta)]
    assert [t.text for t in thinking] == ["penso..."]
    assert [t.text for t in tokens] == ["ciao", " mondo"]

    done = [e for e in events if isinstance(e, ports.LLMStepDone)]
    assert len(done) == 1
    assert done[0].finish_reason == "stop"
    assert done[0].tool_calls == ()


async def test_complete_tool_call_chunks_become_one_stepdone() -> None:
    """Contratto reale: ogni chunk 'tool_call' è già una call completa."""
    fake = FakeLLMService(chunks=[
        {"type": "tool_call", "id": "call_1",
         "function": {"name": "read", "arguments": '{"path": "a.txt"}'}},
        {"type": "tool_call", "id": "call_2",
         "function": {"name": "write", "arguments": '{"path": "b.txt"}'}},
        {"type": "done", "finish_reason": "tool_calls"},
    ])
    events = await _collect(LLMServiceAdapter(fake))

    done = [e for e in events if isinstance(e, ports.LLMStepDone)]
    assert len(done) == 1
    assert done[0].finish_reason == "tool_calls"
    assert [tc.name for tc in done[0].tool_calls] == ["read", "write"]
    assert done[0].tool_calls[0].args == {"path": "a.txt"}
    assert done[0].tool_calls[1].args == {"path": "b.txt"}


async def test_partial_tool_call_fragments_with_same_id_are_merged() -> None:
    """Comportamento difensivo (brief Task 12): accumulo per id di frammenti
    parziali — non prodotto dal servizio reale oggi, ma l'adapter lo
    gestisce correttamente se il contratto tornasse a essere incrementale.
    """
    fake = FakeLLMService(chunks=[
        {"type": "tool_call", "id": "call_1",
         "function": {"name": "read", "arguments": '{"pa'}},
        {"type": "tool_call", "id": "call_1",
         "function": {"arguments": 'th": "a.txt"}'}},
        {"type": "done", "finish_reason": "tool_calls"},
    ])
    events = await _collect(LLMServiceAdapter(fake))

    done = [e for e in events if isinstance(e, ports.LLMStepDone)]
    assert len(done) == 1
    assert len(done[0].tool_calls) == 1
    assert done[0].tool_calls[0].name == "read"
    assert done[0].tool_calls[0].args == {"path": "a.txt"}


async def test_error_chunk_with_4xx_status_is_not_retryable() -> None:
    fake = FakeLLMService(chunks=[
        {"type": "error", "content": "bad request", "status_code": 400},
        {"type": "done", "finish_reason": "error"},
    ])
    events = await _collect(LLMServiceAdapter(fake))

    failures = [e for e in events if isinstance(e, ports.LLMFailure)]
    assert len(failures) == 1
    assert failures[0].retryable is False
    assert failures[0].status_code == 400
    assert failures[0].message == "bad request"


async def test_error_chunk_without_status_is_retryable() -> None:
    fake = FakeLLMService(chunks=[
        {"type": "error", "content": "connection reset"},
        {"type": "done", "finish_reason": "error"},
    ])
    events = await _collect(LLMServiceAdapter(fake))

    failures = [e for e in events if isinstance(e, ports.LLMFailure)]
    assert len(failures) == 1
    assert failures[0].retryable is True
    assert failures[0].status_code is None


async def test_5xx_status_is_retryable() -> None:
    fake = FakeLLMService(chunks=[
        {"type": "error", "content": "server exploded", "status_code": 503},
        {"type": "done", "finish_reason": "error"},
    ])
    events = await _collect(LLMServiceAdapter(fake))

    failures = [e for e in events if isinstance(e, ports.LLMFailure)]
    assert failures[0].retryable is True


async def test_usage_chunk_has_cost() -> None:
    fake = FakeLLMService(chunks=[
        {"type": "usage", "input_tokens": 120, "output_tokens": 30, "cost": 0.0042},
        {"type": "done", "finish_reason": "stop"},
    ])
    events = await _collect(LLMServiceAdapter(fake))

    usages = [e for e in events if isinstance(e, ports.LLMUsage)]
    assert len(usages) == 1
    assert usages[0].input_tokens == 120
    assert usages[0].output_tokens == 30
    assert usages[0].cost == 0.0042


def test_supports_vision_delegates_to_llm_service() -> None:
    """La capability vision della porta delega al servizio wrappato."""
    fake = FakeLLMService(chunks=[], supports_vision=True)
    adapter = LLMServiceAdapter(fake)  # type: ignore[arg-type]
    assert adapter.supports_vision() is True


def test_supports_vision_false_by_default() -> None:
    fake = FakeLLMService(chunks=[])
    adapter = LLMServiceAdapter(fake)  # type: ignore[arg-type]
    assert adapter.supports_vision() is False


async def test_usage_chunk_without_cost_defaults_to_zero() -> None:
    """Path nativo LM Studio (client.py righe 422-429): 'cost' assente."""
    fake = FakeLLMService(chunks=[
        {"type": "usage", "input_tokens": 50, "output_tokens": 10},
        {"type": "done", "finish_reason": "stop"},
    ])
    events = await _collect(LLMServiceAdapter(fake))

    usages = [e for e in events if isinstance(e, ports.LLMUsage)]
    assert usages[0].cost == 0.0
