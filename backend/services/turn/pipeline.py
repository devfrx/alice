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
from backend.services.permission_mode_service import PermissionMode
from backend.services.permission_rules import PermissionRuleService, RuleEffect
from backend.services.permission_service import (
    GateAction,
    GateDecision,
    PermissionOutcome,
    PermissionService,
)
from backend.services.turn import events
from backend.services.turn.channel import InteractionChannel
from backend.services.turn.sink import WSEventSink

# Permission-mode provider: maps a conversation id to its current tier. Read
# synchronously per tool-call by ``PermissionMiddleware`` so a mid-turn change
# takes effect on the next gate.
ModeProvider = Callable[[str], PermissionMode]

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
    """A path argument fell outside the conversation workspace scope."""
    NO_SCOPE_DENIED = "no_scope_denied"
    """A filesystem tool was called with no workspace scope set (Fase 7).
    Holds in every tier, autopilot included — scope is the workspace boundary."""
    PLAN_DENIED = "plan_denied"
    """A write / process-exec tool was blocked by the read-only ``plan`` tier."""
    RULE_DENIED = "rule_denied"
    """Blocked by a persistent ``deny`` permission rule (Fase 7)."""


# Maps a denying permission outcome to its terminal gate disposition. The
# forbidden outcome is handled separately because it also writes an audit row.
_DENY_DISPOSITION: dict[PermissionOutcome, Disposition] = {
    PermissionOutcome.DENY_SCOPE: Disposition.SCOPE_DENIED,
    PermissionOutcome.DENY_NO_SCOPE: Disposition.NO_SCOPE_DENIED,
    PermissionOutcome.DENY_PLAN_MODE: Disposition.PLAN_DENIED,
    PermissionOutcome.DENY_RULE: Disposition.RULE_DENIED,
}


@dataclass(frozen=True, slots=True)
class AuditDecision:
    """A confirmation / forbidden decision the engine must persist as audit."""

    approved: bool
    reason: str | None
    risk_level: str


@dataclass(frozen=True, slots=True)
class ConfirmationOutcome:
    """The result of a confirmation round-trip: approval + a remember choice.

    Attributes:
        approved: ``True`` when the user (or auto-approval) greenlit the call.
        remember: ``"none"`` (ask again next time), ``"session"`` (grant for the
            rest of this conversation), or ``"persistent"`` (write a durable
            permission rule).
    """

    approved: bool
    remember: str = "none"


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
    gate_decision: GateDecision | None = None
    turn_id: str = ""


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
    """Enforce the permission tier: risk policy, scope confinement, rules.

    Delegates the actual verdict to the central
    :class:`~backend.services.permission_service.PermissionService` via
    :meth:`PermissionService.decide`, passing the conversation's current tier
    (read synchronously from *mode_provider* so a mid-turn change is honoured on
    the next gate). The three-valued verdict is stashed on the call as
    ``gate_decision`` so :class:`ConfirmationMiddleware` need not recompute it: a
    DENY short-circuits here (mapped to the matching disposition + an audit row
    for the forbidden case), while ALLOW / NEEDS_CONFIRMATION fall through.

    *mode_provider* defaults to a constant ``strict`` provider, so an isolated
    construction (``PermissionMiddleware(svc)``) reproduces the pre-Fase-7
    behaviour exactly.
    """

    def __init__(
        self,
        permission_service: PermissionService,
        mode_provider: ModeProvider | None = None,
    ) -> None:
        self._permission = permission_service
        self._mode_provider = mode_provider

    async def handle(self, call: ToolCall, nxt: NextHandler) -> ToolOutcome:
        mode = (
            self._mode_provider(call.conversation_id)
            if self._mode_provider is not None
            else PermissionMode.STRICT
        )
        decision = self._permission.decide(
            tool_name=call.tool_name,
            args=call.args,
            tool_def=call.tool_def,
            conversation_id=call.conversation_id,
            mode=mode,
        )
        call.gate_decision = decision
        if decision.action is not GateAction.DENY:
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

        # Scope / no-scope / plan-mode / rule denials: a rejected tool message
        # plus a failed done frame (the engine maps the disposition to text).
        disposition = _DENY_DISPOSITION.get(decision.outcome, Disposition.SCOPE_DENIED)
        logger.warning(
            "Blocked tool '{}' (exec_id={}): {} ({})",
            call.tool_name, call.exec_id, decision.reason, decision.outcome.value,
        )
        return ToolOutcome(call, disposition, reason=decision.reason)


