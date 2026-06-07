"""AL\\CE — Reflective turn executor (model-driven default + optional self-check).

This wraps the model-driven default path with a single, **non-blocking**
reflection pass over the final answer.

The model-driven path needs no bespoke control flow: the agentic behaviour
comes from the ``agent`` plugin's meta-tools (``update_plan`` /
``spawn_subagent``), which already live in the tool registry and run inside
the normal :func:`run_tool_loop`.  So the engine is just the wrapped
:class:`~backend.services.turn.direct_executor.DirectTurnExecutor`; this
executor only adds reflection on top.

Reflection reuses the structured-mode
:class:`~backend.services.agent.critic.CriticService` but applies it **once**
to the completed turn rather than grading every step.  It never rewrites or
blocks the answer: a non-OK verdict is surfaced as an ``agent.warning`` WS
event so the UI can flag it, mirroring the bypass-critic behaviour of
:class:`~backend.services.turn.agent_executor.AgentTurnExecutor`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.services.turn._critic_bypass import emit_critic_invoked, emit_warning
from backend.services.turn.models import TurnInput, TurnResult
from backend.services.turn.sink import WSEventSink

if TYPE_CHECKING:  # pragma: no cover — typing only
    from backend.core.config import AgentConfig
    from backend.services.agent.critic import CriticService
    from backend.services.turn.direct_executor import DirectTurnExecutor


class ReflectiveTurnExecutor:
    """Model-driven executor that adds an optional final-answer self-check.

    Args:
        direct: The lite executor that actually runs the turn (its tool
            loop already exposes the agentic meta-tools).
        critic: The critic service reused for the reflection pass.
        cfg: ``ctx.config.agent`` — the agent config sub-tree.
    """

    def __init__(
        self,
        *,
        direct: DirectTurnExecutor,
        critic: CriticService,
        cfg: AgentConfig,
    ) -> None:
        self._direct = direct
        self._critic = critic
        self._cfg = cfg

    async def execute(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        session: Any,
    ) -> TurnResult:
        """Run the turn, then reflect on the final answer when applicable.

        The returned :class:`TurnResult` is the direct executor's result,
        unchanged — reflection only emits diagnostic WS events.
        """
        result = await self._direct.execute(turn, sink, cancel_event, session)
        if self._should_reflect(result, cancel_event):
            await self._reflect(turn, result, sink, cancel_event)
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _should_reflect(
        self, result: TurnResult, cancel_event: asyncio.Event,
    ) -> bool:
        """Decide whether a reflection pass is warranted for this turn."""
        refl = getattr(self._cfg, "reflection", None)
        if refl is None or not getattr(refl, "enabled", False):
            return False
        if cancel_event.is_set():
            return False
        # Only reflect on cleanly completed turns with actual content.
        if result.finish_reason not in ("stop", "length"):
            return False
        if not (result.content or "").strip():
            return False
        if getattr(refl, "tool_turns_only", True):
            return result.had_tool_calls
        return True

    async def _reflect(
        self,
        turn: TurnInput,
        result: TurnResult,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
    ) -> None:
        """Run a single critic pass and surface a non-blocking warning."""
        from backend.services.agent.models import Plan, Step, VerdictAction

        step = Step(
            index=0,
            description="Risposta diretta all'utente.",
            expected_outcome=(
                "Risposta coerente con la richiesta, senza degenerazioni."
            ),
            tool_hint=None,
        )
        plan = Plan(goal=turn.user_content or "(richiesta vuota)", steps=[step])
        try:
            verdict = await self._critic.evaluate(
                step=step,
                output=result.content,
                plan=plan,
                retries_used=0,
                cancel_event=cancel_event,
                finish_reason=result.finish_reason,
            )
        except Exception as exc:  # noqa: BLE001 — reflection must never break a turn
            logger.warning("Reflection critic failed: {}", exc)
            return

        await emit_critic_invoked(sink, run_id=None, step_index=0, verdict=verdict)
        if verdict.action != VerdictAction.OK:
            logger.info("Reflection flagged output: {}", verdict.reason)
            await emit_warning(
                sink,
                run_id=None,
                code="degenerated_output",
                message="La verifica ha rilevato un possibile problema con la risposta.",
            )


__all__ = ["ReflectiveTurnExecutor"]
