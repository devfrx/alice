"""AL\\CE — Canonical turn-event vocabulary (Fase 3).

This module defines the **additive** canonical turn-event stream that the
model-driven turn engine emits alongside (not instead of) the existing ad-hoc
frames (``token``, ``thinking``, ``tool_execution_start``, ``done`` …). The
frontend consumes these frames to build a structured activity timeline for a
turn. Wiring the engine to emit them is a *later* task — this module only
provides the vocabulary.

Every public function here is a **pure, side-effect-free builder** that returns
a plain JSON-serialisable ``dict[str, Any]`` carrying a ``"type"`` key set to
the corresponding :class:`TurnEventType` value (as a plain ``str``, so the
frame is trivially serialisable). All builders are keyword-only and fully
type-hinted.

Optional keys are **omitted** from the returned frame when their value is
``None`` (e.g. ``tool_result`` without ``content_type``) so frames stay tight.
The one deliberate exception is ``turn_finished``'s ``finish_reason``, which is
always present even when ``None`` (a turn always has a terminal disposition,
``None`` meaning "not reported by the model").
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class TurnEventType(StrEnum):
    """Canonical turn-event ``"type"`` names emitted during a turn.

    Members are :class:`enum.StrEnum` values so they compare equal to their
    wire string while remaining a single source of truth for the vocabulary.
    """

    TURN_STARTED = "turn.started"
    TURN_LLM_STEP = "turn.llm_step"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    INTERACTION_REQUESTED = "interaction.requested"
    INTERACTION_RESOLVED = "interaction.resolved"
    TURN_USAGE = "turn.usage"
    TURN_FINISHED = "turn.finished"


CANONICAL_TURN_EVENT_TYPES: frozenset[str] = frozenset(member.value for member in TurnEventType)
"""All canonical turn-event ``"type"`` strings, derived from the enum."""


def turn_started(*, turn_id: str, conversation_id: str) -> dict[str, Any]:
    """Build a ``turn.started`` frame marking the start of a turn.

    Args:
        turn_id: Stable identifier of the turn.
        conversation_id: Conversation the turn belongs to.

    Returns:
        The JSON-serialisable event frame.
    """
    return {
        "type": TurnEventType.TURN_STARTED.value,
        "turn_id": turn_id,
        "conversation_id": conversation_id,
    }


def turn_llm_step(*, turn_id: str, step: int) -> dict[str, Any]:
    """Build a ``turn.llm_step`` frame marking a new LLM iteration.

    Args:
        turn_id: Stable identifier of the turn.
        step: 1-based index of the LLM step within the turn.

    Returns:
        The JSON-serialisable event frame.
    """
    return {
        "type": TurnEventType.TURN_LLM_STEP.value,
        "turn_id": turn_id,
        "step": step,
    }


def tool_call(
    *,
    turn_id: str,
    execution_id: str,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Build a ``tool.call`` frame for an outgoing tool invocation.

    Args:
        turn_id: Stable identifier of the turn.
        execution_id: Identifier correlating this call with its later
            ``tool.result`` (and any interaction) frames.
        tool_name: Name of the tool being invoked.
        args: Arguments passed to the tool.

    Returns:
        The JSON-serialisable event frame.
    """
    return {
        "type": TurnEventType.TOOL_CALL.value,
        "turn_id": turn_id,
        "execution_id": execution_id,
        "tool_name": tool_name,
        "args": args,
    }


