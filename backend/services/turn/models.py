"""AL\\CE — DTOs for the turn execution layer.

Immutable dataclasses passed between ``ws_chat`` (protocol layer) and a
:class:`~backend.services.turn.direct_executor.DirectTurnExecutor` (or any
other :class:`TurnExecutor` strategy).

The DTOs intentionally carry **only** state needed to execute a turn:
nothing about WebSocket frames, DB sessions, or post-turn persistence.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TurnInput:
    """Everything required to execute a single LLM turn.

    The DTO is **immutable** so it can safely cross task boundaries and be
    inspected in tests without aliasing concerns.

    Args:
        conv_id: Conversation UUID the turn belongs to.
        user_msg_id: UUID of the user :class:`Message` that triggered the
            turn (already persisted by the caller).
        user_content: Raw user text (used by the LM Studio native API path
            when ``was_compressed`` is ``False``).
        history: Filtered conversation history (no system prompt).
        messages: Fully-assembled prompt (system + memory + history)
            suitable for the OpenAI-compatible chat completion path.
        tools: Optional tool definitions for function calling.
        memory_context: Pre-formatted memory block injected upstream of the
            turn (passed through to LLM service for the native path).
        cached_sys_prompt: System prompt already built once by the caller —
            re-used across re-queries inside the tool loop.
        attachment_info: Optional list of attachment dicts
            (``file_path``/``content_type``/``_bytes``) for vision input.
        context_window: Effective context window of the active model.
        version_group_id: Branching group of the user message (propagated
            to all assistant/tool messages produced by this turn).
        version_index: Index of the active branch.
        client_ip: Client IP forwarded as ``session_id`` to the tool
            execution context.
        resolved_max_tokens: Optional output-token budget (computed from
            available context when the global ``max_tokens`` is unset).
        was_compressed: ``True`` if pre-generation compression archived
            messages before this turn started. When set, the executor must
            force the OpenAI-compatible streaming path (``user_content=None``
            in :meth:`LLMService.chat`) and feed ``compressed_history`` to
            :func:`run_tool_loop` instead of ``history`` to avoid
            re-compression on the first iteration.
        compressed_history: History after pre-gen compression (without the
            system message). Required when ``was_compressed`` is ``True``.
        tool_tokens: Token count of the serialized tool definitions, used
            by post-turn breakdown calculations.
    """

    conv_id: uuid.UUID
    user_msg_id: uuid.UUID
    user_content: str
    history: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    memory_context: str | None
    cached_sys_prompt: str | None
    attachment_info: list[dict[str, Any]] | None
    context_window: int
    version_group_id: uuid.UUID | None
    version_index: int
    client_ip: str
    resolved_max_tokens: int | None
    was_compressed: bool = False
    compressed_history: list[dict[str, Any]] | None = None
    tool_tokens: int = 0


@dataclass(frozen=True, slots=True)
class TurnResult:
    """Outcome of a single turn produced by a :class:`TurnExecutor`.

    Intermediate persistence (assistant messages with tool calls, tool
    response messages, summaries from per-iteration compression) has
    already been committed by the executor through ``run_tool_loop``.
    The caller is only responsible for persisting the *final* assistant
    message and triggering post-stream side effects.

    Args:
        content: Final assistant text content (concatenated across tool
            loop iterations when applicable).
        thinking: Final reasoning trace (concatenated likewise).
        input_tokens: Real input-token usage from the last LLM re-query
            (``0`` when the LLM did not report usage).
        output_tokens: Real output-token usage from the last re-query.
        finish_reason: Terminal state of the turn. One of
            ``"stop"``, ``"length"``, ``"cancelled"``, ``"error"``,
            ``"disconnected"``.
        final_assistant_message_id: Optional message UUID written by the
            executor (always ``None`` for :class:`DirectTurnExecutor` —
            persistence happens in ``ws_chat``).
        had_tool_calls: ``True`` when the turn invoked the tool loop.
            The caller uses this to decide whether to skip persisting an
            empty final assistant message (intermediates already
            committed by the loop).
        agent_run_id: Optional UUID of a persisted ``AgentRun`` row.
            Always ``None`` on the current model-driven path (kept for
            backward-compatible serialization).
        cost: Total generation cost in provider credits, accumulated from
            per-step ``usage`` events (``0.0`` = not reported by the
            provider, e.g. LM Studio's native path).
    """

    content: str
    thinking: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    cost: float = 0.0
    final_assistant_message_id: uuid.UUID | None = None
    had_tool_calls: bool = False
    agent_run_id: uuid.UUID | None = None


@dataclass
class TurnProgress:
    """Mutable per-turn counters shared between the executor and the tool loop.

    Used to emit the canonical turn-lifecycle events with a stable
    ``turn_id`` and accurate step/tool-call counts without threading extra
    return values out of :func:`run_tool_loop`.

    Args:
        turn_id: Stable identifier minted once at the start of the turn.
        steps: Number of LLM steps emitted so far this turn.
        tool_calls: Cumulative tool calls dispatched this turn.
        cost: Accumulated generation cost across all LLM steps of the turn.
    """

    turn_id: str
    steps: int = 0
    tool_calls: int = 0
    cost: float = 0.0
