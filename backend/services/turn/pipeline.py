"""AL\\CE — Composable tool-call middleware pipeline (Fase 2, foundation C).

The turn engine used to gate every tool-call with a ladder of inline ``if``
blocks (dedup → forbidden → confirmation → client-exec → execute). Each new
capability meant another branch, which is exactly what made the loop a
god-function. This module extracts that ladder into a **chain of small,
independently-testable middlewares**:

1. :class:`DedupMiddleware`        — collapse identical server calls.
2. :class:`PermissionMiddleware`   — forbidden risk + by-construction scope
   confinement (delegated to :class:`~backend.services.permission_service.PermissionService`).
3. :class:`ConfirmationMiddleware` — user confirmation round-trip (channel).
4. :class:`InteractionMiddleware`  — greenlight bookkeeping + client-executed /
   user-interaction tools (channel; never ``execute_tool``).
5. :class:`ExecuteMiddleware`      — server execution via ``tool_registry``.

**Execution model (behaviour-preserving).** The engine keeps its two-phase
shape: a *sequential gate* (middlewares 1–4, via :meth:`ToolPipeline.gate`)
resolves each call to either a terminal outcome (deduped / forbidden /
rejected / client-executed) or a deferral to server execution; deferred calls
then run **in parallel** through :meth:`ToolPipeline.execute` (middleware 5).
The Interaction|Execute split is exactly the old gate-loop | parallel-batch
split, so frame ordering and concurrency are unchanged.

Middlewares **decide and round-trip**; the engine still owns all DB
persistence, audit rows and artifact handling (it maps the returned
:class:`ToolOutcome` back to messages / sink frames).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from fastapi import WebSocketDisconnect
from loguru import logger

from backend.core.plugin_models import ExecutionContext, ToolDefinition, ToolResult
from backend.core.tool_progress import current_progress_emitter
from backend.services.permission_service import PermissionOutcome, PermissionService
from backend.services.turn.channel import InteractionChannel
from backend.services.turn.sink import WSEventSink

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class Disposition(StrEnum):
    """How a tool-call was resolved by the pipeline."""

    EXECUTE = "execute"
    """Gate terminal: a server tool that passed every gate and should now be
    executed in the engine's parallel batch (via :meth:`ToolPipeline.execute`)."""
    EXECUTED = "executed"
    """:class:`ExecuteMiddleware` ran the tool server-side."""
    CLIENT_EXECUTED = "client_executed"
    """Delegated to the connected client and a result came back (or an error)."""
    DEDUPED = "deduped"
    """Skipped as a duplicate of an earlier identical server call."""
    FORBIDDEN = "forbidden"
    """Blocked by risk policy (``risk_level="forbidden"``)."""
    REJECTED = "rejected"
    """User declined / timed out / cancelled the confirmation."""
    SCOPE_DENIED = "scope_denied"
    """A path argument fell outside the conversation workspace scope. Inert
    until Fase 6 wires a scope (no scope ⇒ never produced)."""


@dataclass(frozen=True, slots=True)
class AuditDecision:
    """A confirmation / forbidden decision the engine must persist as audit."""

    approved: bool
    reason: str | None
    risk_level: str


@dataclass(slots=True)
class ToolCall:
    """A single LLM tool-call flowing through the pipeline.

    Mutable: middlewares annotate it (``audit_decision``) as it passes.
    """

    tc_id: str
    tool_name: str
    args: dict[str, Any]
    tool_def: ToolDefinition | None
    exec_id: str
    conversation_id: str
    context: ExecutionContext
    dedup_key: str
    is_client: bool
    audit_decision: AuditDecision | None = None


@dataclass(slots=True)
class ToolOutcome:
    """The pipeline's verdict for one :class:`ToolCall`."""

    call: ToolCall
    disposition: Disposition
    result: ToolResult | None = None
    reason: str | None = None


NextHandler = Callable[[ToolCall], Awaitable[ToolOutcome]]


