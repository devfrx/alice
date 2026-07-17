"""Adapter ``PermissionPort`` -> ``PermissionService`` + ``PermissionModeService``.

Risolve il mode della conversazione **a ogni chiamata** (invariante §6.9: il
turn engine legge il tier sincronicamente per ogni tool-call, mai una volta
sola all'inizio del turno — così un cambio di mode a metà turno si applica
immediatamente alla prossima tool-call). ``PermissionModeService.get_mode``
(``backend/services/permission_mode_service.py:170``) è sincrono e non solleva
mai (default ``strict`` per conversazioni senza mode esplicito).

``PermissionService.decide`` (``backend/services/permission_service.py:228``)
è anch'esso **sincrono** (non una coroutine) — l'adapter lo richiama
direttamente dentro il metodo ``async def decide`` richiesto dal
``PermissionPort``.

Mapping ``GateAction`` (piattaforma -> motore), come da brief:
    ALLOW              -> EXECUTE
    DENY               -> DENY
    NEEDS_CONFIRMATION -> CONFIRM

``GateVerdict.outcome`` = ``decision.outcome.value`` (stringa dell'enum
``PermissionOutcome``); ``reason`` propagato verbatim. ``risk_level`` e
``description`` sono popolati best-effort dalla ``ToolDefinition`` (``None``
se il tool non esiste nel registry).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.services.agent.models import ToolInvocation
from backend.services.agent.ports import GateAction, GateVerdict
from backend.services.permission_service import GateAction as PlatformGateAction

if TYPE_CHECKING:
    from backend.core.tool_registry import ToolRegistry
    from backend.services.permission_mode_service import PermissionModeService
    from backend.services.permission_service import PermissionService

_ACTION_MAP: dict[PlatformGateAction, GateAction] = {
    PlatformGateAction.ALLOW: GateAction.EXECUTE,
    PlatformGateAction.DENY: GateAction.DENY,
    PlatformGateAction.NEEDS_CONFIRMATION: GateAction.CONFIRM,
}


class PermissionServiceAdapter:
    """Implementa ``PermissionPort`` sopra ``PermissionService`` + mode service."""

    def __init__(
        self,
        *,
        permission_service: PermissionService,
        mode_service: PermissionModeService,
        tool_registry: ToolRegistry,
        conversation_id: str,
    ) -> None:
        """Inizializza l'adapter.

        Args:
            permission_service: Autorità centrale dei permessi (piattaforma).
            mode_service: Servizio del tier di permesso per-conversazione.
            tool_registry: Registro tool, per recuperare la ``ToolDefinition``
                di ogni chiamata (fresca a ogni ``decide``, mai cache).
            conversation_id: ID di conversazione di default per questo adapter
                (documentale — il metodo ``decide`` usa comunque il
                ``conversation_id`` ricevuto per-call, come da ``PermissionPort``).
        """
        self._permission_service = permission_service
        self._mode_service = mode_service
        self._tool_registry = tool_registry
        self._conversation_id = conversation_id

    async def decide(
        self, call: ToolInvocation, *, conversation_id: str,
    ) -> GateVerdict:
        """Risolve una ``ToolInvocation`` a ``EXECUTE``/``DENY``/``CONFIRM``.

        Recupera mode e ``ToolDefinition`` correnti a OGNI chiamata (nessuna
        cache), poi delega a ``PermissionService.decide``.
        """
        mode = self._mode_service.get_mode(conversation_id)
        tool_def = self._tool_registry.get_tool_definition(call.name)
        decision = self._permission_service.decide(
            tool_name=call.name,
            args=call.args,
            tool_def=tool_def,
            conversation_id=conversation_id,
            mode=mode,
        )
        return GateVerdict(
            action=_ACTION_MAP[decision.action],
            outcome=decision.outcome.value,
            reason=decision.reason,
            risk_level=tool_def.risk_level if tool_def is not None else None,
            description=tool_def.description if tool_def is not None else None,
        )
