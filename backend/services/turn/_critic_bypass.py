"""Helpers for running the critic outside the MULTI_STEP loop.

The agent executor invokes the critic after every turn — including
the bypass paths (TRIVIAL / OPEN_ENDED, classifier-disabled, no
tools and SINGLE_TOOL).  Those paths don't have a real
:class:`~backend.services.agent.models.Plan`; the executor builds a
generic stub inline (no fake "Step description = user content" is
synthesised — that would surface as a fake plan to anyone inspecting
the run state).  This module exposes only the small WS-event helpers
shared by the bypass and multi-step paths.
"""

from __future__ import annotations

from typing import Any

from backend.services.agent.models import Verdict
from backend.services.turn.sink import WSEventSink


async def emit_critic_invoked(
    sink: WSEventSink,
    *,
    run_id: Any,
    step_index: int,
    verdict: Verdict,
) -> None:
    """Emit ``agent.critic_invoked`` annotated with the verdict source.

    Args:
        sink: Destination sink for the WS event.
        run_id: Optional ``AgentRun`` identifier — ``None`` is allowed
            (bypass paths without persistence).
        step_index: Index of the step that was critiqued (``0`` for
            bypass paths that have no real plan).
        verdict: The :class:`Verdict` returned by the critic; its
            ``source`` field disambiguates ``"detector"`` / ``"llm"`` /
            ``"fallback"``.  ``None`` is mapped to ``"llm"`` for
            backwards compatibility.
    """
    await sink.send(
        {
            "type": "agent.critic_invoked",
            "run_id": str(run_id) if run_id is not None else None,
            "step_index": step_index,
            "source": verdict.source or "llm",
        }
    )


async def emit_warning(
    sink: WSEventSink,
    *,
    run_id: Any,
    code: str,
    message: str,
) -> None:
    """Emit a soft ``agent.warning`` event (non-blocking diagnostic).

    Used by bypass paths when the critic flags degeneration but the
    caller has no recovery strategy (e.g. TRIVIAL / OPEN_ENDED / no
    tools): the result is still returned to the user but the warning
    is surfaced so the UI can highlight it.

    Args:
        sink: Destination sink for the WS event.
        run_id: Optional run id.
        code: Short machine-readable identifier (e.g.
            ``"degenerated_output"``, ``"intent_mismatch_no_tool"``,
            ``"bypass_single_tool_no_call"``).
        message: Human-readable italian diagnostic.
    """
    await sink.send(
        {
            "type": "agent.warning",
            "run_id": str(run_id) if run_id is not None else None,
            "code": code,
            "message": message,
        }
    )


__all__ = [
    "emit_critic_invoked",
    "emit_warning",
]