class ToolMiddleware(Protocol):
    """One stage of the tool-call pipeline.

    ``handle`` either short-circuits with a terminal :class:`ToolOutcome` or
    delegates to ``nxt(call)`` to continue down the chain.
    """

    async def handle(self, call: ToolCall, nxt: NextHandler) -> ToolOutcome:
        """Process *call*, optionally delegating to ``nxt``."""
        ...


# ---------------------------------------------------------------------------
# Middlewares
# ---------------------------------------------------------------------------


class DedupMiddleware:
    """Collapse identical *server* tool-calls seen earlier in the turn.

    Client-executed *and* user-interaction tools are never deduplicated:
    re-listing/re-reading live UI state after a mutation is legitimate, and
    re-asking the human a question is too. ``seen`` is owned by the engine
    (loop-level, across iterations) and is only *written* once a call is
    greenlit (see :class:`InteractionMiddleware`), so a call the user merely
    rejected once can be retried later.
    """

    def __init__(self, seen: set[str]) -> None:
        self._seen = seen

    async def handle(self, call: ToolCall, nxt: NextHandler) -> ToolOutcome:
        _interactive = call.tool_def is not None and call.tool_def.user_interaction
        if not call.is_client and not _interactive and call.dedup_key in self._seen:
            logger.warning(
                "Dedup: skipping duplicate tool call {}(…)", call.tool_name,
            )
            return ToolOutcome(call, Disposition.DEDUPED)
        return await nxt(call)


class PermissionMiddleware:
    """Enforce risk policy + by-construction scope confinement.

    Delegates the actual decision to the central
    :class:`~backend.services.permission_service.PermissionService`. A
    forbidden tool is blocked; an out-of-scope path is denied. (In Fase 2 no
    scope is configured, so only the forbidden branch can fire — no new
    denials, behaviour preserved.)
    """

    def __init__(self, permission_service: PermissionService) -> None:
        self._permission = permission_service

    async def handle(self, call: ToolCall, nxt: NextHandler) -> ToolOutcome:
        decision = self._permission.evaluate(
            tool_name=call.tool_name,
            args=call.args,
            tool_def=call.tool_def,
            conversation_id=call.conversation_id,
        )
        if decision.allowed:
            return await nxt(call)

        risk_level = call.tool_def.risk_level if call.tool_def else "forbidden"
        if decision.outcome is PermissionOutcome.DENY_FORBIDDEN:
            logger.warning(
                "Blocked FORBIDDEN tool '{}' (exec_id={})",
                call.tool_name, call.exec_id,
            )
            call.audit_decision = AuditDecision(
                approved=False, reason="forbidden_tool", risk_level=risk_level,
            )
            return ToolOutcome(call, Disposition.FORBIDDEN)

        # DENY_SCOPE (inert until Fase 6).
        logger.warning(
            "Blocked out-of-scope tool '{}' (exec_id={}): {}",
            call.tool_name, call.exec_id, decision.reason,
        )
        return ToolOutcome(
            call, Disposition.SCOPE_DENIED, reason=decision.reason,
        )


class ConfirmationMiddleware:
    """Gate confirmation-requiring tools behind a user round-trip.

    Mirrors the legacy behaviour exactly: a tool opts in via
    ``requires_confirmation``; when the runtime toggle
    ``permissions.confirmations_enabled`` is on, the user is asked over the
    :class:`~backend.services.turn.channel.InteractionChannel`; when off, the
    call is auto-approved. Either way an audit decision is recorded for the
    engine to persist. A rejection short-circuits.
    """

    def __init__(
        self,
        *,
        channel: InteractionChannel,
        permission_service: PermissionService,
        confirmations_enabled: bool,
        confirmation_timeout_s: int,
        reasoning: str,
        cancel_event: asyncio.Event | None,
    ) -> None:
        self._channel = channel
        self._permission = permission_service
        self._confirmations_enabled = confirmations_enabled
        self._timeout_s = confirmation_timeout_s
        self._reasoning = reasoning
        self._cancel_event = cancel_event

    async def handle(self, call: ToolCall, nxt: NextHandler) -> ToolOutcome:
        td = call.tool_def
        if not self._permission.requires_confirmation(td):
            return await nxt(call)
        assert td is not None  # requires_confirmation is False for None

        if self._confirmations_enabled:
            approved = await _request_confirmation(
                self._channel, call.tool_name, call.args, call.exec_id,
                self._timeout_s,
                risk_level=td.risk_level,
                description=td.description,
                reasoning=self._reasoning,
                cancel_event=self._cancel_event,
            )
        else:
            logger.info(
                "Confirmations disabled — auto-approving '{}' (exec_id={})",
                call.tool_name, call.exec_id,
            )
            approved = True

        call.audit_decision = AuditDecision(
            approved=approved,
            reason=None if approved else "user_rejected",
            risk_level=td.risk_level,
        )
        if not approved:
            return ToolOutcome(call, Disposition.REJECTED)
        return await nxt(call)


