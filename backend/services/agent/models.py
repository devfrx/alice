"""Domain models for the agent loop.

Defines the Pydantic schemas shared by ``ClassifierService``,
``PlannerService`` and ``CriticService``.  These models are JSON-
serializable so they can be transported over WebSocket and persisted
to the ``AgentRun`` table.

This module also exposes the *sub-config* models
(``ClassifierConfig`` / ``PlannerConfig`` / ``CriticConfig``) used to
parameterize each service.  The aggregating ``AgentConfig`` lives in
``core/config.py`` (see Phase 3 of the rollout).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TaskComplexity(str, Enum):
    """Complexity classes inferred by the classifier.

    Values are lowercase snake_case strings to keep the prompt /
    response contract stable and easily parseable.
    """

    TRIVIAL = "trivial"
    OPEN_ENDED = "open_ended"
    SINGLE_TOOL = "single_tool"
    MULTI_STEP = "multi_step"


ClassificationSource = Literal["heuristic", "llm", "default"]
"""Where a :class:`ClassificationResult` came from.

* ``heuristic`` — deterministic regex match, LLM not invoked.
* ``llm``       — produced by the classifier model.
* ``default``   — safe fallback used on LLM/parse errors.
"""


class ClassificationResult(BaseModel):
    """Structured classifier output.

    The legacy :meth:`ClassifierService.classify` method still returns a
    bare :class:`TaskComplexity` for backwards compatibility; this model
    is exposed for callers that need the provenance metadata (logging,
    metrics, future WS events).
    """

    complexity: TaskComplexity
    source: ClassificationSource = "llm"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class Step(BaseModel):
    """One actionable unit inside a Plan."""

    index: int = Field(ge=0, description="Zero-based ordering inside the plan.")
    description: str = Field(min_length=1, description="What to do.")
    expected_outcome: str = Field(
        min_length=1,
        description="How we'll know the step succeeded.",
    )
    tool_hint: str | None = Field(
        default=None,
        description="Optional name of the tool the planner expects to use.",
    )


class Plan(BaseModel):
    """An ordered list of steps that together satisfy the user's goal."""

    goal: str = Field(min_length=1, description="High-level user intent.")
    steps: list[Step] = Field(description="Non-empty list of ordered steps.")

    @field_validator("steps")
    @classmethod
    def _steps_non_empty(cls, value: list[Step]) -> list[Step]:
        """Reject empty plans — the orchestrator requires at least one step."""
        if not value:
            raise ValueError("Plan.steps must contain at least one Step")
        return value


class VerdictAction(str, Enum):
    """Outcome action proposed by the critic for a completed step."""

    OK = "ok"
    RETRY = "retry"
    REPLAN = "replan"
    ASK_USER = "ask_user"
    ABORT = "abort"


class Verdict(BaseModel):
    """Critic decision about a step's output."""

    action: VerdictAction
    reason: str = Field(min_length=1, description="Short justification.")
    question: str | None = Field(
        default=None,
        description="Required when action=ASK_USER — what to ask the user.",
    )
    source: str | None = Field(
        default=None,
        description=(
            "Origin of the verdict: ``\"detector\"`` for the local "
            "degeneration detector, ``\"llm\"`` for the model call, "
            "``None`` when produced by tests / fallbacks."
        ),
    )


# ---------------------------------------------------------------------------
# Sub-config models (consumed by the services and by AgentConfig in core/).
# ---------------------------------------------------------------------------


class ClassifierConfig(BaseModel):
    """Tunables for ``ClassifierService``.

    Defaults mirror ``config/default.yaml`` (§10 of the agent_loop_plan).
    """

    enabled: bool = True
    cache_ttl_seconds: int = Field(default=300, ge=0)
    max_output_tokens: int = Field(default=20, ge=1)
    temperature: float = Field(default=0.0, ge=0.0)


class PlannerConfig(BaseModel):
    """Tunables for ``PlannerService``."""

    max_output_tokens: int = Field(default=600, ge=1)
    temperature: float = Field(default=0.2, ge=0.0)
    require_json_object: bool = True


class CriticConfig(BaseModel):
    """Tunables for ``CriticService``.

    ``fail_open`` controls the behaviour on parse error: when ``True``
    the critic returns ``OK`` (does not block the user); when ``False``
    it returns ``RETRY``.
    """

    max_output_tokens: int = Field(default=80, ge=1)
    temperature: float = Field(default=0.0, ge=0.0)
    fail_open: bool = True
    always_run: bool = True
    degeneration_detector_enabled: bool = True


__all__ = [
    "TaskComplexity",
    "ClassificationSource",
    "ClassificationResult",
    "Step",
    "Plan",
    "VerdictAction",
    "Verdict",
    "ClassifierConfig",
    "PlannerConfig",
    "CriticConfig",
]
