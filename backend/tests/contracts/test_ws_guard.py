"""Contract tests: the runtime WS wire guard (warn in prod, raise in tests)."""

from __future__ import annotations

import pytest
from backend.api.ws_schema.guard import (
    WsContractViolation,
    chat_frame_validator,
    events_frame_validator,
)


def test_valid_frames_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALICE_WS_STRICT_CONTRACTS", "1")
    events_frame_validator({"type": "heartbeat"})
    chat_frame_validator(
        {"type": "turn.warning", "turn_id": "t1", "code": "c", "message": "m"},
    )


def test_strict_mode_raises_on_unknown_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALICE_WS_STRICT_CONTRACTS", "1")
    with pytest.raises(WsContractViolation):
        events_frame_validator({"type": "no.such.event"})


def test_strict_mode_raises_on_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALICE_WS_STRICT_CONTRACTS", "1")
    with pytest.raises(WsContractViolation):
        # valid type, missing required ``message``
        chat_frame_validator({"type": "turn.warning", "turn_id": "t1", "code": "c"})


def test_lax_mode_only_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALICE_WS_STRICT_CONTRACTS", raising=False)
    events_frame_validator({"type": "no.such.event"})  # must not raise
