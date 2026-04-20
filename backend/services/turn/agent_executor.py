"""AL\\CE — Agent turn executor (plan → act → critic strategy).

Selected by :func:`backend.services.turn.factory.create_turn_executor`
when ``ctx.config.agent.enabled`` is true and an
:class:`~backend.services.agent.AgentComponents` bundle is present on
the application context.

Architectural notes (see ``alice/agent_loop_plan.md`` §3.6 / §3.8):

*   The executor **delegates** every actual LLM turn to a wrapped
    :class:`~backend.services.turn.direct_executor.DirectTurnExecutor`.
    It never streams tokens by itself — that keeps full feature parity
    with ``run_tool_loop`` (tool dedup, confirmation, image
    persistence, per-iteration compression, etc.) for free.
*   No ``Message`` is persisted per intermediate step — the per-step
    tool messages emerge naturally from ``run_tool_loop`` inside each
    delegated ``DirectTurnExecutor.execute``.  Only the final turn
    Message is persisted by ``ws_chat::_persist_final_turn``.
*   Streaming events emitted by the inner executor are wrapped with
    ``agent_step_index`` metadata via :class:`AnnotatingSink` so the
    frontend can group token chunks per step.
*   ``AgentRun`` rows are persisted opportunistically: missing
    persistence (e.g. unit tests with ``session=None``) is *not* an
    error — the executor degrades to in-memory bookkeeping.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.services.turn.models import TurnInput, TurnResult
from backend.services.turn.sink import WSEventSink
from backend.services.turn._critic_bypass import (
    emit_critic_invoked,
    emit_warning,
)

if TYPE_CHECKING:  # pragma: no cover — typing only
    from fastapi import WebSocket

    from backend.core.config import AgentConfig
    from backend.services.agent import AgentComponents
    from backend.services.agent.models import Plan, Step, Verdict
    from backend.services.turn.direct_executor import DirectTurnExecutor


# ---------------------------------------------------------------------------
# Sink wrapper that annotates inner-step events with ``agent_step_index``.
# ---------------------------------------------------------------------------

_ANNOTATED_TYPES: frozenset[str] = frozenset(
    {
        "token",
        "thinking",
        "tool_call",
        "tool_execution_start",
        "tool_execution_done",
    }
)


class AnnotatingSink:
    """Forward events to ``inner`` adding ``agent_step_index`` to token/tool events.

    Other event shapes (``done``, ``context_info``, ``error``, ...) are
    forwarded unchanged so the frontend keeps interpreting them as
    today.  The wrapper preserves ``_ws`` so :func:`run_tool_loop`
    (which still expects a raw ``WebSocket``) keeps working.
    """

    def __init__(self, inner: WSEventSink, step_index: int) -> None:
        self._inner = inner
        self._step_index = step_index

    async def send(self, event: dict[str, Any]) -> None:
        """Forward ``event`` adding the step index when relevant."""
        if event.get("type") in _ANNOTATED_TYPES:
            event = {**event, "agent_step_index": self._step_index}
        await self._inner.send(event)

    @property
    def is_connected(self) -> bool:
        """Mirror the wrapped sink's connection state."""
        return self._inner.is_connected

    @property
    def _ws(self) -> "WebSocket | None":
        """Expose the underlying WebSocket, when any (Phase 1 escape hatch)."""
        return self._inner._ws


# ---------------------------------------------------------------------------
# Internal aggregation state.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Aggregate:
    """Mutable accumulator for the per-step results of one run."""

    content: str = ""
    thinking: str = ""
    in_tokens: int = 0
    out_tokens: int = 0
    tool_calls: int = 0

    def absorb(self, sub: TurnResult) -> None:
        """Merge a sub-turn's result into the running aggregate."""
        if sub.content:
            sep = "\n\n" if self.content else ""
            self.content = f"{self.content}{sep}{sub.content}"
        if sub.thinking:
            self.thinking = f"{self.thinking}{sub.thinking}" \
                if not self.thinking else f"{self.thinking}\n\n{sub.thinking}"
        # The tool loop only reports the last iteration's usage — sum is
        # an over-estimate but never an under-estimate; matches what the
        # plan asks for ("agg_in/agg_out somma di tutti i step").
        self.in_tokens += sub.input_tokens
        self.out_tokens += sub.output_tokens
        if sub.had_tool_calls:
            self.tool_calls += 1