def tool_result(
    *,
    turn_id: str,
    execution_id: str,
    tool_name: str,
    success: bool,
    result: str,
    content_type: str | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Build a ``tool.result`` frame for a completed tool invocation.

    Args:
        turn_id: Stable identifier of the turn.
        execution_id: Identifier correlating this result with its originating
            ``tool.call`` frame.
        tool_name: Name of the tool that produced the result.
        success: Whether the tool completed without error.
        result: Textual result payload (already serialised by the engine).
        content_type: Optional MIME type of an associated artifact. Omitted
            from the frame when ``None``.
        artifact_id: Optional identifier of an associated artifact. Omitted
            from the frame when ``None``.

    Returns:
        The JSON-serialisable event frame.
    """
    frame: dict[str, Any] = {
        "type": TurnEventType.TOOL_RESULT.value,
        "turn_id": turn_id,
        "execution_id": execution_id,
        "tool_name": tool_name,
        "success": success,
        "result": result,
    }
    if content_type is not None:
        frame["content_type"] = content_type
    if artifact_id is not None:
        frame["artifact_id"] = artifact_id
    return frame


def interaction_requested(
    *,
    turn_id: str,
    execution_id: str,
    kind: str,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Build an ``interaction.requested`` frame for a pending user interaction.

    Args:
        turn_id: Stable identifier of the turn.
        execution_id: Identifier correlating this interaction with the tool
            call (or ask) that requested it, and with its later
            ``interaction.resolved`` frame.
        kind: Kind of interaction requested. One of ``"tool_confirmation"``,
            ``"client_tool_call"`` or ``"ask_user"``.
        tool_name: Optional name of the tool the interaction relates to.
            Omitted from the frame when ``None``.

    Returns:
        The JSON-serialisable event frame.
    """
    frame: dict[str, Any] = {
        "type": TurnEventType.INTERACTION_REQUESTED.value,
        "turn_id": turn_id,
        "execution_id": execution_id,
        "kind": kind,
    }
    if tool_name is not None:
        frame["tool_name"] = tool_name
    return frame


def interaction_resolved(
    *,
    turn_id: str,
    execution_id: str,
    kind: str,
    outcome: str,
) -> dict[str, Any]:
    """Build an ``interaction.resolved`` frame closing a prior interaction.

    Args:
        turn_id: Stable identifier of the turn.
        execution_id: Identifier correlating this resolution with its
            originating ``interaction.requested`` frame.
        kind: Kind of interaction that was resolved. One of
            ``"tool_confirmation"``, ``"client_tool_call"`` or ``"ask_user"``.
        outcome: How the interaction resolved. One of ``"approved"``,
            ``"rejected"``, ``"answered"``, ``"executed"``, ``"timeout"``,
            ``"cancelled"`` or ``"disconnected"``.

    Returns:
        The JSON-serialisable event frame.
    """
    return {
        "type": TurnEventType.INTERACTION_RESOLVED.value,
        "turn_id": turn_id,
        "execution_id": execution_id,
        "kind": kind,
        "outcome": outcome,
    }


def turn_usage(
    *,
    turn_id: str,
    step: int,
    input_tokens: int,
    output_tokens: int,
    tool_calls: int,
    max_steps: int,
) -> dict[str, Any]:
    """Build a ``turn.usage`` frame reporting per-step resource usage.

    Args:
        turn_id: Stable identifier of the turn.
        step: 1-based index of the LLM step this usage snapshot covers.
        input_tokens: Input tokens consumed at this step.
        output_tokens: Output tokens produced at this step.
        tool_calls: Number of tool calls issued so far in the turn.
        max_steps: Configured maximum number of LLM steps for the turn.

    Returns:
        The JSON-serialisable event frame.
    """
    return {
        "type": TurnEventType.TURN_USAGE.value,
        "turn_id": turn_id,
        "step": step,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_calls": tool_calls,
        "max_steps": max_steps,
    }


def turn_finished(
    *,
    turn_id: str,
    finish_reason: str | None,
    input_tokens: int,
    output_tokens: int,
    steps: int,
    cost: float | None = None,
) -> dict[str, Any]:
    """Build a ``turn.finished`` frame marking the end of a turn.

    Unlike other optional fields, ``finish_reason`` and ``cost`` are always
    present (even when ``None``): a finished turn always carries a terminal
    disposition (``None`` meaning the model did not report one) and a cost
    slot (``None`` meaning the provider did not report one).

    Args:
        turn_id: Stable identifier of the turn.
        finish_reason: Terminal disposition of the turn (e.g. ``"stop"``,
            ``"length"``, ``"cancelled"``, ``"error"``, ``"disconnected"``),
            or ``None`` when not reported.
        input_tokens: Total input tokens for the final LLM step.
        output_tokens: Total output tokens for the final LLM step.
        steps: Number of LLM steps executed in the turn.
        cost: Total turn cost in provider credits, or ``None`` when not
            reported.

    Returns:
        The JSON-serialisable event frame.
    """
    return {
        "type": TurnEventType.TURN_FINISHED.value,
        "turn_id": turn_id,
        "finish_reason": finish_reason,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "steps": steps,
        "cost": cost,
    }


__all__ = [
    "CANONICAL_TURN_EVENT_TYPES",
    "TurnEventType",
    "interaction_requested",
    "interaction_resolved",
    "tool_call",
    "tool_result",
    "turn_finished",
    "turn_llm_step",
    "turn_started",
    "turn_usage",
]
