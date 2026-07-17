"""Composition root del motore greenfield (Agent v2, Fase 1, Task 16).

``run_agent_turn`` monta le 7 porte + retry policy + :class:`AgentEngine` a
partire dall'``AppContext`` di piattaforma e da una ``TurnRequest`` già
assemblata, poi esegue il turno. È l'UNICO punto in cui il motore greenfield
viene cablato ai servizi reali.

Due configurazioni di porte, selezionate dalla presenza di un ``transport``:

* **WebSocket** (``transport`` fornito): eventi via :class:`WsEventPort`
  (tradotti in frame wire dal translator di parità), interazioni via
  :class:`WsInteractionPort` (conferme/ask_user/client tool sul socket).
* **Headless/eval** (``transport is None``): eventi via
  :class:`SinkEventPort` sopra un ``WSEventSink`` iniettato (tipicamente il
  ``RecordingSink`` dell'eval harness o un ``NullEventSink``);
  interazioni auto-declinate da :class:`AutoDeclineInteractionPort` (nessuna
  UI da servire — la conferma diventa una negazione pulita, i tool
  client/ask_user un ``ToolResult`` d'errore).

PILASTRO: questo modulo NON importa ``backend.services.turn`` (lint enforced).
Il tipo del sink iniettato è descritto qui da un ``Protocol`` strutturale
locale (:class:`_EventSink`), non importato dal package legacy.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from loguru import logger

from backend.services.agent.adapters.context import ContextManagerAdapter
from backend.services.agent.adapters.db import SqlModelPersistence
from backend.services.agent.adapters.execution import ToolRegistryAdapter
from backend.services.agent.adapters.llm import LLMServiceAdapter
from backend.services.agent.adapters.parity import to_wire_frames
from backend.services.agent.adapters.permission import PermissionServiceAdapter
from backend.services.agent.adapters.ws import (
    WsEventPort,
    WsInteractionPort,
    WsTransport,
)
from backend.services.agent.engine import AgentEngine
from backend.services.agent.models import ToolInvocation, TurnOutcome, TurnRequest
from backend.services.agent.ports import (
    GateVerdict,
    InteractionOutcome,
    ToolExecutionOutput,
)
from backend.services.agent.retry import RetryPolicy

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlmodel.ext.asyncio.session import AsyncSession

    from backend.core.context import AppContext
    from backend.core.tool_registry import ToolRegistry
    from backend.services.agent.events import AgentEvent
    from backend.services.context_manager import ContextManager
    from backend.services.llm_service import LLMService

_HEADLESS_UNAVAILABLE = "interazione non disponibile in headless"


@runtime_checkable
class _EventSink(Protocol):
    """Tipo strutturale del sink iniettato (evita l'import di services.turn).

    Combacia con ``WSEventSink`` di piattaforma (``send`` + ``is_connected``):
    :class:`SinkEventPort` lo consuma senza dipendere dal package legacy.
    """

    async def send(self, event: dict[str, Any]) -> None: ...

    @property
    def is_connected(self) -> bool: ...


class SinkEventPort:
    """``EventPort`` sopra un ``WSEventSink`` iniettato (headless/eval).

    Traduce ogni ``AgentEvent`` in frame wire (translator di parità) e li
    consegna via ``sink.send``. Best-effort come da contratto ``EventPort``:
    non solleva MAI. Rispetta ``sink.is_connected`` (contratto eval §6.14:
    ``RecordingSink`` parte con ``is_connected=True``).
    """

    def __init__(
        self,
        sink: _EventSink,
        translator: Callable[[AgentEvent], list[dict[str, Any]]],
    ) -> None:
        """Inizializza la porta eventi.

        Args:
            sink: Il sink di destinazione (recording/null/…).
            translator: Mappa un ``AgentEvent`` in zero o più frame wire
                (``to_wire_frames``, l'adapter di parità).
        """
        self._sink = sink
        self._translator = translator

    async def emit(self, event: AgentEvent) -> None:
        """Emette un evento: ogni frame prodotto dal translator è inviato."""
        if not self._sink.is_connected:
            return
        try:
            frames = self._translator(event)
        except Exception:
            logger.exception("SinkEventPort: translator fallito; evento scartato")
            return
        for frame in frames:
            try:
                await self._sink.send(frame)
            except Exception:  # noqa: BLE001 — best-effort: mai sollevare
                logger.debug("SinkEventPort: send fallito; frame scartato")


class AutoDeclineInteractionPort:
    """``InteractionPort`` headless: nessuna UN, ogni interazione è declinata.

    * ``confirm_tool`` → :class:`InteractionOutcome.REJECTED` (il motore
      persiste la tool response sintetica di rifiuto e prosegue);
    * ``run_client_tool`` / ``ask_user`` → ``ToolExecutionOutput(ok=False)``
      con messaggio esplicito (il tool non può essere servito senza UI).
    """

    async def confirm_tool(
        self,
        call: ToolInvocation,
        *,
        verdict: GateVerdict,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> InteractionOutcome:
        """Nessuna UI per confermare: rifiuto pulito."""
        return InteractionOutcome.REJECTED

    async def run_client_tool(
        self,
        call: ToolInvocation,
        *,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput:
        """Nessun client per eseguire il tool UI-side: errore pulito."""
        return ToolExecutionOutput(
            ok=False, content=_HEADLESS_UNAVAILABLE, error=_HEADLESS_UNAVAILABLE,
        )

    async def ask_user(
        self,
        call: ToolInvocation,
        *,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput:
        """Nessun utente da interrogare: errore pulito."""
        return ToolExecutionOutput(
            ok=False, content=_HEADLESS_UNAVAILABLE, error=_HEADLESS_UNAVAILABLE,
        )


async def run_agent_turn(
    ctx: AppContext,
    *,
    request: TurnRequest,
    session: AsyncSession,
    transport: WsTransport | None,
    sink_fallback: _EventSink | None = None,
    cancel: asyncio.Event,
) -> TurnOutcome:
    """Composition root: costruisce porte + engine ed esegue il turno.

    Args:
        ctx: L'``AppContext`` di piattaforma (servizi, config).
        request: La ``TurnRequest`` già assemblata dal call site.
        session: Sessione async SQLModel del turno (unit-of-work del motore).
        transport: Il :class:`WsTransport` proprietario del socket, oppure
            ``None`` per un turno headless (eventi via ``sink_fallback``).
        sink_fallback: Sink degli eventi per il path headless/eval
            (``RecordingSink``/``NullEventSink``). Ignorato quando
            ``transport`` è fornito.
        cancel: Evento cooperativo di cancellazione del turno.

    Returns:
        Il ``TurnOutcome`` prodotto dal motore (mai un'eccezione: il motore
        cattura ogni fallimento e lo mappa nell'outcome).
    """
    # ``ctx`` espone i servizi come ``Protocol | None`` (o ``Any``); gli
    # adapter vogliono i tipi concreti. Al confine del composition root i
    # servizi sono garantiti presenti (il call site verifica ``llm_service``/
    # ``db``), quindi si restringe con ``cast`` — nessun controllo runtime
    # aggiuntivo qui.
    llm_service = cast("LLMService", ctx.llm_service)
    tool_registry = cast("ToolRegistry", ctx.tool_registry)
    context_manager = cast("ContextManager", ctx.context_manager)

    llm_port = LLMServiceAdapter(llm_service)
    permission_port = PermissionServiceAdapter(
        permission_service=ctx.permission_service,
        mode_service=ctx.permission_mode_service,
        tool_registry=tool_registry,
        conversation_id=request.conversation_id,
    )
    execution_port = ToolRegistryAdapter(
        tool_registry, default_timeout_s=ctx.config.llm.tool_execution_timeout,
    )
    context_port = ContextManagerAdapter(
        context_manager, llm_service, ctx.config.llm,
    )
    persistence = SqlModelPersistence(
        session=session,
        conversation_id=request.conversation_id,
        artifact_registry=ctx.artifact_registry,
        version_group_id=request.version_group_id,
        version_index=request.version_index,
    )

    if transport is not None:
        event_port: Any = WsEventPort(transport, to_wire_frames)
        interaction_port: Any = WsInteractionPort(transport)
    else:
        sink = sink_fallback if sink_fallback is not None else _DropSink()
        event_port = SinkEventPort(sink, to_wire_frames)
        interaction_port = AutoDeclineInteractionPort()

    engine = AgentEngine(
        llm=llm_port,
        permissions=permission_port,
        interaction=interaction_port,
        events=event_port,
        persistence=persistence,
        context=context_port,
        execution=execution_port,
        retry=RetryPolicy(),
        confirmation_timeout_s=float(ctx.config.permissions.confirmation_timeout_s),
    )
    return await engine.run(request, cancel=cancel)


class _DropSink:
    """Sink di riserva: connesso ma silenzioso (se nessun sink è iniettato)."""

    async def send(self, event: dict[str, Any]) -> None:
        return None

    @property
    def is_connected(self) -> bool:
        return True