class InteractionMiddleware:
    """Greenlight bookkeeping + client-executed / user-interaction dispatch.

    This is the last gate stage, reached only by calls that cleared dedup,
    permission and confirmation. It emits ``tool_execution_start`` and marks
    the call ``seen`` (in that order, matching the legacy gate loop) for every
    greenlit call — server *and* client — then:

    * **client-executed** tools are delegated to the connected client over the
      :class:`~backend.services.turn.channel.InteractionChannel` (never
      ``execute_tool``) and resolve to :attr:`Disposition.CLIENT_EXECUTED`;
    * **user-interaction** tools (``ask_user``) round-trip the human over the
      same channel and likewise resolve to :attr:`Disposition.CLIENT_EXECUTED`,
      so the answer is persisted and fed back to the LLM exactly like a
      client-tool result;
    * **server** tools fall through to ``nxt`` — in :meth:`ToolPipeline.gate`
      that terminal returns :attr:`Disposition.EXECUTE`, deferring them to the
      engine's parallel execution batch.
    """

    def __init__(
        self,
        *,
        sink: WSEventSink,
        channel: InteractionChannel,
        seen: set[str],
        tool_exec_timeout: float,
        cancel_event: asyncio.Event | None,
    ) -> None:
        self._sink = sink
        self._channel = channel
        self._seen = seen
        self._tool_exec_timeout = tool_exec_timeout
        self._cancel_event = cancel_event

    async def handle(self, call: ToolCall, nxt: NextHandler) -> ToolOutcome:
        await self._sink.send({
            "type": "tool_execution_start",
            "tool_name": call.tool_name,
            "execution_id": call.exec_id,
        })
        # Mark seen ONLY now that the call cleared every rejection gate, so a
        # previously-rejected call can still be retried in a later iteration.
        self._seen.add(call.dedup_key)

        td = call.tool_def
        if td is not None and td.client_execution:
            result = await _execute_client_tool(
                self._channel, call.tool_name, call.args, call.exec_id,
                self._tool_exec_timeout, self._cancel_event,
            )
            return ToolOutcome(call, Disposition.CLIENT_EXECUTED, result=result)

        if td is not None and td.user_interaction:
            result = await _execute_user_interaction(
                self._channel, call.tool_name, call.args, call.exec_id,
                self._tool_exec_timeout, self._cancel_event,
            )
            # Reuse CLIENT_EXECUTED on purpose: the engine's
            # _persist_gate_outcome routes it to _persist_client_tool_result
            # (DB tool message + tool_execution_done frame) — exactly how the
            # user's answer should be persisted and fed back to the LLM.
            return ToolOutcome(call, Disposition.CLIENT_EXECUTED, result=result)

        return await nxt(call)


