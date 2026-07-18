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

Presence of the planning meta-tools is definition-driven: a
:class:`~backend.core.plugin_models.ToolDefinition` marked ``always_offered``
survives every selection and capability-blocking pass on its own — no
name-based allow-list is needed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.permission_mode_service import PermissionMode

# Capability tags withheld from the offered toolset in a read-only tier.  These
# are exactly the capabilities the gate denies in ``plan`` mode
# (``PermissionService.decide`` step 5: ``is_write or is_exec`` or an MCP write
# — ``mcp_write``, Fase 2 MCP perimeter), so withholding them keeps the toolset
# honest — the model is never shown an action it cannot take in this tier.
_READ_ONLY_BLOCKED_CAPABILITIES: frozenset[str] = frozenset(
    {"fs_write", "process_exec", "mcp_write"}
)

# Plugin owning the planning meta-tools.  Floated to the front in ``plan``
# mode so the model leads with planning (presence itself is guaranteed by
# ``always_offered`` on the tool definitions).
_PLANNING_PLUGINS: tuple[str, ...] = ("agent",)


@dataclass(frozen=True, slots=True)
class ModePolicy:
    """How a permission tier shapes the agent for a turn.

    Attributes:
        mode: The tier this policy is for.
        blocked_capabilities: Capability tags whose tools are withheld from the
            offered toolset (empty ⇒ withhold nothing).
        priority_plugins: Plugins whose tools are guaranteed present and floated
            to the front of the toolset (empty ⇒ no reordering).
        guidance: A system-prompt block (markdown body, no header) steering the
            model's behaviour in this tier.  May be empty.
    """

    mode: PermissionMode
    blocked_capabilities: frozenset[str]
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
        "Stai operando in modalità **plan** (sola lettura). **Non puoi "
        "scrivere file né eseguire comandi**: questi strumenti non ti sono "
        "stati forniti apposta. Il tuo compito è capire e pianificare: leggi "
        "e ispeziona ciò che ti serve e definisci il piano con gli strumenti "
        "di pianificazione. Quando il piano è pronto, invita l'utente a "
        "passare a una modalità operativa (auto-edits o autopilot) per "
        "eseguirlo."
    ),
    PermissionMode.AUTOPILOT: (
        "Stai operando in modalità **autopilot**. Hai piena autonomia e "
        "**non verrà chiesta alcuna conferma**: procedi end-to-end fino a "
        "completare l'obiettivo, restando sempre dentro l'ambito di lavoro."
    ),
}


def policy_for(
    mode: PermissionMode,
    *,
    custom_guidance: dict[PermissionMode, str] | None = None,
) -> ModePolicy:
    """Return the :class:`ModePolicy` that shapes the agent for *mode*.

    ``plan`` is the only tier that reshapes the toolset (read-only ⇒ withhold
    write/exec tools, lead with the planning tools); every tier contributes a
    behavioural ``guidance`` block.

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
            priority_plugins=_PLANNING_PLUGINS,
            guidance=overrides.get(mode) or _GUIDANCE[mode],
        )
    return ModePolicy(
        mode=mode,
        blocked_capabilities=frozenset(),
        priority_plugins=(),
        guidance=overrides.get(mode) or _GUIDANCE.get(mode, ""),
    )
