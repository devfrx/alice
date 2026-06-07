"""AL\\CE — Reflective turn executor (model-driven default + optional self-check).

This wraps the model-driven default path with a single, **non-blocking**
reflection pass over the final answer.

The model-driven path needs no bespoke control flow: the agentic behaviour
comes from the ``agent`` plugin's meta-tools (``update_plan`` /
``spawn_subagent``), which already live in the tool registry and run inside
the normal :func:`run_tool_loop`.  So the engine is just the wrapped
:class:`~backend.services.turn.direct_executor.DirectTurnExecutor`; this
executor only adds reflection on top.

Reflection uses the self-contained
:class:`~backend.services.turn._reflection.ReflectionCritic` and applies it
**once** to the completed turn rather than grading every step.  It never
rewrites or blocks the answer: a non-OK verdict is surfaced as an
``agent.warning`` WS event so the UI can flag it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.services.turn._reflection import ReflectionCritic
from backend.services.turn.models import TurnInput, TurnResult
from backend.services.turn.sink import WSEventSink

if TYPE_CHECKING:  # pragma: no cover — typing only
    from backend.core.config import AgentConfig
    from backend.services.turn.direct_executor import DirectTurnExecutor


class ReflectiveTurnExecutor:
    """Model-driven executor that adds an optional final-answer self-check.

    Args:
        direct: The executor that actually runs the turn (its tool loop
            already exposes the agentic meta-tools).
        critic: The reflection critic reused for the self-check pass.
        cfg: ``ctx.config.agent`` — the agent config sub-tree.
    """

    def __init__(
        self,
        *,
        direct: DirectTurnExecutor,
        critic: ReflectionCritic,
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
        """Run a single reflection pass and surface a non-blocking warning."""
        verdict = await self._critic.evaluate(
            output=result.content,
            finish_reason=result.finish_reason,
            goal=turn.user_content or "(richiesta vuota)",
            cancel_event=cancel_event,
        )

        await sink.send(
            {
                "type": "agent.critic_invoked",
                "run_id": None,
                "step_index": 0,
                "source": verdict.source or "llm",
            }
        )
        if not verdict.ok:
            logger.info("Reflection flagged output: {}", verdict.reason)
            await sink.send(
                {
                    "type": "agent.warning",
                    "run_id": None,
                    "code": "degenerated_output",
                    "message": (
                        "La verifica ha rilevato un possibile problema "
                        "con la risposta."
                    ),
                }
            )


__all__ = ["ReflectiveTurnExecutor"]
