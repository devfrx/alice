"""AL\\CE — Tests for additive canonical ``tool.call`` / ``tool.result`` events.

Pins the behaviour wired in Task 3.2b: the turn engine emits the canonical
``tool.call`` and ``tool.result`` frames *additively* — one ``tool.call`` per
well-formed (named + JSON-parsed) tool call, and one ``tool.result`` at every
terminal site (success, failure, timeout, dedup, confirmation-rejection,
client-execution) — alongside (never replacing) the legacy
``tool_execution_start`` / ``tool_execution_done`` frames.

Every assertion here exercises :func:`run_tool_loop` through the same mocks as
``test_tool_loop`` (which mints its own ``TurnProgress`` when no
``turn_progress`` is supplied, so all canonical frames share one ``turn_id``).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.plugin_models import ToolDefinition, ToolResult

from .test_tool_loop import (
    MockToolRegistry,
    MockWebSocket,
    _ClientToolWebSocket,
    _run,
    _tc,
)

# A trivial final-answer re-query so the loop terminates after one iteration.
_FINAL: list[list[dict[str, Any]]] = [
    [{"type": "token", "content": "Done"}, {"type": "done"}],
]


def _by_type(ws: MockWebSocket, frame_type: str) -> list[dict[str, Any]]:
    """Return every recorded frame whose ``type`` equals *frame_type*."""
    return [m for m in ws.sent if m.get("type") == frame_type]


# ---------------------------------------------------------------------------
# Server tool — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_tool_emits_paired_call_and_result() -> None:
    """A normal server tool emits one tool.call + one success tool.result."""
    ws, _, _ = await _run(
        [_tc("tool_a", '{"q": "hi"}')],
        llm_responses=_FINAL,
    )

    calls = _by_type(ws, "tool.call")
    results = _by_type(ws, "tool.result")

    assert len(calls) == 1
    assert len(results) == 1

    # Same execution_id correlates the pair; same (non-empty) turn_id.
    assert calls[0]["execution_id"] == results[0]["execution_id"]
    assert calls[0]["turn_id"] == results[0]["turn_id"]
    assert calls[0]["turn_id"]  # non-empty

    # tool.call carries the tool name and round-trips the parsed args.
    assert calls[0]["tool_name"] == "tool_a"
    assert calls[0]["args"] == {"q": "hi"}

    # tool.result reports success and the same tool name.
    assert results[0]["success"] is True
    assert results[0]["tool_name"] == "tool_a"

    # Additive: the legacy frames are STILL present alongside the canonical.
    assert len(_by_type(ws, "tool_execution_start")) == 1
    assert len(_by_type(ws, "tool_execution_done")) == 1


# ---------------------------------------------------------------------------
# Server tool — failure path (registry raises)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failing_server_tool_emits_failed_result() -> None:
    """A tool whose registry execution raises yields a failed tool.result."""

    async def _fail(name: str, args: dict[str, Any], ctx: object) -> ToolResult:
        raise RuntimeError("tool crashed")

    ws, _, _ = await _run(
        [_tc("bad_tool")],
        registry=MockToolRegistry(execute_fn=_fail),
        llm_responses=_FINAL,
    )

    calls = _by_type(ws, "tool.call")
    results = _by_type(ws, "tool.result")

    assert len(calls) == 1
    assert len(results) == 1
    assert results[0]["success"] is False
    # The failed result stays correlated with its originating call.
    assert calls[0]["execution_id"] == results[0]["execution_id"]

    # Additive: the legacy failed done frame is still emitted too.
    legacy = [
        m for m in _by_type(ws, "tool_execution_done")
        if m.get("success") is False
    ]
    assert len(legacy) == 1


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_call_emits_two_calls_and_dedup_result() -> None:
    """Two identical calls → two tool.call frames; the dedup yields a result."""
    ws, _, reg = await _run(
        [_tc("tool_a"), _tc("tool_a")],
        llm_responses=_FINAL,
    )

    calls = _by_type(ws, "tool.call")
    results = _by_type(ws, "tool.result")

    # Both well-formed calls are announced; only one actually executes.
    assert len(calls) == 2
    assert len(reg.execute_calls) == 1

    # Both terminal sites close their timeline entry: the executed one and
    # the deduped one (canonical-only — there is no legacy dedup frame).
    assert len(results) == 2
    dedup = [r for r in results if "Duplicate" in r["result"]]
    assert len(dedup) == 1
    assert dedup[0]["success"] is True

    # Pairing integrity: every result correlates with an announced call.
    call_ids = {c["execution_id"] for c in calls}
    result_ids = {r["execution_id"] for r in results}
    assert result_ids <= call_ids

    # All canonical frames share one turn_id.
    turn_ids = {m["turn_id"] for m in calls + results}
    assert len(turn_ids) == 1


# ---------------------------------------------------------------------------
# Client-executed tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_tool_emits_paired_call_and_result() -> None:
    """A client-executed tool emits one tool.call + one success tool.result."""
    client_def = ToolDefinition(
        name="continuum_list_blocks",
        description="List blocks",
        client_execution=True,
    )
    reg = MockToolRegistry(definitions={"continuum_list_blocks": client_def})
    ws = _ClientToolWebSocket(result={"count": 2, "blocks": []})

    # ``_run`` returns the very ``ws``/``reg`` it was handed, so keep the
    # original bindings (preserves the ``_ClientToolWebSocket`` static type).
    await _run(
        [_tc("continuum_list_blocks")],
        registry=reg,
        ws=ws,
        llm_responses=[[{"type": "token", "content": "Listed"}, {"type": "done"}]],
    )

    calls = _by_type(ws, "tool.call")
    results = _by_type(ws, "tool.result")

    assert len(calls) == 1
    assert len(results) == 1
    assert results[0]["success"] is True
    assert calls[0]["execution_id"] == results[0]["execution_id"]
    assert calls[0]["tool_name"] == "continuum_list_blocks"

    # The server must NOT run a client tool locally.
    assert reg.execute_calls == []

    # Additive: the legacy client done frame is still present (matches the
    # existing test_tool_loop client round-trip assertion).
    legacy_done = [
        m for m in _by_type(ws, "tool_execution_done")
        if m.get("tool_name") == "continuum_list_blocks"
    ]
    assert len(legacy_done) == 1
    assert legacy_done[0]["success"] is True


# ---------------------------------------------------------------------------
# Confirmation-rejected dangerous tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmation_rejected_emits_failed_result() -> None:
    """A rejected (timed-out) confirmation yields a failed tool.result."""
    confirmable = ToolDefinition(
        name="danger",
        description="Dangerous op",
        requires_confirmation=True,
    )
    reg = MockToolRegistry(definitions={"danger": confirmable})
    # auto_confirm=None → the confirmation round-trip times out → rejected.
    ws = MockWebSocket(auto_confirm=None)

    ws, _, reg = await _run(
        [_tc("danger")],
        registry=reg,
        ws=ws,
        llm_responses=[[{"type": "token", "content": "Rejected"}, {"type": "done"}]],
    )

    calls = _by_type(ws, "tool.call")
    results = _by_type(ws, "tool.result")

    # A rejected dangerous tool is still announced, then closed as a failure.
    assert len(calls) == 1
    assert len(results) == 1
    assert results[0]["success"] is False
    assert calls[0]["execution_id"] == results[0]["execution_id"]

    # The tool never executed, and the legacy failed done frame remains.
    assert reg.execute_calls == []
    assert len(_by_type(ws, "tool_confirmation_required")) == 1
    legacy = [
        m for m in _by_type(ws, "tool_execution_done")
        if m.get("success") is False
    ]
    assert len(legacy) == 1
