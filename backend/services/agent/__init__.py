"""Agent loop services package.

Phase 2 of the rollout (see ``alice/agent_loop_plan.md`` §8): isolated,
unit-testable components.  Nothing here is wired into ``ws_chat`` yet —
that's Phase 3 (subagent C).

Public API:
    - :class:`ClassifierService`
    - :class:`PlannerService`
    - :class:`CriticService`
    - :class:`AgentComponents` — convenience aggregator passed to the
      ``AgentTurnExecutor`` once that lands.
    - Domain models: :class:`TaskComplexity`, :class:`Plan`, :class:`Step`,
      :class:`Verdict`, :class:`VerdictAction`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .classifier import ClassifierService
from .critic import CriticService
from .models import (
    ClassifierConfig,
    CriticConfig,
    Plan,
    PlannerConfig,
    Step,
    TaskComplexity,
    Verdict,
    VerdictAction,
)
from .planner import PlannerService


@dataclass(slots=True)
class AgentComponents:
    """Bundle of the three agent services used by ``AgentTurnExecutor``.

    Wired together once at startup (see Phase 3) so the executor can
    accept a single dependency instead of three.
    """

    classifier: ClassifierService
    planner: PlannerService
    critic: CriticService


__all__ = [
    "AgentComponents",
    "ClassifierService",
    "PlannerService",
    "CriticService",
    "TaskComplexity",
    "Plan",
    "Step",
    "Verdict",
    "VerdictAction",
    "ClassifierConfig",
    "PlannerConfig",
    "CriticConfig",
]