class ExecuteMiddleware:
    """Run a server-side tool via the registry (the terminal stage).

    Binds a progress emitter to ``current_progress_emitter`` so long-running
    tools can stream ``tool_progress`` frames, then calls ``execute_tool``.
    Exceptions propagate so the engine's batch handler can report them per
    future (matching the legacy ``_exec_one``).
    """

    def __init__(self, *, tool_registry: Any, sink: WSEventSink) -> None:
        self._registry = tool_registry
        self._sink = sink

    async def handle(self, call: ToolCall, nxt: NextHandler) -> ToolOutcome:
        async def _emit(progress: dict[str, Any]) -> None:
            await self._sink.send({
                "type": "tool_progress",
                "tool_name": call.tool_name,
                "execution_id": call.exec_id,
                **progress,
            })

        token = current_progress_emitter.set(_emit)
        try:
            result = await self._registry.execute_tool(
                call.tool_name, call.args, call.context,
            )
        finally:
            current_progress_emitter.reset(token)
        return ToolOutcome(call, Disposition.EXECUTED, result=result)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


async def _gate_terminal(call: ToolCall) -> ToolOutcome:
    """Terminal for the gate chain: a server tool that passed every gate."""
    return ToolOutcome(call, Disposition.EXECUTE)


async def _execute_terminal(call: ToolCall) -> ToolOutcome:  # pragma: no cover
    """Terminal after :class:`ExecuteMiddleware` — never reached."""
    raise RuntimeError("ExecuteMiddleware must be terminal")


async def _run_chain(
    middlewares: Sequence[ToolMiddleware],
    index: int,
    call: ToolCall,
    terminal: NextHandler,
) -> ToolOutcome:
    """Recursively invoke ``middlewares[index:]`` then ``terminal``."""
    if index >= len(middlewares):
        return await terminal(call)

    async def _nxt(c: ToolCall) -> ToolOutcome:
        return await _run_chain(middlewares, index + 1, c, terminal)

    return await middlewares[index].handle(call, _nxt)


class ToolPipeline:
    """Two-phase composable pipeline over the tool-call middlewares.

    :meth:`gate` runs the sequential gate chain (dedup → permission →
    confirmation → interaction); :meth:`execute` runs the parallel execution
    stage. Splitting them lets the engine preserve its
    sequential-gate / parallel-execute concurrency model.
    """

    def __init__(
        self,
        gate_middlewares: Sequence[ToolMiddleware],
        execute_middleware: ToolMiddleware,
    ) -> None:
        self._gate_chain = list(gate_middlewares)
        self._execute_middleware = execute_middleware

    async def gate(self, call: ToolCall) -> ToolOutcome:
        """Run the gate chain. Returns a terminal outcome or
        :attr:`Disposition.EXECUTE` (defer to :meth:`execute`)."""
        return await _run_chain(self._gate_chain, 0, call, _gate_terminal)

    async def execute(self, call: ToolCall) -> ToolOutcome:
        """Run the server-execution stage for a deferred call."""
        return await self._execute_middleware.handle(call, _execute_terminal)


# ---------------------------------------------------------------------------
# Channel round-trips (module-level so tests can patch them)
# ---------------------------------------------------------------------------


async def _request_confirmation(
    channel: InteractionChannel,
    tool_name: str,
    args: dict[str, Any],
    execution_id: str,
    timeout_s: int,
    risk_level: str = "medium",
    description: str = "",
    reasoning: str = "",
    cancel_event: asyncio.Event | None = None,
) -> bool:
    """Send a confirmation request and wait for the user's response.

    Issues a ``tool_confirmation`` round-trip on the
    :class:`~backend.services.turn.channel.InteractionChannel` and blocks
    until the correlated response arrives or *timeout_s* elapses.

    Returns:
        ``True`` if the user approved, ``False`` on rejection, timeout,
        cancellation or disconnect.
    """
    msg = await channel.request(
        "tool_confirmation",
        {
            "tool_name": tool_name,
            "args": args,
            "risk_level": risk_level,
            "description": description,
            "reasoning": reasoning,
        },
        execution_id=execution_id,
        timeout_s=timeout_s,
        cancel_event=cancel_event,
    )
    if msg is None:
        logger.debug(
            "Confirmation not granted for tool '{}' (exec_id={})",
            tool_name, execution_id,
        )
        return False
    return bool(msg.get("approved", False))


