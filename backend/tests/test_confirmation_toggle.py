"""Tests for tier-authoritative confirmations in the turn engine.

The permission TIER is authoritative: a ``NEEDS_CONFIRMATION`` verdict always
prompts, regardless of the legacy global ``permissions.confirmations_enabled``
flag. ``AUTOPILOT`` is the explicit "never ask" tier (it yields ALLOW), and
``FORBIDDEN`` tools stay blocked in every tier. The legacy flag now only governs
the no-gate-decision fallback used by isolated unit tests.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.turn.tool_loop import run_tool_loop
from backend.services.turn.pipeline import ConfirmationOutcome
from backend.services.permission_mode_service import PermissionMode, PermissionModeService
from backend.core.plugin_models import ToolDefinition, ToolResult
from backend.db.models import ToolConfirmationAudit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_call(name: str, args: dict | None = None) -> dict:
    """Build a minimal tool_call dict as the LLM would produce."""
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args or {}),
        },
    }


def _make_tool_def(
    name: str,
    *,
    requires_confirmation: bool = False,
    risk_level: str = "safe",
) -> ToolDefinition:
    """Build a ToolDefinition with the given confirmation/risk settings."""
    return ToolDefinition(
        name=name,
        description=f"Test tool {name}",
        requires_confirmation=requires_confirmation,
        risk_level=risk_level,
    )


def _build_mocks(*, confirmations_enabled: bool = True, mode: str = "strict"):
    """Return (ctx, ws, session, llm) mocks wired for run_tool_loop.

    ``mode`` selects the conversation's permission tier. A
    ``MagicMock(spec=PermissionModeService)`` passes the ``isinstance`` check the
    tool loop uses, so the gate consults this mode for every tool-call.
    """
    # --- Config ---
    permissions_cfg = MagicMock()
    permissions_cfg.confirmations_enabled = confirmations_enabled

    llm_cfg = MagicMock()
    llm_cfg.tool_execution_timeout = 120.0
    llm_cfg.context_compression_enabled = False

    cfg = MagicMock()
    cfg.permissions = permissions_cfg
    cfg.llm = llm_cfg

    # --- Tool registry ---
    tool_registry = MagicMock()
    tool_registry.execute_tool = AsyncMock(
        return_value=ToolResult(success=True, content="ok"),
    )
    tool_registry.get_available_tools = AsyncMock(return_value=[])

    # --- AppContext ---
    ctx = MagicMock()
    ctx.config = cfg
    ctx.tool_registry = tool_registry
    ctx.event_bus = MagicMock()
    ctx.event_bus.emit = AsyncMock()

    # --- WebSocket ---
    ws = AsyncMock()
    ws.send = AsyncMock()

    # --- DB session ---
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    # exec() must return an iterable of Message-like objects for the re-query
    result_mock = MagicMock()
    result_mock.all.return_value = []
    session.exec = AsyncMock(return_value=result_mock)

    # --- LLM (returns no further tool calls) ---
    llm = MagicMock()

    async def _final_answer(*_a, **_kw):
        yield {"type": "token", "content": "Done."}
        yield {"type": "done", "content": ""}

    llm.chat = MagicMock(side_effect=_final_answer)
    llm.build_continuation_messages = MagicMock(return_value=[])

    # --- Permission-mode service (tier the gate consults per tool-call) ---
    # A spec'd MagicMock satisfies the tool loop's
    # ``isinstance(ctx.permission_mode_service, PermissionModeService)`` check.
    mode_service = MagicMock(spec=PermissionModeService)
    mode_service.get_mode.return_value = PermissionMode(mode)
    ctx.permission_mode_service = mode_service

    return ctx, ws, session, llm


def _get_audit_entries(session_mock: MagicMock) -> list[ToolConfirmationAudit]:
    """Extract ToolConfirmationAudit objects added to the session."""
    return [
        call.args[0]
        for call in session_mock.add.call_args_list
        if isinstance(call.args[0], ToolConfirmationAudit)
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmations_enabled_requests_approval():
    """With confirmations_enabled=True, dangerous tools trigger _request_confirmation."""
    ctx, ws, session, llm = _build_mocks(confirmations_enabled=True)
    ctx.tool_registry.get_tool_definition.return_value = _make_tool_def(
        "dangerous_tool", requires_confirmation=True, risk_level="dangerous",
    )

    tool_calls = [_make_tool_call("dangerous_tool")]
    conv_id = uuid.uuid4()

    with patch(
        "backend.services.turn.pipeline._request_confirmation",
        new_callable=AsyncMock,
        return_value=ConfirmationOutcome(approved=True),
    ) as mock_confirm:
        await run_tool_loop(
            channel=ws,
            sink=ws,
            ctx=ctx,
            session=session,
            conv_id=conv_id,
            llm=llm,
            tool_calls_from_llm=tool_calls,
            full_content="",
            thinking_content="",
            max_iterations=1,
            confirmation_timeout_s=30,
            client_ip="127.0.0.1",

        )

        mock_confirm.assert_called_once()


@pytest.mark.asyncio
async def test_strict_tier_always_prompts_even_with_global_flag_off():
    """Tier authoritative: a NEEDS_CONFIRMATION verdict prompts regardless of the legacy flag."""
    ctx, ws, session, llm = _build_mocks(confirmations_enabled=False, mode="strict")
    ctx.tool_registry.get_tool_definition.return_value = _make_tool_def(
        "dangerous_tool", requires_confirmation=True, risk_level="dangerous",
    )
    tool_calls = [_make_tool_call("dangerous_tool")]
    conv_id = uuid.uuid4()
    with patch(
        "backend.services.turn.pipeline._request_confirmation",
        new_callable=AsyncMock, return_value=ConfirmationOutcome(approved=True),
    ) as mock_confirm:
        await run_tool_loop(
            channel=ws, sink=ws, ctx=ctx, session=session, conv_id=conv_id, llm=llm,
            tool_calls_from_llm=tool_calls, full_content="", thinking_content="",
            max_iterations=1, confirmation_timeout_s=30, client_ip="127.0.0.1",
        )
        mock_confirm.assert_called_once()  # NO LONGER silently auto-approved


@pytest.mark.asyncio
async def test_autopilot_tier_does_not_prompt():
    """AUTOPILOT is the explicit 'never ask' tier."""
    ctx, ws, session, llm = _build_mocks(confirmations_enabled=True, mode="autopilot")
    ctx.tool_registry.get_tool_definition.return_value = _make_tool_def(
        "dangerous_tool", requires_confirmation=True, risk_level="dangerous",
    )
    tool_calls = [_make_tool_call("dangerous_tool")]
    conv_id = uuid.uuid4()
    with patch(
        "backend.services.turn.pipeline._request_confirmation", new_callable=AsyncMock,
    ) as mock_confirm:
        await run_tool_loop(
            channel=ws, sink=ws, ctx=ctx, session=session, conv_id=conv_id, llm=llm,
            tool_calls_from_llm=tool_calls, full_content="", thinking_content="",
            max_iterations=1, confirmation_timeout_s=30, client_ip="127.0.0.1",
        )
        mock_confirm.assert_not_called()
    ctx.tool_registry.execute_tool.assert_called_once()


@pytest.mark.asyncio
async def test_forbidden_blocked_even_when_confirmations_disabled():
    """Forbidden tools are always blocked, regardless of confirmations_enabled."""
    ctx, ws, session, llm = _build_mocks(confirmations_enabled=False)
    ctx.tool_registry.get_tool_definition.return_value = _make_tool_def(
        "forbidden_tool", requires_confirmation=True, risk_level="forbidden",
    )

    tool_calls = [_make_tool_call("forbidden_tool")]
    conv_id = uuid.uuid4()

    await run_tool_loop(
        channel=ws,
        sink=ws,
        ctx=ctx,
        session=session,
        conv_id=conv_id,
        llm=llm,
        tool_calls_from_llm=tool_calls,
        full_content="",
        thinking_content="",
        max_iterations=1,
        confirmation_timeout_s=30,
        client_ip="127.0.0.1",
    )

    # Tool must NOT have been executed
    ctx.tool_registry.execute_tool.assert_not_called()

    # Audit entry should record rejection
    audits = _get_audit_entries(session)
    assert len(audits) == 1
    assert audits[0].user_approved is False
    assert audits[0].risk_level == "forbidden"
    assert audits[0].rejection_reason == "forbidden_tool"


@pytest.mark.asyncio
async def test_audit_logged_when_confirmation_approved():
    """An approved confirmation writes an audit row with user_approved=True.

    Re-grounded for the tier-authoritative model: a NEEDS_CONFIRMATION tool in
    STRICT prompts even with the global flag off (it is no longer silently
    auto-approved). On approval, the audit row still records user_approved=True.
    (AUTOPILOT can't stand in here: it yields ALLOW, which never reaches the
    ConfirmationMiddleware and so writes no audit row.)
    """
    ctx, ws, session, llm = _build_mocks(confirmations_enabled=False, mode="strict")
    ctx.tool_registry.get_tool_definition.return_value = _make_tool_def(
        "medium_tool", requires_confirmation=True, risk_level="medium",
    )

    tool_calls = [_make_tool_call("medium_tool")]
    conv_id = uuid.uuid4()

    with patch(
        "backend.services.turn.pipeline._request_confirmation",
        new_callable=AsyncMock,
        return_value=ConfirmationOutcome(approved=True),
    ) as mock_confirm:
        await run_tool_loop(
            channel=ws,
            sink=ws,
            ctx=ctx,
            session=session,
            conv_id=conv_id,
            llm=llm,
            tool_calls_from_llm=tool_calls,
            full_content="",
            thinking_content="some reasoning",
            max_iterations=1,
            confirmation_timeout_s=30,
            client_ip="127.0.0.1",

        )
        mock_confirm.assert_called_once()

    audits = _get_audit_entries(session)
    assert len(audits) == 1
    assert audits[0].user_approved is True
    assert audits[0].risk_level == "medium"
    assert audits[0].tool_name == "medium_tool"
    assert audits[0].thinking_content == "some reasoning"


@pytest.mark.asyncio
async def test_safe_tool_no_confirmation_regardless_of_toggle():
    """Safe tools (requires_confirmation=False) execute without confirmation
    regardless of the toggle value."""
    for toggle in (True, False):
        ctx, ws, session, llm = _build_mocks(confirmations_enabled=toggle)
        ctx.tool_registry.get_tool_definition.return_value = _make_tool_def(
            "safe_tool", requires_confirmation=False, risk_level="safe",
        )

        tool_calls = [_make_tool_call("safe_tool")]
        conv_id = uuid.uuid4()

        with patch(
            "backend.services.turn.pipeline._request_confirmation",
            new_callable=AsyncMock,
        ) as mock_confirm:
            await run_tool_loop(
                channel=ws,
                sink=ws,
                ctx=ctx,
                session=session,
                conv_id=conv_id,
                llm=llm,
                tool_calls_from_llm=tool_calls,
                full_content="",
                thinking_content="",
                max_iterations=1,
                confirmation_timeout_s=30,
                client_ip="127.0.0.1",
    
            )

            mock_confirm.assert_not_called()

        ctx.tool_registry.execute_tool.assert_called_once()
        # No audit entry for safe tools
        audits = _get_audit_entries(session)
        assert len(audits) == 0


@pytest.mark.asyncio
async def test_confirmations_enabled_rejected_by_user():
    """When confirmations are enabled and the user rejects, the tool is NOT executed
    and an audit entry records the rejection."""
    ctx, ws, session, llm = _build_mocks(confirmations_enabled=True)
    ctx.tool_registry.get_tool_definition.return_value = _make_tool_def(
        "dangerous_tool", requires_confirmation=True, risk_level="dangerous",
    )

    tool_calls = [_make_tool_call("dangerous_tool")]
    conv_id = uuid.uuid4()

    with patch(
        "backend.services.turn.pipeline._request_confirmation",
        new_callable=AsyncMock,
        return_value=ConfirmationOutcome(approved=False),
    ):
        await run_tool_loop(
            channel=ws,
            sink=ws,
            ctx=ctx,
            session=session,
            conv_id=conv_id,
            llm=llm,
            tool_calls_from_llm=tool_calls,
            full_content="",
            thinking_content="",
            max_iterations=1,
            confirmation_timeout_s=30,
            client_ip="127.0.0.1",

        )

    ctx.tool_registry.execute_tool.assert_not_called()

    audits = _get_audit_entries(session)
    assert len(audits) == 1
    assert audits[0].user_approved is False
    assert audits[0].rejection_reason == "user_rejected"