# ---------------------------------------------------------------------------
# Executor.
# ---------------------------------------------------------------------------


class AgentTurnExecutor:
    """Plan → act → critic loop sitting on top of :class:`DirectTurnExecutor`.

    Args:
        direct: The legacy single-shot executor used to run each step.
        components: Bundle of classifier / planner / critic services.
        cfg: ``ctx.config.agent`` — the Pydantic config sub-tree.
    """

    def __init__(
        self,
        *,
        direct: "DirectTurnExecutor",
        components: "AgentComponents",
        cfg: "AgentConfig",
    ) -> None:
        self._direct = direct
        self._classifier = components.classifier
        self._planner = components.planner
        self._critic = components.critic
        self._cfg = cfg

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        session: Any,
    ) -> TurnResult:
        """Run the agent loop for ``turn`` and return its outcome.

        Bypasses the loop and delegates to the wrapped
        :class:`DirectTurnExecutor` whenever:

        *   The classifier is disabled in config, OR
        *   No tools are wired in for this turn, OR
        *   The classifier verdict is ``TRIVIAL`` or ``OPEN_ENDED``.

        Never raises: every internal failure is mapped to a
        :class:`TurnResult` with the appropriate ``finish_reason`` so
        ``ws_chat`` keeps a single error path.
        """
        # Local import to break the import cycle that would otherwise be
        # caused by ``backend.services.agent`` importing config models
        # at module load.
        from backend.services.agent.models import TaskComplexity, VerdictAction

        # ------------------------------------------------------------------
        # Bypass path 1: classifier off / no tools.
        # ------------------------------------------------------------------
        if not self._cfg.classifier.enabled or not turn.tools:
            label = "classifier_disabled" if not self._cfg.classifier.enabled else "no_tools"
            return await self._direct_with_optional_critic(
                turn, sink, cancel_event, session, label=label,
            )

        # ------------------------------------------------------------------
        # Classification (fail-safe — never raises).
        # ------------------------------------------------------------------
        complexity = await self._classifier.classify(
            turn.user_content,
            has_tools=bool(turn.tools),
            cancel_event=cancel_event,
        )

        # ------------------------------------------------------------------
        # Bypass path 2: trivial / open-ended.
        # ------------------------------------------------------------------
        if complexity in (TaskComplexity.TRIVIAL, TaskComplexity.OPEN_ENDED):
            return await self._direct_with_optional_critic(
                turn, sink, cancel_event, session, label=complexity.value,
            )

        # ------------------------------------------------------------------
        # Persist a fresh AgentRun row (best-effort).
        # ------------------------------------------------------------------
        run = await self._create_run(
            session,
            conv_id=turn.conv_id,
            user_message_id=turn.user_msg_id,
            goal=turn.user_content,
            complexity=complexity.value,
        )
        run_id = run.id if run is not None else None
        # ``mode`` is "bypass" for the SINGLE_TOOL fast path (no real
        # plan ever produced) and "agent" for the full MULTI_STEP loop
        # below.  Older clients that don't read the field continue to
        # work — the addition is strictly additive.
        run_started_mode = (
            "bypass" if complexity == TaskComplexity.SINGLE_TOOL else "agent"
        )
        run_started_payload: dict[str, Any] = {
            "type": "agent.run_started",
            "run_id": str(run_id) if run_id is not None else None,
            "complexity": complexity.value,
            "mode": run_started_mode,
            # Carry the originating user message id so the frontend can
            # slice the conversation window owned by this run before the
            # final assistant message id is known.
            "user_message_id": str(turn.user_msg_id),
        }
        if run_started_mode == "bypass":
            # Bypass paths never produce a structured plan visible to
            # the client.  Surfacing ``plan=None`` / ``total_steps=0``
            # makes that explicit so the UI can hide the plan tray.
            run_started_payload["plan"] = None
            run_started_payload["total_steps"] = 0
        await sink.send(run_started_payload)

        # ------------------------------------------------------------------
        # SINGLE_TOOL: skip planner / critic, but still track the run.
        # ------------------------------------------------------------------
        if complexity == TaskComplexity.SINGLE_TOOL:
            return await self._run_single_tool(turn, sink, cancel_event, session, run)

        # ------------------------------------------------------------------
        # MULTI_STEP: full plan → act → critic loop.
        # ------------------------------------------------------------------
        return await self._run_multi_step(
            turn, sink, cancel_event, session, run, VerdictAction
        )

    # ------------------------------------------------------------------
    # SINGLE_TOOL strategy
    # ------------------------------------------------------------------

    async def _run_single_tool(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        session: Any,
        run: Any,
    ) -> TurnResult:
        """Execute as a single direct turn, persisting the run as ``done``.

        When ``cfg.critic.always_run`` is true the critic is invoked on
        the produced content.  A ``REPLAN`` verdict is honoured by
        promoting the turn to a 1-N-step mini-plan via the planner;
        ``RETRY`` re-runs the same direct execution up to
        ``cfg.max_retries_per_step`` with a reinforced user prompt.
        """
        from backend.services.agent.models import VerdictAction

        result = await self._direct.execute(turn, sink, cancel_event, session)

        # SINGLE_TOOL bypass: if the classifier said a tool was needed
        # but the model didn't call any, surface a soft warning so the
        # frontend can flag the mismatch.  Non-blocking: the critic
        # below still gets to render the final verdict.
        if not result.had_tool_calls and not cancel_event.is_set():
            await emit_warning(
                sink,
                run_id=run.id if run is not None else None,
                code="bypass_single_tool_no_call",
                message=(
                    "Il classificatore prevedeva l'uso di uno strumento "
                    "ma il modello non l'ha invocato."
                ),
            )

        if self._critic_always_run() and not cancel_event.is_set():
            verdict = await self._critique_bypass(
                turn=turn,
                sink=sink,
                cancel_event=cancel_event,
                run_id=run.id if run is not None else None,
                output=result.content,
                finish_reason=result.finish_reason,
                label="single_tool",
            )

            retries = 0
            while (
                verdict.action == VerdictAction.RETRY
                and retries < self._cfg.max_retries_per_step
                and not cancel_event.is_set()
            ):
                retries += 1
                result = await self._direct.execute(
                    self._reinforce_turn(turn, verdict.reason, retries),
                    sink, cancel_event, session,
                )
                verdict = await self._critique_bypass(
                    turn=turn,
                    sink=sink,
                    cancel_event=cancel_event,
                    run_id=run.id if run is not None else None,
                    output=result.content,
                    finish_reason=result.finish_reason,
                    label="single_tool",
                )

            if verdict.action == VerdictAction.REPLAN and not cancel_event.is_set():
                # Promote to a real mini-plan and run it through the
                # multi-step machinery.  The original direct result is
                # discarded — the planner will re-do the work with a
                # structured plan that the critic can guard end-to-end.
                logger.info(
                    "SINGLE_TOOL promoted to MULTI_STEP after REPLAN: {}",
                    verdict.reason,
                )
                await emit_warning(
                    sink,
                    run_id=run.id if run is not None else None,
                    code="single_tool_promoted",
                    message=(
                        "La richiesta richiede una pianificazione: "
                        "riformulo come piano in più passi."
                    ),
                )
                if run is not None:
                    run.complexity = "multi_step"
                    await self._flush(session)
                return await self._run_multi_step(
                    turn, sink, cancel_event, session, run, VerdictAction,
                )

            if verdict.action in (VerdictAction.RETRY, VerdictAction.REPLAN):
                # Retries exhausted (or REPLAN under cancel) — surface as warning.
                await emit_warning(
                    sink,
                    run_id=run.id if run is not None else None,
                    code="critic_unsatisfied",
                    message=(
                        "La verifica non è stata superata e non posso "
                        "riprovare oltre."
                    ),
                )

        if run is not None:
            state = self._final_state_from_finish_reason(result.finish_reason)
            run.state = state
            run.total_steps = 1
            run.current_step = 1 if state == "done" else 0
            run.total_tokens_in = result.input_tokens
            run.total_tokens_out = result.output_tokens
            run.total_tool_calls = 1 if result.had_tool_calls else 0
            run.error = None if state == "done" else result.finish_reason
            await self._finalize_run(session, run)
        await sink.send(
            {
                "type": "agent.run_finished",
                "run_id": str(run.id) if run is not None else None,
                "state": run.state if run is not None else "done",
            },
        )
        return TurnResult(
            content=result.content,
            thinking=result.thinking,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            finish_reason=result.finish_reason,
            final_assistant_message_id=result.final_assistant_message_id,
            had_tool_calls=result.had_tool_calls,
            agent_run_id=run.id if run is not None else None,
        )

    # ------------------------------------------------------------------
    # Bypass critic helpers
    # ------------------------------------------------------------------

    def _critic_always_run(self) -> bool:
        """Return True when ``cfg.critic.always_run`` is enabled.

        ``getattr`` is used to keep compatibility with stub configs
        used in unit tests that may omit the attribute.
        """
        return bool(getattr(self._cfg.critic, "always_run", False))

    async def _critique_bypass(
        self,
        *,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        run_id: Any,
        output: str,
        finish_reason: str | None,
        label: str,
    ) -> Any:
        """Invoke the critic on a bypass turn output and emit the WS event.

        Builds a minimal generic 1-step :class:`Plan` *inline* (no fake
        per-user-content step is materialised — the user's request is
        passed only as the goal so the critic prompt has the necessary
        context) and calls :meth:`CriticService.evaluate`.
        """
        from backend.services.agent.models import Plan, Step

        step = Step(
            index=0,
            description="Risposta diretta all'utente.",
            expected_outcome=(
                "Risposta coerente con la richiesta, senza degenerazioni."
            ),
            tool_hint=None,
        )
        plan = Plan(goal=turn.user_content or "(richiesta vuota)", steps=[step])
        verdict = await self._critic.evaluate(
            step=step,
            output=output,
            plan=plan,
            retries_used=0,
            cancel_event=cancel_event,
            finish_reason=finish_reason,
        )
        # ``label`` is logged for traceability but never surfaced in
        # ``verdict.reason`` (which must stay user-facing italian).
        logger.debug("Bypass critique label={} verdict={}", label, verdict.action)
        await emit_critic_invoked(
            sink, run_id=run_id, step_index=0, verdict=verdict,
        )
        return verdict

    async def _direct_with_optional_critic(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        session: Any,
        *,
        label: str,
    ) -> TurnResult:
        """Run the direct executor and optionally critique its output.

        Used by the *non-tool-flow* bypass paths (TRIVIAL,
        OPEN_ENDED, classifier disabled, no tools).  Recovery is not
        attempted: a non-OK verdict is surfaced as a soft
        ``agent.warning`` event and the original result is returned
        untouched — it is up to the user / UI to react.

        When ``cfg.critic.always_run`` is true the executor wraps the
        delegated direct turn with ``agent.run_started`` (mode=bypass)
        and ``agent.run_finished`` so the WS contract stays uniform
        with the SINGLE_TOOL / MULTI_STEP paths.  When it's off, no
        ``agent.*`` event is emitted and the path is bit-equivalent to
        :class:`DirectTurnExecutor` alone.
        """
        from backend.services.agent.models import VerdictAction

        critic_on = self._critic_always_run()
        if critic_on:
            await sink.send(
                {
                    "type": "agent.run_started",
                    "run_id": None,
                    "complexity": label,
                    "mode": "bypass",
                    "plan": None,
                    "total_steps": 0,
                },
            )

        result = await self._direct.execute(turn, sink, cancel_event, session)
        if not critic_on or cancel_event.is_set():
            return result

        verdict = await self._critique_bypass(
            turn=turn,
            sink=sink,
            cancel_event=cancel_event,
            run_id=None,
            output=result.content,
            finish_reason=result.finish_reason,
            label=label,
        )
        if verdict.action != VerdictAction.OK:
            logger.warning(
                "Bypass critic non-OK ({}): {}", verdict.action.value, verdict.reason,
            )
            await emit_warning(
                sink,
                run_id=None,
                code="degenerated_output",
                message=(
                    "La verifica ha rilevato un problema con la risposta."
                ),
            )
        await sink.send(
            {
                "type": "agent.run_finished",
                "run_id": None,
                "state": "done",
            },
        )
        return result

    @staticmethod
    def _reinforce_turn(turn: TurnInput, reason: str, attempt: int) -> TurnInput:
        """Append a reinforcement message before retrying a bypass turn."""
        nudge = (
            f"[Retry {attempt}] La risposta precedente è stata giudicata "
            f"insufficiente dal validatore: {reason}\n"
            "Riprova rispettando rigorosamente il formato richiesto, "
            "evitando ripetizioni e SENZA emettere blocchi <tool_code> o "
            "JSON tool-call testuali (usa la function-call API)."
        )
        new_messages = list(turn.messages) + [{"role": "user", "content": nudge}]
        from dataclasses import replace as _replace

        return _replace(turn, messages=new_messages)

    # ------------------------------------------------------------------
    # MULTI_STEP strategy
    # ------------------------------------------------------------------

    async def _run_multi_step(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        session: Any,
        run: Any,
        verdict_action_cls: Any,
    ) -> TurnResult:
        """Plan, then iterate steps with critic-driven control flow."""
        # Local imports to avoid module-load cycles.
        from backend.services.agent.models import Verdict, VerdictAction
        # Plan generation -------------------------------------------------
        plan = await self._planner.plan(
            goal=turn.user_content,
            available_tools=list(turn.tools or []),
            cancel_event=cancel_event,
        )
        if run is not None:
            run.state = "running"
            run.plan_json = plan.model_dump_json()
            run.total_steps = len(plan.steps)
            await self._flush(session)
        await sink.send(
            {
                "type": "agent.plan_created",
                "run_id": str(run.id) if run is not None else None,
                "plan": plan.model_dump(mode="json"),
            },
        )

        # Loop ------------------------------------------------------------
        agg = _Aggregate()
        retries: dict[int, int] = {}
        replans = 0
        retries_total = 0
        last_finish_reason = "stop"
        end_state = "done"
        end_error: str | None = None
        deadline = self._compute_deadline()
        max_steps = max(1, self._cfg.max_steps)
        i = 0

        while i < min(len(plan.steps), max_steps):
            if cancel_event.is_set():
                end_state = "cancelled"
                last_finish_reason = "cancelled"
                break
            if self._deadline_exceeded(deadline):
                end_state = "failed"
                end_error = "total_timeout"
                last_finish_reason = "error"
                break

            step = plan.steps[i]
            await sink.send(
                {
                    "type": "agent.step_started",
                    "run_id": str(run.id) if run is not None else None,
                    "step_index": i,
                    "total_steps": len(plan.steps),
                    "step": step.model_dump(mode="json"),
                },
            )

            sub_turn = self._build_sub_turn(turn, step, agg.content, i)
            annotated = AnnotatingSink(sink, step_index=i)

            try:
                sub_result = await self._execute_step_with_timeout(
                    sub_turn, annotated, cancel_event, session
                )
            except asyncio.TimeoutError:
                end_state = "failed"
                end_error = f"step_timeout:{i}"
                last_finish_reason = "error"
                break

            agg.absorb(sub_result)
            last_finish_reason = sub_result.finish_reason

            if sub_result.finish_reason == "cancelled" or cancel_event.is_set():
                end_state = "cancelled"
                last_finish_reason = "cancelled"
                break
            if sub_result.finish_reason == "disconnected":
                end_state = "failed"
                end_error = "disconnected"
                last_finish_reason = "disconnected"
                break
            if sub_result.finish_reason == "error":
                end_state = "failed"
                end_error = "step_error"
                break

            # --- Structural intent-mismatch check -------------------
            # When the planner explicitly declared a tool for this step
            # (``step.tool_hint``) but the inner LLM produced no tool
            # call at all, short-circuit straight to REPLAN — there is
            # no point burning a critic LLM call on an output that
            # objectively missed the planner's intent.  No regex on
            # the output text is involved.
            if step.tool_hint and not sub_result.had_tool_calls:
                logger.info(
                    "Structural intent mismatch on step {} (hint={!r}, no tool_calls)",
                    i,
                    step.tool_hint,
                )
                await emit_warning(
                    sink,
                    run_id=run.id if run is not None else None,
                    code="intent_mismatch_no_tool",
                    message=(
                        f"Lo step {i + 1} prevedeva l'uso di "
                        f"'{step.tool_hint}' ma il modello non l'ha invocato."
                    ),
                )
                verdict = Verdict(
                    action=VerdictAction.REPLAN,
                    reason="Lo step prevedeva uno strumento ma il modello non lo ha invocato.",
                    source="detector",
                )
            else:
                verdict = await self._critic.evaluate(
                    step=step,
                    output=sub_result.content,
                    plan=plan,
                    retries_used=retries.get(i, 0),
                    cancel_event=cancel_event,
                    finish_reason=sub_result.finish_reason,
                )
            await emit_critic_invoked(
                sink,
                run_id=run.id if run is not None else None,
                step_index=i,
                verdict=verdict,
            )
            await sink.send(
                {
                    "type": "agent.step_completed",
                    "run_id": str(run.id) if run is not None else None,
                    "step_index": i,
                    "verdict": verdict.model_dump(mode="json"),
                },
            )

            action = verdict.action
            if action == verdict_action_cls.OK:
                i += 1
            elif action == verdict_action_cls.RETRY:
                used = retries.get(i, 0)
                if used < self._cfg.max_retries_per_step:
                    retries[i] = used + 1
                    retries_total += 1
                    # Do not advance — retry the same step.
                else:
                    i += 1
            elif action == verdict_action_cls.REPLAN:
                if replans < self._cfg.max_replans:
                    replans += 1
                    new_plan = await self._planner.plan(
                        goal=turn.user_content,
                        available_tools=list(turn.tools or []),
                        history_summary=self._summarise_history(plan, i),
                        remaining_goal=verdict.reason,
                        cancel_event=cancel_event,
                    )
                    plan = self._splice_plan(plan, i, new_plan)
                    if run is not None:
                        run.replans = replans
                        run.plan_json = plan.model_dump_json()
                        run.total_steps = len(plan.steps)
                        await self._flush(session)
                    await sink.send(
                        {
                            "type": "agent.replanned",
                            "run_id": str(run.id) if run is not None else None,
                            "new_plan": plan.model_dump(mode="json"),
                            "replan_count": replans,
                        },
                    )
                    i += 1
                else:
                    i += 1
            elif action == verdict_action_cls.ASK_USER:
                end_state = "asked_user"
                await sink.send(
                    {
                        "type": "agent.ask_user",
                        "run_id": str(run.id) if run is not None else None,
                        "question": verdict.question or verdict.reason,
                    },
                )
                break
            elif action == verdict_action_cls.ABORT:
                end_state = "failed"
                end_error = verdict.reason
                break
            else:  # pragma: no cover — exhaustive enum
                i += 1

            if run is not None:
                run.current_step = i
                run.retries_total = retries_total
                run.total_tokens_in = agg.in_tokens
                run.total_tokens_out = agg.out_tokens
                run.total_tool_calls = agg.tool_calls
                await self._flush(session)

        # Finalize --------------------------------------------------------
        if run is not None:
            run.state = end_state
            run.error = end_error
            run.current_step = i
            run.retries_total = retries_total
            run.replans = replans
            run.total_tokens_in = agg.in_tokens
            run.total_tokens_out = agg.out_tokens
            run.total_tool_calls = agg.tool_calls
            await self._finalize_run(session, run)
        await sink.send(
            {
                "type": "agent.run_finished",
                "run_id": str(run.id) if run is not None else None,
                "state": end_state,
            },
        )

        finish_reason = "stop" if end_state == "done" else (
            last_finish_reason if end_state in ("cancelled", "asked_user")
            else last_finish_reason
        )
        # ``cancelled`` / ``asked_user`` map directly; ``failed`` keeps
        # the inner reason ("error" / "disconnected" / "error").
        if end_state == "asked_user":
            finish_reason = "asked_user"
        elif end_state == "cancelled":
            finish_reason = "cancelled"
        elif end_state == "done":
            finish_reason = "stop"
        # else: leave finish_reason as last seen ("error" / "disconnected").

        return TurnResult(
            content=agg.content,
            thinking=agg.thinking,
            input_tokens=agg.in_tokens,
            output_tokens=agg.out_tokens,
            finish_reason=finish_reason,
            final_assistant_message_id=None,
            had_tool_calls=agg.tool_calls > 0,
            agent_run_id=run.id if run is not None else None,
        )

    # ------------------------------------------------------------------
    # Sub-turn assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _build_sub_turn(
        turn: TurnInput,
        step: "Step",
        accumulated_content: str,
        step_index: int,
    ) -> TurnInput:
        """Return a new :class:`TurnInput` enriched with the step's prompt.

        The original ``messages`` and ``history`` payloads are preserved
        verbatim — we only append a single ``user`` message that
        instructs the model on the current step.  All compression /
        history flags propagate through unchanged.
        """
        step_block = (
            f"[Agent step {step_index + 1}] {step.description}\n"
            f"Risultato atteso: {step.expected_outcome}"
        )
        if accumulated_content:
            step_block = (
                f"{step_block}\n\n"
                f"Contesto dei passi precedenti:\n{accumulated_content}"
            )
        extra_msg = {"role": "user", "content": step_block}
        new_messages = list(turn.messages) + [extra_msg]
        return TurnInput(
            conv_id=turn.conv_id,
            user_msg_id=turn.user_msg_id,
            user_content=step.description,
            history=turn.history,
            messages=new_messages,
            tools=turn.tools,
            memory_context=turn.memory_context,
            cached_sys_prompt=turn.cached_sys_prompt,
            attachment_info=turn.attachment_info,
            context_window=turn.context_window,
            version_group_id=turn.version_group_id,
            version_index=turn.version_index,
            client_ip=turn.client_ip,
            resolved_max_tokens=turn.resolved_max_tokens,
            was_compressed=turn.was_compressed,
            compressed_history=turn.compressed_history,
            tool_tokens=turn.tool_tokens,
        )

    @staticmethod
    def _splice_plan(current: "Plan", index: int, replacement: "Plan") -> "Plan":
        """Replace the tail of ``current`` from ``index+1`` with ``replacement``."""
        from backend.services.agent.models import Plan

        head = list(current.steps[: index + 1])
        # Reindex the new steps so the sequence stays monotonic.
        new_tail: list[Any] = []
        for offset, step in enumerate(replacement.steps, start=index + 1):
            new_tail.append(step.model_copy(update={"index": offset}))
        return Plan(goal=current.goal, steps=head + new_tail)

    @staticmethod
    def _summarise_history(plan: "Plan", index: int) -> str:
        """Short textual recap of the steps already executed (for re-plan)."""
        parts = []
        for step in plan.steps[: index + 1]:
            parts.append(f"- {step.description} (atteso: {step.expected_outcome})")
        return "\n".join(parts) if parts else "(nessun passo eseguito)"

    # ------------------------------------------------------------------
    # Step execution + timeout
    # ------------------------------------------------------------------

    async def _execute_step_with_timeout(
        self,
        sub_turn: TurnInput,
        annotated: WSEventSink,
        cancel_event: asyncio.Event,
        session: Any,
    ) -> TurnResult:
        """Run one step under ``cfg.step_timeout_seconds``."""
        timeout = self._cfg.step_timeout_seconds
        coro = self._direct.execute(sub_turn, annotated, cancel_event, session)
        if timeout and timeout > 0:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

    def _compute_deadline(self) -> float | None:
        """Return the monotonic deadline for the run, or ``None`` if disabled."""
        total = self._cfg.total_timeout_seconds
        if total and total > 0:
            return time.monotonic() + total
        return None

    @staticmethod
    def _deadline_exceeded(deadline: float | None) -> bool:
        """Check whether the monotonic clock crossed ``deadline``."""
        return deadline is not None and time.monotonic() >= deadline

    # ------------------------------------------------------------------
    # AgentRun persistence helpers
    # ------------------------------------------------------------------

    async def _create_run(
        self,
        session: Any,
        *,
        conv_id: uuid.UUID,
        user_message_id: uuid.UUID,
        goal: str,
        complexity: str,
    ) -> Any | None:
        """Create and flush a new ``AgentRun`` row.

        Returns ``None`` if persistence is disabled or unavailable so
        the caller can keep working without a DB row (used in unit
        tests that pass ``session=None``).
        """
        if not self._cfg.persistence.save_runs or session is None:
            return None
        try:
            from backend.db.models import AgentRun

            run = AgentRun(
                conversation_id=conv_id,
                user_message_id=user_message_id,
                goal=goal,
                complexity=complexity,
                state="planning",
                plan_json="[]",
            )
            session.add(run)
            await self._flush(session)
            return run
        except Exception as exc:  # noqa: BLE001 — never block the user
            logger.warning("AgentRun create failed: {}", exc)
            return None

    async def _finalize_run(self, session: Any, run: Any) -> None:
        """Set ``finished_at`` and flush the run row (best-effort)."""
        if run is None or session is None:
            return
        try:
            from datetime import datetime, timezone

            run.finished_at = datetime.now(timezone.utc)
            session.add(run)
            await self._flush(session)
        except Exception as exc:  # noqa: BLE001 — non-fatal
            logger.warning("AgentRun finalize failed: {}", exc)

    @staticmethod
    async def _flush(session: Any) -> None:
        """Async flush that tolerates sync test doubles."""
        flush = getattr(session, "flush", None)
        if flush is None:
            return
        result = flush()
        if hasattr(result, "__await__"):
            await result

    @staticmethod
    def _final_state_from_finish_reason(reason: str) -> str:
        """Map a :class:`TurnResult.finish_reason` to an ``AgentRun.state``."""
        if reason in ("stop", "length"):
            return "done"
        if reason == "cancelled":
            return "cancelled"
        if reason == "disconnected":
            return "failed"
        return "failed"


# Re-export of plan_json helper used by tests --------------------------------

def serialize_plan_steps(plan: "Plan") -> str:
    """Return a JSON-encoded list of plan steps (used by tests)."""
    return json.dumps([s.model_dump(mode="json") for s in plan.steps])


__all__ = ["AgentTurnExecutor", "AnnotatingSink", "serialize_plan_steps"]
