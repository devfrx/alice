"""Trasporto WS greenfield: read-pump unico, attese correlate, send fail-safe.

``WsTransport`` è il PROPRIETARIO del socket (invariante §6.6: un solo lettore).
Un unico task asyncio (il read-pump) consuma ``receive_json()`` e smista per
``type``:

* ``cancel`` → set dell'evento cancel del turno corrente + risoluzione a
  ``None`` di tutte le attese pendenti (esito cancel);
* ``interaction.response`` → risolve il Future dell'interazione correlata per
  ``interaction_id``; se l'id è sconosciuto (risposta stale) il frame è
  scartato con log, NON accodato come messaggio utente;
* qualsiasi altro frame → coda consumata da ``next_user_message()`` (giro
  turni in ``ws.py``).

Il frame di RICHIESTA di un'interazione NON nasce qui: è l'evento canonico
``interaction.requested`` che il motore emette via ``EventPort`` (tradotto
dal translator iniettato, ``to_v2_frames`` di ``api/ws_schema/wire.py``)
PRIMA di chiamare la porta. Le porte non costruiscono
alcun frame outbound; il bridge ``correlation_id``/``alt_key`` è morto.

Su ``WebSocketDisconnect``/``RuntimeError`` (socket chiuso) il pump marca il
trasporto disconnesso, risolve tutte le attese pendenti con
``EngineDisconnected`` e spinge una sentinella ``None`` nella coda utente.

``send_json`` non solleva MAI: su qualunque errore di invio marca disconnesso
e inghiotte — il motore apprende della disconnessione dai percorsi d'attesa
delle porte (o da ``connected``), mai dall'emissione eventi (fire-and-forget).

Precedenza nella race di ``wait_response``: disconnect > cancel > timeout. La
disconnessione risolve il Future pendente in modo eccezionale, quindi vince
anche quando cancel/timeout scattano nello stesso giro di loop.

Le porte:

* ``WsEventPort`` implementa ``EventPort``: traduce ogni ``AgentEvent`` in
  zero o più frame wire v2 (via il translator iniettato dal call site api)
  e li invia best-effort via ``send_json``.
* ``WsInteractionPort`` implementa ``InteractionPort`` attendendo la
  ``interaction.response`` correlata per ``interaction_id``. NON emette e NON
  costruisce frame: la richiesta è l'evento del motore (un evento = un fatto
  del turno). ``confirm_tool`` cattura ``EngineDisconnected`` e ritorna
  ``InteractionOutcome.DISCONNECTED`` come DATO (adjudicazione review T4: il
  motore persiste la tool response sintetica prima di fermarsi);
  ``run_client_tool``/``ask_user`` la PROPAGANO (§6.5: il loro tipo di ritorno
  non può codificarla).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from loguru import logger
from starlette.websockets import WebSocketDisconnect

from backend.services.agent.models import ToolInvocation
from backend.services.agent.ports import (
    ConfirmationResult,
    EngineDisconnected,
    GateVerdict,
    InteractionOutcome,
    RememberScope,
    ToolExecutionOutput,
)

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

    from backend.services.agent.events import AgentEvent


class WsTransport:
    """Proprietario del socket: UNICO lettore, send fail-safe, attese correlate."""

    def __init__(self, websocket: WebSocket) -> None:
        """Inizializza il trasporto sopra un socket già accettato.

        Args:
            websocket: Il ``WebSocket`` Starlette (o un doppio con lo stesso
                contratto ``receive_json``/``send_json``).
        """
        self._ws = websocket
        # Attese pendenti keyed by ``interaction_id`` (la chiave di
        # correlazione wire v2: motore genera → emette in interaction.requested
        # → passa alla porta → il pump risolve sulla interaction.response).
        self._pending: dict[str, asyncio.Future[dict[str, Any] | None]] = {}
        self._user_messages: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._connected = True
        self._disconnected_event = asyncio.Event()
        self._cancel = asyncio.Event()
        self._pump_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        """True finché il socket non risulta caduto o chiuso."""
        return self._connected

    def begin_turn(self) -> asyncio.Event:
        """Crea e ritorna un NUOVO evento cancel per il turno che inizia.

        Lo stato di cancel non trapela mai tra turni: ogni turno ha il suo
        evento fresco; il pump setta sempre quello corrente.
        """
        self._cancel = asyncio.Event()
        return self._cancel

    async def start(self) -> None:
        """Avvia il read-pump (idempotente: un solo task, mai due lettori)."""
        if self._pump_task is None:
            self._pump_task = asyncio.create_task(
                self._read_pump(), name="ws-transport-read-pump",
            )

    async def aclose(self) -> None:
        """Ferma il pump e marca il trasporto chiuso (attese pendenti sbloccate)."""
        task = self._pump_task
        self._pump_task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._mark_disconnected()

    async def send_json(self, payload: dict[str, Any]) -> None:
        """Invia un frame al client. NON solleva mai.

        Su qualunque errore di invio (socket chiuso incluso) marca il
        trasporto disconnesso e inghiotte l'errore: l'emissione è
        fire-and-forget, il motore apprende della caduta altrove.
        """
        if not self._connected:
            return
        try:
            await self._ws.send_json(payload)
        except Exception as exc:
            logger.debug("WsTransport: send fallito ({}); marco disconnesso", exc)
            self._mark_disconnected()

    async def wait_response(
        self,
        interaction_id: str,
        *,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> dict[str, Any] | None:
        """Attende il frame ``interaction.response`` correlato a ``interaction_id``.

        Il frame di RICHIESTA è già sul wire (l'evento ``interaction.requested``
        del motore, emesso via ``EventPort`` PRIMA di chiamare la porta): qui si
        registra il waiter e si attende. La registrazione è SINCRONA (prima di
        qualunque await): unita all'invariante del motore "nessun await tra
        l'emit del requested e la chiamata alla porta", garantisce che una
        risposta non possa arrivare al pump prima che il waiter esista.

        Race con precedenza disconnect > cancel > timeout (invariata):

        * disconnessione → solleva ``EngineDisconnected`` (anche se registrata a
          socket già caduto: fast path immediato dopo cleanup);
        * cancel (evento o frame ``cancel``) → ``None``;
        * timeout → ``None``.

        L'entry pendente è ripulita in TUTTI i percorsi di uscita.

        Args:
            interaction_id: Chiave di correlazione dell'interazione.
            timeout_s: Timeout di attesa della risposta.
            cancel: Evento cooperativo di cancellazione del turno.

        Returns:
            Il frame di risposta, oppure ``None`` su cancel/timeout.

        Raises:
            EngineDisconnected: se il client cade prima della risposta (o è
                già caduto quando si registra il waiter).
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any] | None] = loop.create_future()
        self._pending[interaction_id] = future
        if not self._connected:
            # Registrato a socket già caduto: esito disconnect immediato.
            self._pending.pop(interaction_id, None)
            raise EngineDisconnected("client WS disconnesso")
        disconnect_waiter = asyncio.create_task(self._disconnected_event.wait())
        cancel_waiter = asyncio.create_task(cancel.wait())
        try:
            waiters: set[asyncio.Future[Any]] = {future, disconnect_waiter, cancel_waiter}
            await asyncio.wait(
                waiters, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED,
            )
            if future.done():
                # Risposta reale, ``None`` da frame cancel, oppure
                # EngineDisconnected impostata dal pump (che vince sempre).
                return future.result()
            if disconnect_waiter.done():
                raise EngineDisconnected(
                    f"client WS caduto in attesa di interaction.response "
                    f"({interaction_id})"
                )
            # cancel o timeout: entrambi → None.
            if not cancel_waiter.done():
                logger.debug(
                    "WsTransport: interaction {} scaduta dopo {}s",
                    interaction_id, timeout_s,
                )
            return None
        finally:
            self._pending.pop(interaction_id, None)
            if not future.done():
                future.cancel()
            disconnect_waiter.cancel()
            cancel_waiter.cancel()

    async def next_user_message(self) -> dict[str, Any] | None:
        """Prossimo frame utente non smistato altrove; ``None`` a fine socket."""
        if not self._connected and self._user_messages.empty():
            return None
        return await self._user_messages.get()

    # ------------------------------------------------------------------
    # Read-pump
    # ------------------------------------------------------------------

    async def _read_pump(self) -> None:
        """UNICO lettore del socket: consuma e smista i frame inbound."""
        try:
            while True:
                try:
                    frame = await self._ws.receive_json()
                except ValueError:
                    # JSON malformato dal client: scarta e prosegui.
                    logger.debug("WsTransport: frame JSON invalido scartato")
                    continue
                if isinstance(frame, dict):
                    self._dispatch(frame)
                else:
                    logger.debug("WsTransport: frame non-oggetto scartato")
        except WebSocketDisconnect:
            logger.debug("WsTransport: client disconnesso")
        except RuntimeError as exc:
            # Starlette solleva RuntimeError sul receive di un socket chiuso.
            logger.debug("WsTransport: socket chiuso ({})", exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("WsTransport: errore inatteso nel read-pump")
        finally:
            self._mark_disconnected()

    def _dispatch(self, frame: dict[str, Any]) -> None:
        """Smista un frame inbound: cancel, interaction.response, o messaggio utente."""
        if frame.get("type") == "cancel":
            self._cancel.set()
            self._resolve_all_pending_to_none()
            return
        if frame.get("type") == "interaction.response":
            interaction_id = frame.get("interaction_id")
            future = self._pending.pop(str(interaction_id), None)
            if future is None:
                logger.warning(
                    "WsTransport: interaction.response stale scartata "
                    "(interaction_id={})", interaction_id,
                )
                return
            if not future.done():
                future.set_result(frame)
            return
        self._user_messages.put_nowait(frame)

    def _resolve_all_pending_to_none(self) -> None:
        """Risoluzione a ``None`` (esito cancel) di tutte le attese pendenti."""
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_result(None)

    def _mark_disconnected(self) -> None:
        """Marca il trasporto caduto: pendenti → EngineDisconnected, sentinella."""
        if not self._connected:
            return
        self._connected = False
        self._disconnected_event.set()
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(
                    EngineDisconnected("client WS disconnesso"),
                )
        self._user_messages.put_nowait(None)


class WsEventPort:
    """``EventPort`` sul trasporto WS: traduce e invia best-effort, mai solleva."""

    def __init__(
        self,
        transport: WsTransport,
        translator: Callable[[AgentEvent], list[dict[str, Any]]],
    ) -> None:
        """Inizializza la porta eventi.

        Args:
            transport: Il trasporto WS proprietario del socket.
            translator: Mappa un ``AgentEvent`` in zero o più frame wire v2
                (tipicamente ``to_v2_frames`` da ``api/ws_schema/wire.py``,
                iniettato dal call site api).
        """
        self._transport = transport
        self._translator = translator

    async def emit(self, event: AgentEvent) -> None:
        """Emette un evento: ogni frame prodotto dal translator è inviato.

        Best-effort come da ``EventPort``: un translator che solleva viene
        loggato e ignorato; ``send_json`` non solleva mai per contratto.
        """
        try:
            frames = self._translator(event)
        except Exception:
            logger.exception("WsEventPort: translator fallito; evento scartato")
            return
        for frame in frames:
            await self._transport.send_json(frame)


class WsInteractionPort:
    """``InteractionPort`` sul trasporto WS, vocabolario v2.

    NON costruisce frame outbound: il frame di richiesta è l'evento
    ``interaction.requested`` emesso dal MOTORE (un evento = un fatto del
    turno). Qui solo l'attesa correlata per ``interaction_id`` e la decodifica
    della ``interaction.response``.
    """

    def __init__(self, transport: WsTransport) -> None:
        """Inizializza la porta interazioni.

        Args:
            transport: Il trasporto WS proprietario del socket.
        """
        self._transport = transport

    async def confirm_tool(
        self,
        call: ToolInvocation,
        *,
        interaction_id: str,
        verdict: GateVerdict,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> ConfirmationResult:
        """Attende l'esito della conferma per ``interaction_id``.

        Su disconnessione ritorna ``DISCONNECTED`` come DATO (adjudicazione
        T4): il motore persiste la tool response sintetica prima di fermarsi.

        La scelta ``remember`` del frame è decodificata SOLO su approvazione
        (una call declinata non va mai ricordata) e normalizzata a ``NONE``
        per valori fuori dal vocabolario wire — il frame inbound non passa da
        una validazione Pydantic, la porta è l'ultimo presidio.
        """
        try:
            response = await self._transport.wait_response(
                interaction_id, timeout_s=timeout_s, cancel=cancel,
            )
        except EngineDisconnected:
            return ConfirmationResult(outcome=InteractionOutcome.DISCONNECTED)
        if response is None:
            if cancel.is_set():
                return ConfirmationResult(outcome=InteractionOutcome.CANCELLED)
            return ConfirmationResult(outcome=InteractionOutcome.TIMEOUT)
        if not bool(response.get("approved")):
            return ConfirmationResult(outcome=InteractionOutcome.REJECTED)
        raw_remember = response.get("remember")
        try:
            remember = RememberScope(raw_remember) if raw_remember else RememberScope.NONE
        except ValueError:
            remember = RememberScope.NONE
        return ConfirmationResult(
            outcome=InteractionOutcome.APPROVED, remember=remember,
        )

    async def run_client_tool(
        self,
        call: ToolInvocation,
        *,
        interaction_id: str,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput:
        """Delegazione al client di un tool UI-side; attende per ``interaction_id``.

        Raises:
            EngineDisconnected: se il client cade prima del risultato (il
                tipo di ritorno non può codificarla; il motore la gestisce).
        """
        response = await self._transport.wait_response(
            interaction_id, timeout_s=timeout_s, cancel=cancel,
        )
        if response is None:
            return self._interrupted_output(call, cancel)
        success = bool(response.get("success", False))
        raw_result = response.get("result")
        if isinstance(raw_result, str):
            content = raw_result
        elif raw_result is None:
            content = ""
        else:
            content = json.dumps(raw_result, ensure_ascii=False)
        error = response.get("error")
        if success:
            return ToolExecutionOutput(ok=True, content=content)
        return ToolExecutionOutput(
            ok=False,
            content=content,
            error=str(error) if error else "esecuzione client fallita",
        )

    async def ask_user(
        self,
        call: ToolInvocation,
        *,
        interaction_id: str,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput:
        """Attende le risposte del wizard ``ask_user`` per ``interaction_id``.

        Raises:
            EngineDisconnected: se il client cade prima delle risposte.
        """
        response = await self._transport.wait_response(
            interaction_id, timeout_s=timeout_s, cancel=cancel,
        )
        if response is None:
            return self._interrupted_output(call, cancel)
        answers = response.get("answers")
        return ToolExecutionOutput(
            ok=True,
            content=_format_answers(answers if isinstance(answers, list) else []),
        )

    @staticmethod
    def _interrupted_output(
        call: ToolInvocation, cancel: asyncio.Event,
    ) -> ToolExecutionOutput:
        """Output sintetico per timeout/cancel di un'interazione client."""
        if cancel.is_set():
            reason = f"Interazione '{call.name}' annullata."
        else:
            reason = f"Interazione '{call.name}' scaduta (timeout)."
        return ToolExecutionOutput(ok=False, content=reason, error=reason)


def _format_answers(answers: list[Any]) -> str:
    """Rende le risposte dell'utente in testo leggibile per il modello."""
    if not answers:
        return "L'utente non ha fornito risposte."
    lines: list[str] = []
    for item in answers:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id") or "?")
        selected = item.get("selected")
        parts: list[str] = []
        if isinstance(selected, list) and selected:
            parts.append(", ".join(str(s) for s in selected))
        free_text = item.get("free_text")
        if free_text:
            parts.append(f"(testo libero: {free_text})")
        lines.append(f"{question_id}: {' '.join(parts) if parts else '(nessuna risposta)'}")
    return "Risposte dell'utente:\n" + "\n".join(lines)
