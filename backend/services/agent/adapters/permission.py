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
se il tool non è risolvibile nel registry).

Fix review T12 (bare tool name): la ``ToolDefinition`` è recuperata con
``_tool_lookup.resolve_tool_definition`` (condivisa con
``ToolRegistryAdapter``), non più con un match esatto — un nome "nudo" (es.
``"remember"`` per ``"memory_remember"``) ora produce lo stesso ``tool_def``
(quindi lo stesso ``risk_level``/capability nel gate) che produrrebbe il nome
namespaced completo, invece di gated con ``tool_def=None`` (decisione più
debole).

Fix review olistica M1 (nome nudo passato a ``PermissionService.decide``):
il nome RISOLTO (namespaced) — non più ``call.name`` — è passato come
``tool_name`` a ``PermissionService.decide``. Rules/grants per-conversazione
sono keyed sul nome namespaced (es. ``"memory_remember"``); passare il nome
nudo emesso dal modello (``"remember"``) faceva sì che una regola/grant su
``memory_remember`` non facesse mai match. Se la risoluzione fallisce (nome
sconosciuto o suffisso ambiguo), fallback al nome nudo originale — stesso
comportamento di prima per i tool non risolvibili.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from backend.services.agent.adapters._tool_lookup import resolve_tool_definition
from backend.services.agent.models import ToolInvocation
from backend.services.agent.ports import GateAction, GateVerdict, RememberScope
from backend.services.permission_rules import RuleEffect
from backend.services.permission_service import GateAction as PlatformGateAction

if TYPE_CHECKING:
    from backend.core.tool_registry import ToolRegistry
    from backend.services.permission_mode_service import PermissionModeService
    from backend.services.permission_rules import PermissionRuleService
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
        rule_service: PermissionRuleService,
        conversation_id: str,
    ) -> None:
        """Inizializza l'adapter.

        Args:
            permission_service: Autorità centrale dei permessi (piattaforma).
            mode_service: Servizio del tier di permesso per-conversazione.
            tool_registry: Registro tool, per recuperare la ``ToolDefinition``
                di ogni chiamata (fresca a ogni ``decide``, mai cache).
            rule_service: Servizio delle regole persistite — destinazione
                della scelta "ricorda" delle conferme (``remember_approval``).
            conversation_id: ID di conversazione di default per questo adapter
                (documentale — il metodo ``decide`` usa comunque il
                ``conversation_id`` ricevuto per-call, come da ``PermissionPort``).
        """
        self._permission_service = permission_service
        self._mode_service = mode_service
        self._tool_registry = tool_registry
        self._rule_service = rule_service
        self._conversation_id = conversation_id

    async def decide(
        self, call: ToolInvocation, *, conversation_id: str,
    ) -> GateVerdict:
        """Risolve una ``ToolInvocation`` a ``EXECUTE``/``DENY``/``CONFIRM``.

        Recupera mode e ``ToolDefinition`` correnti a OGNI chiamata (nessuna
        cache), poi delega a ``PermissionService.decide``. La
        ``ToolDefinition`` è risolta tollerando i bare tool name (stessa
        regola unique-suffix della piattaforma — vedi
        ``_tool_lookup.resolve_tool_definition``).
        """
        mode = self._mode_service.get_mode(conversation_id)
        resolved = resolve_tool_definition(self._tool_registry, call.name)
        tool_name = resolved[0] if resolved is not None else call.name
        tool_def = resolved[1] if resolved is not None else None
        decision = self._permission_service.decide(
            tool_name=tool_name,
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

    async def remember_approval(
        self,
        call: ToolInvocation,
        *,
        conversation_id: str,
        scope: RememberScope,
    ) -> None:
        """Persiste la scelta "ricorda" di una conferma approvata come regola.

        Mapping (fix smoke Fase 1 — la scelta era scartata in
        ``adapters/ws.py`` e nessuna regola veniva mai creata):

        * ``CONVERSATION`` → regola ``allow`` scoped alla conversazione;
        * ``PERSISTENT``   → regola ``allow`` globale;
        * ``NONE``         → no-op.

        La regola è keyed sul nome NAMESPACED risolto (stessa regola del fix
        M1 su ``decide``: rules/grants keyed sul nome bare non farebbero mai
        match nel gate). Best-effort come da contratto ``PermissionPort``: un
        errore di persistenza è loggato, mai propagato — la call è già stata
        approvata dall'utente e deve proseguire.
        """
        if scope is RememberScope.NONE:
            return
        resolved = resolve_tool_definition(self._tool_registry, call.name)
        tool_name = resolved[0] if resolved is not None else call.name
        try:
            await self._rule_service.add_rule(
                tool_name=tool_name,
                effect=RuleEffect.ALLOW,
                conversation_id=(
                    conversation_id if scope is RememberScope.CONVERSATION else None
                ),
            )
        except Exception:  # noqa: BLE001 — best-effort: mai far fallire la call approvata
            logger.exception(
                "remember_approval fallita: tool={} scope={} (regola non salvata)",
                tool_name, scope.value,
            )
