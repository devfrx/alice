"""DTO del motore: normalizzazione tool call e mapping finish_reason."""

from backend.services.agent.models import (
    STOP_TO_FINISH,
    StopReason,
    normalize_tool_invocations,
)


def test_normalize_assigns_missing_call_ids() -> None:
    raw = [{"function": {"name": "read_file", "arguments": '{"path": "a.txt"}'}}]
    calls = normalize_tool_invocations(raw)
    assert len(calls) == 1
    assert calls[0].call_id.startswith("call_") and len(calls[0].call_id) > 10
    assert calls[0].name == "read_file"
    assert calls[0].args == {"path": "a.txt"}
    assert calls[0].parse_error is None


def test_normalize_preserves_existing_id_and_bad_json() -> None:
    raw = [{"id": "call_abc", "function": {"name": "t", "arguments": "{oops"}}]
    calls = normalize_tool_invocations(raw)
    assert calls[0].call_id == "call_abc"
    assert calls[0].args == {}
    assert calls[0].raw_args == "{oops"
    assert calls[0].parse_error is not None


def test_normalize_missing_name_yields_parse_error() -> None:
    raw = [{"id": "call_x", "function": {"arguments": "{}"}}]
    calls = normalize_tool_invocations(raw)
    assert calls[0].name == ""
    assert calls[0].parse_error is not None


def test_stop_reason_maps_to_legacy_finish_vocabulary() -> None:
    assert STOP_TO_FINISH[StopReason.COMPLETED] == "stop"
    assert STOP_TO_FINISH[StopReason.MAX_STEPS] == "stop"
    assert STOP_TO_FINISH[StopReason.CANCELLED] == "cancelled"
    assert STOP_TO_FINISH[StopReason.DISCONNECTED] == "disconnected"
    assert STOP_TO_FINISH[StopReason.ERROR] == "error"
    assert STOP_TO_FINISH[StopReason.LENGTH] == "length"
    assert set(STOP_TO_FINISH) == set(StopReason)
