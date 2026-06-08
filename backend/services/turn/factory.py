"""AL\\CE — Turn executor factory.

The model-driven loop is the **only** execution path: the engine is always
:class:`DirectTurnExecutor`, whose agentic behaviour comes from the ``agent``
plugin's meta-tools (``update_plan`` / ``spawn_subagent``) already in the
tool registry and driven inside the normal :func:`run_tool_loop`.

There are exactly two outcomes:

* ``agent.reflection.enabled = False`` (default) → a bare
  :class:`DirectTurnExecutor`.
* ``agent.reflection.enabled = True`` → that same executor wrapped in a
  :class:`~backend.services.turn.reflective_executor.ReflectiveTurnExecutor`
  that adds a single, non-blocking final-answer self-check.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from backend.core.context import AppContext
from backend.services.llm_service import LLMService
from backend.services.turn._reflection import ReflectionCritic
from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.reflective_executor import ReflectiveTurnExecutor

SyncFn = Callable[..., Coroutine[Any, Any, None]]


def create_turn_executor(
    ctx: AppContext,
    llm: LLMService,
    sync_fn: SyncFn | None = None,
) -> Any:
    """Return the executor strategy for the current configuration.

    Args:
        ctx: Application context (config + services).
        llm: Active LLM service.
        sync_fn: Optional ``_sync_conversation_to_file`` callback handed
            down to the tool loop. ``None`` disables file sync.

    Returns:
        A :class:`DirectTurnExecutor` (default), or a
        :class:`~backend.services.turn.reflective_executor.ReflectiveTurnExecutor`
        wrapping it when ``agent.reflection.enabled`` is set.
    """
    direct = DirectTurnExecutor(ctx, llm, sync_fn=sync_fn)

    refl = ctx.config.agent.reflection
    if getattr(refl, "enabled", False):
        return ReflectiveTurnExecutor(
            direct=direct,
            critic=ReflectionCritic(llm, refl),
            cfg=ctx.config.agent,
        )
    return direct


__all__ = ["create_turn_executor"]
