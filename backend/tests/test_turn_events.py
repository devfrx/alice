"""AL\\CE — Unit tests for the canonical turn-event vocabulary (Fase 3).

These tests pin the contract of
:mod:`backend.services.turn.events`: every builder's ``"type"`` string, its
exact payload key set, the optional-key omission behaviour, and the fact that
every frame is JSON-serialisable. They are pure (no async, no I/O).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.services.turn import events
from backend.services.turn.events import CANONICAL_TURN_EVENT_TYPES, TurnEventType

# One representative frame per builder (including each optional-key variant).
SAMPLE_FRAMES: list[dict[str, Any]] = [
    events.turn_started(turn_id="t1", conversation_id="c1"),
    events.turn_llm_step(turn_id="t1", step=1),
    events.tool_call(
        turn_id="t1",
        execution_id="e1",
        tool_name="web_search",
        args={"query": "alice", "limit": 3},
    ),
    events.tool_result(
        turn_id="t1",
        execution_id="e1",
        tool_name="web_search",
        success=True,
        result="ok",
    ),
    events.tool_result(
        turn_id="t1",
        execution_id="e2",
        tool_name="generate_image",
        success=True,
        result="done",
        content_type="image/png",
        artifact_id="a1",
    ),
    events.interaction_requested(turn_id="t1", execution_id="e3", kind="ask_user"),
    events.interaction_requested(
        turn_id="t1",
        execution_id="e4",
        kind="tool_confirmation",
        tool_name="run_shell",
    ),
    events.interaction_resolved(
        turn_id="t1",
        execution_id="e4",
        kind="tool_confirmation",
        outcome="approved",
    ),
    events.turn_usage(
        turn_id="t1",
        step=2,
        input_tokens=120,
        output_tokens=34,
        tool_calls=1,
        max_steps=8,
    ),
    events.turn_finished(
        turn_id="t1",
        finish_reason="stop",
        input_tokens=120,
        output_tokens=34,
        steps=3,
    ),
    events.turn_finished(
        turn_id="t1",
        finish_reason=None,
        input_tokens=0,
        output_tokens=0,
        steps=0,
    ),
]


# ---------------------------------------------------------------------------
# Canonical type set
# ---------------------------------------------------------------------------


def test_canonical_event_types_are_the_eight_expected_strings() -> None:
    expected = {
        "turn.started",
        "turn.llm_step",
        "tool.call",
        "tool.result",
        "interaction.requested",
        "interaction.resolved",
        "turn.usage",
        "turn.finished",
    }
    assert set(CANONICAL_TURN_EVENT_TYPES) == expected
    assert len(CANONICAL_TURN_EVENT_TYPES) == 8


def test_canonical_event_types_is_a_frozenset_derived_from_the_enum() -> None:
    assert isinstance(CANONICAL_TURN_EVENT_TYPES, frozenset)
    assert set(CANONICAL_TURN_EVENT_TYPES) == frozenset(member.value for member in TurnEventType)


# ---------------------------------------------------------------------------
# Per-builder type + exact key set
# ---------------------------------------------------------------------------


def test_turn_started() -> None:
    frame = events.turn_started(turn_id="t1", conversation_id="c1")
    assert frame["type"] == TurnEventType.TURN_STARTED.value == "turn.started"
    assert set(frame) == {"type", "turn_id", "conversation_id"}
    assert frame["turn_id"] == "t1"
    assert frame["conversation_id"] == "c1"


def test_turn_llm_step() -> None:
    frame = events.turn_llm_step(turn_id="t1", step=4)
    assert frame["type"] == TurnEventType.TURN_LLM_STEP.value == "turn.llm_step"
    assert set(frame) == {"type", "turn_id", "step"}
    assert frame["step"] == 4


def test_tool_call() -> None:
    args = {"query": "alice", "limit": 3}
    frame = events.tool_call(turn_id="t1", execution_id="e1", tool_name="web_search", args=args)
    assert frame["type"] == TurnEventType.TOOL_CALL.value == "tool.call"
    assert set(frame) == {"type", "turn_id", "execution_id", "tool_name", "args"}
    assert frame["execution_id"] == "e1"
    assert frame["tool_name"] == "web_search"
    assert frame["args"] == args


def test_tool_result_omits_optionals_when_none() -> None:
    frame = events.tool_result(
        turn_id="t1",
        execution_id="e1",
        tool_name="web_search",
        success=True,
        result="ok",
    )
    assert frame["type"] == TurnEventType.TOOL_RESULT.value == "tool.result"
    assert set(frame) == {"type", "turn_id", "execution_id", "tool_name", "success", "result"}
    assert "content_type" not in frame
    assert "artifact_id" not in frame
    assert frame["success"] is True
    assert frame["result"] == "ok"


def test_tool_result_includes_both_optionals_when_set() -> None:
    frame = events.tool_result(
        turn_id="t1",
        execution_id="e2",
        tool_name="generate_image",
        success=False,
        result="boom",
        content_type="image/png",
        artifact_id="a1",
    )
    assert set(frame) == {
        "type",
        "turn_id",
        "execution_id",
        "tool_name",
        "success",
        "result",
        "content_type",
        "artifact_id",
    }
    assert frame["content_type"] == "image/png"
    assert frame["artifact_id"] == "a1"
    assert frame["success"] is False


def test_tool_result_includes_only_the_provided_optional() -> None:
    frame = events.tool_result(
        turn_id="t1",
        execution_id="e3",
        tool_name="generate_chart",
        success=True,
        result="ok",
        content_type="text/plain",
    )
    assert "content_type" in frame
    assert frame["content_type"] == "text/plain"
    assert "artifact_id" not in frame


def test_interaction_requested_omits_tool_name_when_none() -> None:
    frame = events.interaction_requested(turn_id="t1", execution_id="e1", kind="ask_user")
    assert frame["type"] == TurnEventType.INTERACTION_REQUESTED.value == "interaction.requested"
    assert set(frame) == {"type", "turn_id", "execution_id", "kind"}
    assert "tool_name" not in frame
    assert frame["kind"] == "ask_user"


def test_interaction_requested_includes_tool_name_when_set() -> None:
    frame = events.interaction_requested(
        turn_id="t1",
        execution_id="e1",
        kind="tool_confirmation",
        tool_name="run_shell",
    )
    assert set(frame) == {"type", "turn_id", "execution_id", "kind", "tool_name"}
    assert frame["tool_name"] == "run_shell"


def test_interaction_resolved() -> None:
    frame = events.interaction_resolved(
        turn_id="t1",
        execution_id="e1",
        kind="tool_confirmation",
        outcome="rejected",
    )
    assert frame["type"] == TurnEventType.INTERACTION_RESOLVED.value == "interaction.resolved"
    assert set(frame) == {"type", "turn_id", "execution_id", "kind", "outcome"}
    assert frame["outcome"] == "rejected"


def test_turn_usage() -> None:
    frame = events.turn_usage(
        turn_id="t1",
        step=2,
        input_tokens=120,
        output_tokens=34,
        tool_calls=1,
        max_steps=8,
    )
    assert frame["type"] == TurnEventType.TURN_USAGE.value == "turn.usage"
    assert set(frame) == {
        "type",
        "turn_id",
        "step",
        "input_tokens",
        "output_tokens",
        "tool_calls",
        "max_steps",
    }
    assert frame["input_tokens"] == 120
    assert frame["output_tokens"] == 34
    assert frame["tool_calls"] == 1
    assert frame["max_steps"] == 8


def test_turn_finished_with_reason() -> None:
    frame = events.turn_finished(
        turn_id="t1",
        finish_reason="stop",
        input_tokens=120,
        output_tokens=34,
        steps=3,
    )
    assert frame["type"] == TurnEventType.TURN_FINISHED.value == "turn.finished"
    assert set(frame) == {
        "type",
        "turn_id",
        "finish_reason",
        "input_tokens",
        "output_tokens",
        "steps",
    }
    assert frame["finish_reason"] == "stop"
    assert frame["steps"] == 3


def test_turn_finished_keeps_finish_reason_when_none() -> None:
    frame = events.turn_finished(
        turn_id="t1",
        finish_reason=None,
        input_tokens=0,
        output_tokens=0,
        steps=0,
    )
    assert set(frame) == {
        "type",
        "turn_id",
        "finish_reason",
        "input_tokens",
        "output_tokens",
        "steps",
    }
    assert "finish_reason" in frame
    assert frame["finish_reason"] is None


# ---------------------------------------------------------------------------
# Cross-cutting invariants (over one frame per builder/variant)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("frame", SAMPLE_FRAMES, ids=lambda f: f["type"])
def test_every_frame_type_is_canonical(frame: dict[str, Any]) -> None:
    assert frame["type"] in CANONICAL_TURN_EVENT_TYPES
    # A plain string in the dict, never the StrEnum member object.
    assert type(frame["type"]) is str


@pytest.mark.parametrize("frame", SAMPLE_FRAMES, ids=lambda f: f["type"])
def test_every_frame_round_trips_through_json(frame: dict[str, Any]) -> None:
    assert json.loads(json.dumps(frame)) == frame
