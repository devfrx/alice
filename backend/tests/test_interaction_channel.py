"""Tests for the inbound :mod:`backend.services.turn.channel`.

These exercise the production :class:`WebSocketInteractionChannel` (single
read-pump routing by ``execution_id`` / cancel / timeout / stale frames)
plus the :class:`ScriptedInteractionChannel` test double.

A :class:`FakeWebSocket` feeds raw frames into the pump and records the
frames the channel sends back, so the round-trip contract can be asserted
without a real socket.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.services.turn.channel import (
    ScriptedInteractionChannel,
    WebSocketInteractionChannel,
)


class _DisconnectError(Exception):
    """Raised by :class:`FakeWebSocket.receive_text` to simulate a drop."""


class FakeWebSocket:
    """Minimal WebSocket double driving the channel pump.

    ``receive_text`` blocks on an internal queue; ``feed`` enqueues a raw
    frame and ``disconnect`` makes the next receive raise (mapped by the
    pump to a transport close).  ``send_json`` records outbound frames.
    """

    def __init__(self) -> None:
        self._incoming: asyncio.Queue[str | _DisconnectError] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []

    async def receive_text(self) -> str:
        item = await self._incoming.get()
        if isinstance(item, _DisconnectError):
            raise item
        return item

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    def feed(self, frame: dict[str, Any]) -> None:
        self._incoming.put_nowait(json.dumps(frame))

    def feed_raw(self, raw: str) -> None:
        self._incoming.put_nowait(raw)

    def disconnect(self) -> None:
        self._incoming.put_nowait(_DisconnectError())


async def _settle() -> None:
    """Yield control so the pump can drain the queue deterministically."""
    for _ in range(5):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# WebSocketInteractionChannel
# ---------------------------------------------------------------------------


async def test_request_resolves_on_matching_response() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        task = asyncio.ensure_future(
            ch.request(
                "tool_confirmation",
                {"tool_name": "t", "args": {}},
                execution_id="e1",
                timeout_s=2.0,
            ),
        )
        await _settle()
        # The outbound request frame was sent with the mapped type + id.
        assert ws.sent[-1]["type"] == "tool_confirmation_required"
        assert ws.sent[-1]["execution_id"] == "e1"

        ws.feed({"type": "tool_confirmation_response", "execution_id": "e1", "approved": True})
        result = await asyncio.wait_for(task, timeout=1.0)
        assert result is not None
        assert result["approved"] is True
    finally:
        await ch.aclose()


async def test_request_ignores_mismatched_execution_id() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        task = asyncio.ensure_future(
            ch.request(
                "tool_confirmation", {}, execution_id="e1", timeout_s=2.0,
            ),
        )
        await _settle()
        # A response for a different id must not resolve our request.
        ws.feed({"type": "tool_confirmation_response", "execution_id": "OTHER", "approved": True})
        await _settle()
        assert not task.done()
        # The correct id does.
        ws.feed({"type": "tool_confirmation_response", "execution_id": "e1", "approved": False})
        result = await asyncio.wait_for(task, timeout=1.0)
        assert result is not None
        assert result["approved"] is False
    finally:
        await ch.aclose()


async def test_request_timeout_returns_none() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        result = await ch.request(
            "client_tool_call", {}, execution_id="e1", timeout_s=0.05,
        )
        assert result is None
        assert ch.connected is True
        assert ch.cancelled is False
    finally:
        await ch.aclose()


async def test_cancel_frame_unblocks_pending_and_sets_cancelled() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    cancel_event = ch.begin_turn()
    ch.start()
    try:
        task = asyncio.ensure_future(
            ch.request(
                "tool_confirmation", {}, execution_id="e1",
                timeout_s=5.0, cancel_event=cancel_event,
            ),
        )
        await _settle()
        ws.feed({"type": "cancel"})
        result = await asyncio.wait_for(task, timeout=1.0)
        assert result is None
        assert ch.cancelled is True
        assert cancel_event.is_set()
    finally:
        await ch.aclose()


async def test_stale_response_is_not_queued_as_user_message() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        # No pending request → this interaction response is stale.
        ws.feed({"type": "client_tool_result", "execution_id": "ghost", "success": True})
        # A genuine user frame follows.
        ws.feed({"type": "user_message", "content": "ciao"})
        await _settle()
        msg = await asyncio.wait_for(ch.next_user_message(), timeout=1.0)
        assert msg is not None
        assert msg["type"] == "user_message"
        assert msg["content"] == "ciao"
    finally:
        await ch.aclose()


async def test_user_message_routed_to_idle_queue() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        ws.feed({"type": "user_message", "content": "uno"})
        ws.feed({"type": "user_message", "content": "due"})
        first = await asyncio.wait_for(ch.next_user_message(), timeout=1.0)
        second = await asyncio.wait_for(ch.next_user_message(), timeout=1.0)
        assert first is not None and first["content"] == "uno"
        assert second is not None and second["content"] == "due"
    finally:
        await ch.aclose()


async def test_disconnect_marks_channel_and_wakes_idle_loop() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        pending = asyncio.ensure_future(
            ch.request("client_tool_call", {}, execution_id="e1", timeout_s=5.0),
        )
        await _settle()
        ws.disconnect()
        # Pending request resolves to None on disconnect.
        result = await asyncio.wait_for(pending, timeout=1.0)
        assert result is None
        assert ch.connected is False
        # Idle loop is woken with a None end-of-stream signal.
        idle = await asyncio.wait_for(ch.next_user_message(), timeout=1.0)
        assert idle is None
    finally:
        await ch.aclose()


async def test_request_after_disconnect_returns_none_immediately() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        ws.disconnect()
        await _settle()
        assert ch.connected is False
        result = await ch.request(
            "tool_confirmation", {}, execution_id="x", timeout_s=1.0,
        )
        assert result is None
    finally:
        await ch.aclose()


async def test_client_tool_request_sends_expected_frame() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        task = asyncio.ensure_future(
            ch.request(
                "client_tool_call",
                {"tool_name": "continuum_apply", "args": {"k": 1}},
                execution_id="c1",
                timeout_s=2.0,
            ),
        )
        await _settle()
        sent = ws.sent[-1]
        assert sent["type"] == "client_tool_call"
        assert sent["execution_id"] == "c1"
        assert sent["tool_name"] == "continuum_apply"
        assert sent["args"] == {"k": 1}
        ws.feed(
            {
                "type": "client_tool_result",
                "execution_id": "c1",
                "success": True,
                "result": {"ok": 1},
            },
        )
        result = await asyncio.wait_for(task, timeout=1.0)
        assert result is not None and result["success"] is True
    finally:
        await ch.aclose()


async def test_unknown_kind_raises() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        with pytest.raises(ValueError, match="Unknown interaction kind"):
            await ch.request("nope", {}, execution_id="x", timeout_s=1.0)
    finally:
        await ch.aclose()


async def test_non_json_frame_discarded() -> None:
    ws = FakeWebSocket()
    ch = WebSocketInteractionChannel(ws)  # type: ignore[arg-type]
    ch.start()
    try:
        ws.feed_raw("not-json{{")
        ws.feed({"type": "user_message", "content": "ok"})
        msg = await asyncio.wait_for(ch.next_user_message(), timeout=1.0)
        assert msg is not None and msg["content"] == "ok"
    finally:
        await ch.aclose()


# ---------------------------------------------------------------------------
# ScriptedInteractionChannel
# ---------------------------------------------------------------------------


async def test_scripted_returns_queued_responses_then_none() -> None:
    ch = ScriptedInteractionChannel(
        [{"type": "tool_confirmation_response", "approved": True}],
    )
    first = await ch.request(
        "tool_confirmation", {"tool_name": "t"}, execution_id="e1", timeout_s=1.0,
    )
    assert first is not None and first["approved"] is True
    # Exhausted → None (timeout-equivalent).
    second = await ch.request(
        "tool_confirmation", {}, execution_id="e2", timeout_s=1.0,
    )
    assert second is None
    assert [r["execution_id"] for r in ch.requests] == ["e1", "e2"]


async def test_scripted_unknown_kind_raises() -> None:
    ch = ScriptedInteractionChannel()
    with pytest.raises(ValueError, match="Unknown interaction kind"):
        await ch.request("bogus", {}, execution_id="x", timeout_s=1.0)


async def test_scripted_cancel_and_connection_flags() -> None:
    ch = ScriptedInteractionChannel(is_connected=False)
    assert ch.connected is False
    ch.connected = True
    assert ch.connected is True
    assert ch.cancelled is False
    ch.cancelled = True
    assert ch.cancelled is True


async def test_scripted_user_message_queue() -> None:
    ch = ScriptedInteractionChannel()
    ch.feed_user_message({"type": "user_message", "content": "hey"})
    msg = await asyncio.wait_for(ch.next_user_message(), timeout=1.0)
    assert msg is not None and msg["content"] == "hey"
