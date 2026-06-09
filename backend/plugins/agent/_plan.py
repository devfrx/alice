"""AL\\CE — Agent plugin: per-conversation tasks (todo-list) store.

The task list is a model-driven, mutable checklist (Claude/GPT ``TodoWrite``
style).  Each call to the ``update_tasks`` tool *replaces* the whole list
for the active conversation, so the model always owns the source of truth.

State is intentionally in-memory and process-local: a plan tracks the work
of an in-flight turn, not durable history.  It is keyed by ``conversation_id``
so concurrent conversations never clobber each other.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

#: Allowed step lifecycle states.
VALID_STATUSES: tuple[str, ...] = ("pending", "in_progress", "completed")

#: Glyphs used when rendering a plan as a checklist for the LLM / UI.
_STATUS_MARKS: dict[str, str] = {
    "pending": "[ ]",
    "in_progress": "[~]",
    "completed": "[x]",
}

#: Hard cap on the number of steps a single plan may contain.
MAX_STEPS: int = 30


@dataclass(slots=True)
class TaskStep:
    """A single todo-list entry.

    Attributes:
        description: Human-readable description of the step.
        status: One of :data:`VALID_STATUSES`.
    """

    description: str
    status: str = "pending"

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serialisable representation of the step."""
        return {"step": self.description, "status": self.status}


@dataclass(slots=True)
class TaskStore:
    """Thread-safe, per-conversation store of the active todo-list."""

    _plans: dict[str, list[TaskStep]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def set_plan(
        self, conversation_id: str, steps: list[TaskStep],
    ) -> list[TaskStep]:
        """Replace the task list for *conversation_id* and return a copy."""
        async with self._lock:
            self._plans[conversation_id] = list(steps)
            return list(steps)

    async def get_plan(self, conversation_id: str) -> list[TaskStep]:
        """Return a copy of the current task list (empty list if none)."""
        async with self._lock:
            return list(self._plans.get(conversation_id, []))

    async def clear(self, conversation_id: str) -> None:
        """Drop the task list for *conversation_id* (no-op if absent)."""
        async with self._lock:
            self._plans.pop(conversation_id, None)


def parse_steps(raw: object) -> list[TaskStep]:
    """Validate and coerce raw ``update_tasks`` arguments into steps.

    Accepts either a list of strings (each becomes a ``pending`` step) or a
    list of objects with ``step``/``description`` and optional ``status``.

    Args:
        raw: The value supplied for the ``tasks`` argument.

    Returns:
        A validated, non-empty list of :class:`TaskStep`.

    Raises:
        ValueError: If the payload is malformed or a status is invalid.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError("'tasks' must be a non-empty array of steps")
    if len(raw) > MAX_STEPS:
        raise ValueError(f"'tasks' must contain at most {MAX_STEPS} steps")

    steps: list[TaskStep] = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            description, status = item, "pending"
        elif isinstance(item, dict):
            description = str(
                item.get("step") or item.get("description") or "",
            )
            status = str(item.get("status", "pending"))
        else:
            raise ValueError(
                f"step {index}: must be a string or an object",
            )

        description = description.strip()
        if not description:
            raise ValueError(f"step {index}: empty description")
        if status not in VALID_STATUSES:
            raise ValueError(
                f"step {index}: invalid status '{status}' "
                f"(allowed: {', '.join(VALID_STATUSES)})",
            )
        steps.append(TaskStep(description=description, status=status))

    return steps


def render_tasks(steps: list[TaskStep]) -> str:
    """Render *steps* as a compact checklist string."""
    if not steps:
        return "(empty plan)"
    return "\n".join(
        f"{_STATUS_MARKS[step.status]} {step.description}" for step in steps
    )