class ConfirmationMiddleware:
    """Gate confirmation-requiring tools behind a user round-trip.

    **The tier is authoritative.** When ``PermissionMiddleware`` stamped a
    ``NEEDS_CONFIRMATION`` verdict (``call.gate_decision``), the user is *always*
    asked over the :class:`~backend.services.turn.channel.InteractionChannel` —
    the legacy global ``permissions.confirmations_enabled`` toggle can no longer
    override the chosen tier. ``AUTOPILOT`` is the explicit "never ask" tier (it
    yields ALLOW, so it never reaches this middleware needing confirmation).

    The legacy flag survives only as a fallback for the *no-gate-decision* path:
    when this middleware is driven in isolation (a unit test without the upstream
    permission stage, ``gate_decision is None``), the call falls back to the
    ``requires_confirmation`` flag and the toggle then decides ask-vs-auto-approve.
    Either way an audit decision is recorded for the engine to persist, and a
    rejection short-circuits.
    """

    def __init__(
        self,
        *,
        sink: WSEventSink,
        channel: InteractionChannel,
        permission_service: PermissionService,
        confirmations_enabled: bool,
        confirmation_timeout_s: int,
        reasoning: str,
        cancel_event: asyncio.Event | None,
        rule_service: PermissionRuleService | None = None,
    ) -> None:
        self._sink = sink
        self._channel = channel
        self._permission = permission_service
        self._confirmations_enabled = confirmations_enabled
        self._timeout_s = confirmation_timeout_s
        self._reasoning = reasoning
        self._cancel_event = cancel_event
        self._rule_service = rule_service

    async def handle(self, call: ToolCall, nxt: NextHandler) -> ToolOutcome:
        td = call.tool_def
        # Gate on the tier verdict stamped by PermissionMiddleware. When the
        # gate decision is absent (a unit test driving this middleware in
        # isolation), fall back to the legacy ``requires_confirmation`` flag so
        # behaviour is preserved without the upstream stage.
        gd = call.gate_decision
        if gd is not None:
            needs = gd.action is GateAction.NEEDS_CONFIRMATION
        else:
            needs = self._permission.requires_confirmation(td)
        if not needs:
            return await nxt(call)

        # ``td`` is non-None for ``requires_confirmation`` tools; an ``ask`` rule
        # could in principle target an unknown tool, so default its metadata.
        risk_level = td.risk_level if td is not None else "medium"
        description = td.description if td is not None else ""

        # Canonical interaction frame: a confirmation round-trip is now pending
        # (covers both the channel-asked and the auto-approved paths below).
        await self._sink.send(events.interaction_requested(
            turn_id=call.turn_id,
            execution_id=call.exec_id,
            kind="tool_confirmation",
            tool_name=call.tool_name,
        ))

        # Tier authoritative: a NEEDS_CONFIRMATION verdict ALWAYS prompts. The legacy
        # global toggle only governs the no-gate-decision fallback (unit-test isolation).
        tier_mandated = gd is not None and gd.action is GateAction.NEEDS_CONFIRMATION
        if tier_mandated or self._confirmations_enabled:
            confirmation = await _request_confirmation(
                self._channel, call.tool_name, call.args, call.exec_id,
                self._timeout_s,
                risk_level=risk_level,
                description=description,
                reasoning=self._reasoning,
                cancel_event=self._cancel_event,
            )
            approved = confirmation.approved
            remember = confirmation.remember
        else:
            logger.info(
                "No tier verdict and confirmations disabled — auto-approving '{}' (exec_id={})",
                call.tool_name, call.exec_id,
            )
            approved = True
            remember = "none"

        # Canonical interaction frame: the confirmation resolved. ``approved``
        # is True for a user-approval or an auto-approval; False covers an
        # explicit rejection, a timeout, a cancel or a disconnect (all of which
        # ``_request_confirmation`` collapses to ``False``) — never mislabeled.
        await self._sink.send(events.interaction_resolved(
            turn_id=call.turn_id,
            execution_id=call.exec_id,
            kind="tool_confirmation",
            outcome="approved" if approved else "rejected",
        ))

        call.audit_decision = AuditDecision(
            approved=approved,
            reason=None if approved else "user_rejected",
            risk_level=risk_level,
        )
        await self._persist_remember(call, approved, remember)
        if not approved:
            return ToolOutcome(call, Disposition.REJECTED)
        return await nxt(call)

    async def _persist_remember(
        self, call: ToolCall, approved: bool, remember: str,
    ) -> None:
        """Apply a "don't ask again" choice (best-effort, never raises).

        ``session`` records an in-memory grant on the permission service (only
        meaningful for an approval); ``persistent`` writes a durable allow/deny
        rule when a rule service is wired.
        """
        if remember == "session" and approved:
            self._permission.grant(call.conversation_id, call.tool_name)
        elif remember == "persistent" and self._rule_service is not None:
            effect = RuleEffect.ALLOW if approved else RuleEffect.DENY
            try:
                await self._rule_service.add_rule(
                    tool_name=call.tool_name,
                    effect=effect,
                    conversation_id=call.conversation_id,
                )
            except Exception as exc:  # never let persistence break the turn
                logger.warning("Failed to persist permission rule: {}", exc)


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
            # Canonical interaction frame: delegating to the connected client.
            await self._sink.send(events.interaction_requested(
                turn_id=call.turn_id,
                execution_id=call.exec_id,
                kind="client_tool_call",
                tool_name=call.tool_name,
            ))
            result = await _execute_client_tool(
                self._channel, call.tool_name, call.args, call.exec_id,
                self._tool_exec_timeout, self._cancel_event,
            )
            # Outcome mapping. ``_execute_client_tool`` returns
            # ``ToolResult.ok(...)`` on a genuine client reply, or
            # ``ToolResult.error(...)`` on cancel / timeout / a client-reported
            # failure (a disconnect RAISES ``WebSocketDisconnect`` before this
            # point, so no resolved frame is emitted then — the socket is gone).
            # success -> "executed"; a turn cancel -> "cancelled"; anything else
            # (a timeout and a client-reported failure are indistinguishable
            # from the result alone) -> "failed". A non-success is never
            # mislabeled "executed".
            if result.success:
                outcome = "executed"
            elif self._channel.cancelled:
                outcome = "cancelled"
            else:
                outcome = "failed"
            await self._sink.send(events.interaction_resolved(
                turn_id=call.turn_id,
                execution_id=call.exec_id,
                kind="client_tool_call",
                outcome=outcome,
            ))
            return ToolOutcome(call, Disposition.CLIENT_EXECUTED, result=result)

        if td is not None and td.user_interaction:
            # Canonical interaction frame: asking the human a question.
            await self._sink.send(events.interaction_requested(
                turn_id=call.turn_id,
                execution_id=call.exec_id,
                kind="ask_user",
                tool_name=call.tool_name,
            ))
            result = await _execute_user_interaction(
                self._channel, call.tool_name, call.args, call.exec_id,
                self._tool_exec_timeout, self._cancel_event,
            )
            # Outcome mapping. ``_execute_user_interaction`` returns
            # ``ToolResult.ok(answer)`` on a real answer (or ``ok("")`` if the
            # user replied with no answer), or ``ToolResult.error(...)`` on
            # cancel / timeout (a disconnect RAISES before this point). A
            # genuine non-empty answer -> "answered"; a user cancel or an empty
            # (declined) answer -> "cancelled"; otherwise (an error result while
            # still connected, i.e. no reply in the window) -> "timeout". A
            # timeout/cancel is never mislabeled "answered".
            answer_text = result.content if isinstance(result.content, str) else ""
            if result.success:
                outcome = "answered" if answer_text.strip() else "cancelled"
            elif self._channel.cancelled:
                outcome = "cancelled"
            else:
                outcome = "timeout"
            await self._sink.send(events.interaction_resolved(
                turn_id=call.turn_id,
                execution_id=call.exec_id,
                kind="ask_user",
                outcome=outcome,
            ))
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


_REMEMBER_CHOICES: frozenset[str] = frozenset({"none", "session", "persistent"})


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
) -> ConfirmationOutcome:
    """Send a confirmation request and wait for the user's response.

    Issues a ``tool_confirmation`` round-trip on the
    :class:`~backend.services.turn.channel.InteractionChannel` and blocks
    until the correlated response arrives or *timeout_s* elapses. The request
    payload advertises ``allow_remember`` so the client can offer the
    "don't ask again" options; the response may carry a ``remember`` field
    (``none`` / ``session`` / ``persistent``).

    Returns:
        A :class:`ConfirmationOutcome`: ``approved=False`` on rejection,
        timeout, cancellation or disconnect; the ``remember`` choice (defaulting
        to ``"none"``) otherwise.
    """
    msg = await channel.request(
        "tool_confirmation",
        {
            "tool_name": tool_name,
            "args": args,
            "risk_level": risk_level,
            "description": description,
            "reasoning": reasoning,
            "allow_remember": True,
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
        return ConfirmationOutcome(approved=False)
    remember = msg.get("remember", "none")
    if remember not in _REMEMBER_CHOICES:
        remember = "none"
    return ConfirmationOutcome(
        approved=bool(msg.get("approved", False)), remember=remember,
    )


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
