"""AL\\CE — Behavioural policy derived from a permission tier (Fase 7 extension).

The :class:`~backend.services.permission_mode_service.PermissionMode` tier the
user picks per conversation governs the *gate* (whether a given tool-call may
run).  This module turns that same tier into how the agent should be **shaped
up-front**, so the choice changes the agent's behaviour rather than only
denying calls after the model has already decided to make them:

* which tools are even offered (``blocked_capabilities`` — withheld from the
  toolset because the gate would deny them anyway), and which are floated to the
  front (``priority_plugins``);
* a system-prompt block (``guidance``) that tells the model, in plain language,
  what it may and may not do in this tier — so it *leads* with the right
  behaviour instead of trying blocked actions and getting bounced.

Keeping the whole tier → behaviour mapping in one small, pure, dependency-light
module means the steering for every tier can be reviewed and tuned in one place.

``always_allow_tools`` guarantees the planning meta-tools survive the
capability-blocking pass even if they were ever to gain a blocked capability —
the tier owns its offered toolset, so a planning tool can never be withheld out
from under it.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.permission_mode_service import PermissionMode

# Capability tags withheld from the offered toolset in a read-only tier.  These
# are exactly the capabilities the gate denies in ``plan`` mode
# (``PermissionService.decide`` step 5: ``is_write or is_exec``), so withholding
# them keeps the toolset honest — the model is never shown an action it cannot
# take in this tier.
_READ_ONLY_BLOCKED_CAPABILITIES: frozenset[str] = frozenset(
    {"fs_write", "process_exec"}
)

# Plugin whose tools are the *planning* meta-tools (``update_tasks`` /
# ``spawn_subagent`` / ``ask_user``).  Floated to the front — and guaranteed
# present — in ``plan`` mode so the model leads with planning.
_PLANNING_PLUGINS: tuple[str, ...] = ("agent",)

# Namespaced planning meta-tool names that must survive the capability-blocking
# pass in ``plan`` mode.  The tier owns its toolset: these are always offered
# even if one of them were ever to declare a blocked capability.
_PLANNING_TOOLS: frozenset[str] = frozenset(
    {
        "agent_update_tasks",
        "agent_write_plan",
        "agent_spawn_subagent",
        "agent_ask_user",
    }
)


@dataclass(frozen=True, slots=True)
class ModePolicy:
    """How a permission tier shapes the agent for a turn.

    Attributes:
        mode: The tier this policy is for.
        blocked_capabilities: Capability tags whose tools are withheld from the
            offered toolset (empty ⇒ withhold nothing).
        always_allow_tools: Namespaced tool names that must survive the
            capability-blocking pass even if they declare a blocked capability
            (empty ⇒ no exceptions).  Lets the tier guarantee its own meta-tools.
        priority_plugins: Plugins whose tools are guaranteed present and floated
            to the front of the toolset (empty ⇒ no reordering).
        guidance: A system-prompt block (markdown body, no header) steering the
            model's behaviour in this tier.  May be empty.
    """

    mode: PermissionMode
    blocked_capabilities: frozenset[str]
    always_allow_tools: frozenset[str]
    priority_plugins: tuple[str, ...]
    guidance: str


# Per-tier behavioural steering injected into the system prompt.  Italian to
# match the rest of Alice's prompt surface.
_GUIDANCE: dict[PermissionMode, str] = {
    PermissionMode.STRICT: (
        "Stai operando in modalità **strict**. Prima di ogni scrittura su file "
        "o comando di sistema, l'app chiederà conferma all'utente: proponi pure "
        "le azioni: verranno eseguite dopo l'ok. Le sole letture non richiedono "
        "conferma. Non dare per scontato di poter agire senza approvazione."
    ),
    PermissionMode.AUTO_EDITS: (
        "Stai operando in modalità **auto-edits**. Puoi creare e modificare file "
        "dentro l'ambito di lavoro **senza chiedere conferma**: agisci con "
        "autonomia sulle modifiche ai file. Per i comandi di sistema/processi e "
        "per le azioni classificate come rischiose serve comunque conferma."
    ),
    PermissionMode.PLAN: (
        "Stai operando in modalità **plan** (sola lettura). **Non puoi scrivere "
        "file né eseguire comandi**: questi strumenti non ti sono stati forniti "
        "apposta. Il tuo compito è capire e pianificare: usa `update_tasks` per "
        "costruire un piano passo-passo, leggi e ispeziona ciò che ti serve, e "
        "descrivi con precisione le azioni che eseguirai. Quando il piano è "
        "pronto, invita l'utente a passare a una modalità operativa "
        "(auto-edits o autopilot) per eseguirlo."
    ),
    PermissionMode.AUTOPILOT: (
        "Stai operando in modalità **autopilot**. Hai piena autonomia e **non "
        "verrà chiesta alcuna conferma**: procedi end-to-end fino a completare "
        "l'obiettivo, restando sempre dentro l'ambito di lavoro. Per un lavoro "
        "non banale usa `update_tasks` per tracciare i passi mentre li esegui."
    ),
}


def policy_for(
    mode: PermissionMode,
    *,
    custom_guidance: dict[PermissionMode, str] | None = None,
) -> ModePolicy:
    """Return the :class:`ModePolicy` that shapes the agent for *mode*.

    ``plan`` is the only tier that reshapes the toolset (read-only ⇒ withhold
    write/exec tools, lead with — and always allow — the planning tools); every
    tier contributes a behavioural ``guidance`` block.

    Args:
        mode: The conversation's permission tier.
        custom_guidance: Optional per-tier guidance overrides.  When a tier is
            present (and non-empty), its text replaces the built-in default;
            tiers absent from the mapping fall back to ``_GUIDANCE``.

    Returns:
        The behavioural policy for *mode*.
    """
    overrides = custom_guidance or {}
    if mode is PermissionMode.PLAN:
        return ModePolicy(
            mode=mode,
            blocked_capabilities=_READ_ONLY_BLOCKED_CAPABILITIES,
            always_allow_tools=_PLANNING_TOOLS,
            priority_plugins=_PLANNING_PLUGINS,
            guidance=overrides.get(mode) or _GUIDANCE[mode],
        )
    return ModePolicy(
        mode=mode,
        blocked_capabilities=frozenset(),
        always_allow_tools=frozenset(),
        priority_plugins=(),
        guidance=overrides.get(mode) or _GUIDANCE.get(mode, ""),
    )
