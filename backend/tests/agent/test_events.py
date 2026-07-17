"""Vocabolario eventi interni: type letterali, frozen, union esaustiva."""

import pydantic
import pytest

from backend.services.agent import events as ev
from backend.services.agent.models import ToolInvocation

CALL = ToolInvocation(call_id="call_1", name="t", args={}, raw_args="{}")


def test_every_event_has_literal_type() -> None:
    e = ev.ToolResultEvent(
        turn_id="t1", call_id="call_1", name="t", status="ok",
        content_preview="x", artifact_id=None,
    )
    assert e.type == "tool.result"


def test_events_are_frozen() -> None:
    e = ev.TurnStartedEvent(turn_id="t1", conversation_id="c1", source="chat")
    with pytest.raises(pydantic.ValidationError):
        e.turn_id = "other"  # type: ignore[misc]


def test_tool_call_event_embeds_invocation() -> None:
    e = ev.ToolCallEvent(turn_id="t1", step=1, call=CALL)
    assert e.type == "tool.call"
    assert e.call.call_id == "call_1"
    assert e.call.name == "t"


def test_union_covers_all_event_classes() -> None:
    classes = {
        c for n, c in vars(ev).items()
        if isinstance(c, type) and n.endswith("Event")
    }
    from typing import get_args
    assert set(get_args(ev.AgentEvent)) == classes
