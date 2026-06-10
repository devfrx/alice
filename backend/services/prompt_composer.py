"""AL\\CE — System-prompt dynamic-context composer.

Owns the ORDER of the dynamic blocks injected into the system prompt for a
turn, in one pure, dependency-light module (same spirit as
``permission_mode_policy``): scope/tier steering leads, the orchestration
contract follows, auxiliary context (memories / MCP / whiteboards) sits in
the middle, and the in-flight plan document + task checklist close the
prompt — recency keeps the model continuing the work it already planned.

The orchestration block is composed ONLY from the ``usage_guidance``
fragments of tools actually offered this turn (see
``ToolRegistry.usage_guidance_for``), so the prompt never teaches a tool
the model cannot call — the invariant holds by construction, not by
review.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Fixed intro line of the ``[ORCHESTRAZIONE]`` block. Italian to match the
#: rest of Alice's prompt surface.
_ORCHESTRATION_INTRO = (
    "Questi strumenti orchestrano il tuo lavoro e alimentano pannelli "
    "dedicati dell'interfaccia. Regole vincolanti:"
)


def build_orchestration_block(fragments: Sequence[str]) -> str | None:
    """Render the ``[ORCHESTRAZIONE]`` system-prompt block.

    Args:
        fragments: ``usage_guidance`` texts of the tools offered this
            turn, in toolset order.

    Returns:
        The rendered block, or ``None`` when there is nothing to teach.
    """
    items = [f.strip() for f in fragments if f and f.strip()]
    if not items:
        return None
    bullets = "\n".join(f"- {item}" for item in items)
    return (
        "[ORCHESTRAZIONE]\n"
        f"{_ORCHESTRATION_INTRO}\n"
        f"{bullets}\n"
        "[/ORCHESTRAZIONE]"
    )


def compose_dynamic_context(
    *,
    permission_block: str | None = None,
    orchestration_block: str | None = None,
    aux_context: str | None = None,
    plan_document_block: str | None = None,
    task_steps_block: str | None = None,
) -> str | None:
    """Join the dynamic system-prompt blocks in their declared order.

    The order is the module's contract:

    1. ``permission_block`` — workspace scope + tier steering (leads).
    2. ``orchestration_block`` — the meta-tool contract.
    3. ``aux_context`` — memories, MCP servers, whiteboards (pre-merged).
    4. ``plan_document_block`` — the living plan document.
    5. ``task_steps_block`` — the task checklist (closes the prompt).

    Args:
        permission_block: ``[AMBITO DI LAVORO]`` / ``[MODALITÀ OPERATIVA]``.
        orchestration_block: ``[ORCHESTRAZIONE]``.
        aux_context: Auxiliary context already merged by the caller.
        plan_document_block: Rendered plan document, if any.
        task_steps_block: Rendered task checklist, if any.

    Returns:
        The joined context, or ``None`` when every block is empty.
    """
    blocks = (
        permission_block,
        orchestration_block,
        aux_context,
        plan_document_block,
        task_steps_block,
    )
    parts = [b.strip() for b in blocks if b and b.strip()]
    if not parts:
        return None
    return "\n\n".join(parts)