async def _execute_client_tool(
    channel: InteractionChannel,
    tool_name: str,
    args: dict[str, Any],
    execution_id: str,
    timeout_s: float,
    cancel_event: asyncio.Event | None = None,
) -> ToolResult:
    """Delegate a tool's execution to the connected client and await its result.

    Issues a ``client_tool_call`` round-trip on the
    :class:`~backend.services.turn.channel.InteractionChannel` and blocks
    until the correlated ``client_tool_result`` arrives. Used for tools
    flagged ``ToolDefinition.client_execution`` — operations that must run
    against live client UI state (e.g. the open Continuum editor).

    Returns:
        A :class:`ToolResult` carrying the client-supplied payload, or an
        error result on timeout / cancellation.

    Raises:
        WebSocketDisconnect: If the socket dropped while awaiting the reply.
    """
    msg = await channel.request(
        "client_tool_call",
        {"tool_name": tool_name, "args": args},
        execution_id=execution_id,
        timeout_s=timeout_s,
        cancel_event=cancel_event,
    )

    if msg is None:
        # Disambiguate the None outcome (disconnect wins over cancel, since a
        # disconnect also trips the cancel signal).
        if not channel.connected:
            logger.warning(
                "WebSocket disconnected during client tool '{}' (exec_id={})",
                tool_name, execution_id,
            )
            raise WebSocketDisconnect(code=1006)
        if channel.cancelled:
            return ToolResult.error("Client tool cancelled by user.")
        logger.warning(
            "Client tool '{}' timed out after {}s (exec_id={})",
            tool_name, timeout_s, execution_id,
        )
        return ToolResult.error(
            f"Client tool '{tool_name}' timed out — is a Continuum note open?",
        )

    if msg.get("success", False):
        payload = msg.get("result")
        content = (
            payload
            if isinstance(payload, (str, dict, list))
            else str(payload)
        )
        return ToolResult.ok(
            content if content is not None else "OK",
            content_type="application/json"
            if isinstance(payload, (dict, list))
            else "text/plain",
        )
    return ToolResult.error(
        str(msg.get("error") or "Client tool reported a failure."),
    )


async def _execute_user_interaction(
    channel: InteractionChannel,
    tool_name: str,
    args: dict[str, Any],
    execution_id: str,
    timeout_s: float,
    cancel_event: asyncio.Event | None = None,
) -> ToolResult:
    """Ask the human a question and return their answer as a tool result.

    Issues an ``ask_user`` round-trip on the InteractionChannel (emitting an
    ``ask_user_required`` frame) and blocks until the correlated
    ``ask_user_response`` arrives. Used for tools flagged
    ``ToolDefinition.user_interaction`` (the ``ask_user`` meta-tool). The
    answer text becomes the tool result fed back into the LLM loop.

    Returns:
        A successful :class:`ToolResult` carrying the user's answer, or an
        error result on cancellation / timeout.

    Raises:
        WebSocketDisconnect: If the socket dropped while awaiting the answer.
    """
    question = str(args.get("question", "")).strip()
    payload: dict[str, Any] = {"question": question}
    options = args.get("options")
    if isinstance(options, list):
        payload["options"] = [str(o) for o in options]

    msg = await channel.request(
        "ask_user", payload,
        execution_id=execution_id, timeout_s=timeout_s, cancel_event=cancel_event,
    )
    if msg is None:
        # Same disambiguation as client tools: disconnect > cancel > timeout.
        if not channel.connected:
            logger.warning(
                "WebSocket disconnected during ask_user (exec_id={})", execution_id,
            )
            raise WebSocketDisconnect(code=1006)
        if channel.cancelled:
            return ToolResult.error("Question cancelled by the user.")
        logger.warning(
            "ask_user timed out after {}s (exec_id={})", timeout_s, execution_id,
        )
        return ToolResult.error(f"No answer received (timed out after {timeout_s}s).")

    answer = msg.get("answer")
    return ToolResult.ok(
        str(answer) if answer is not None else "",
        content_type="text/plain",
    )
