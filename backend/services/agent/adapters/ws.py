"""Trasporto WS greenfield: read-pump unico, request correlate, send fail-safe.

``WsTransport`` è il PROPRIETARIO del socket (invariante §6.6: un solo lettore).
Un unico task asyncio (il read-pump) consuma ``receive_json()`` e smista per
``type``:

* ``cancel`` → set dell'evento cancel del turno corrente + risoluzione a
  ``None`` di tutte le request pendenti (esito cancel);
* frame con ``correlation_id`` noto → risolve il Future della request; se la
  correlation è sconosciuta (risposta stale) il frame è scartato con log;
* qualsiasi altro frame → coda consumata da ``next_user_message()`` (giro
  turni in ``ws.py``).

Su ``WebSocketDisconnect``/``RuntimeError`` (socket chiuso) il pump marca il
trasporto disconnesso, risolve tutte le request pendenti con
``EngineDisconnected`` e spinge una sentinella ``None`` nella coda utente.

``send_json`` non solleva MAI: su qualunque errore di invio marca disconnesso
e inghiotte — il motore apprende della disconnessione dai percorsi request
delle porte (o da ``connected``), mai dall'emissione eventi (fire-and-forget).

Precedenza nella race di ``request``: disconnect > cancel > timeout. La
disconnessione risolve il Future pendente in modo eccezionale, quindi vince
anche quando cancel/timeout scattano nello stesso giro di loop.

Le porte:

* ``WsEventPort`` implementa ``EventPort``: traduce ogni ``AgentEvent`` in
  zero o più frame wire (il translator di parità arriva col Task 15) e li
  invia best-effort via ``send_json``.
* ``WsInteractionPort`` implementa ``InteractionPort`` costruendo i frame
  legacy del contratto chat (``api/ws_schema/chat.py``):
  ``tool_confirmation_required``, ``client_tool_call``, ``ask_user_required``.
  NON emette gli eventi canonici ``interaction.requested``/``resolved``: quelli
  sono fatti del turno e li emette il motore (Task 9) — emetterli anche qui
  li duplicherebbe sul canale.
  ``confirm_tool`` cattura ``EngineDisconnected`` e ritorna
  ``InteractionOutcome.DISCONNECTED`` come DATO (adjudicazione review T4: il
  motore persiste la tool response sintetica prima di fermarsi);
  ``run_client_tool``/``ask_user`` la PROPAGANO (§6.5: il loro tipo di ritorno
  non può codificarla).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from loguru import logger
from starlette.websockets import WebSocketDisconnect

from backend.services.agent.models import ToolInvocation
from backend.services.agent.ports import (
    EngineDisconnected,
    GateVerdict,
    InteractionOutcome,
    ToolExecutionOutput,
)

if TYPE_CHECKING:
    from starlette.websockets import WebSocket

    from backend.services.agent.events import AgentEvent

_RISK_LEVELS = frozenset({"safe", "medium", "dangerous", "forbidden"})
_DEFAULT_RISK = "medium"


class WsTransport:
    """Proprietario del socket: UNICO lettore, send fail-safe, request correlate."""

    def __init__(self, websocket: WebSocket) -> None:
        """Inizializza il trasporto sopra un socket già accettato.

        Args:
            websocket: Il ``WebSocket`` Starlette (o un doppio con lo stesso
                contratto ``receive_json``/``send_json``).
        """
        self._ws = websocket
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
        """Ferma il pump e marca il trasporto chiuso (request pendenti sbloccate)."""
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

    async def request(
        self,
        kind: str,
        frame_out: dict[str, Any],
        *,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> dict[str, Any] | None:
        """Invia ``frame_out`` con ``correlation_id`` e attende la risposta.

        Race con precedenza disconnect > cancel > timeout:

        * disconnessione → solleva ``EngineDisconnected``;
        * cancel (evento o frame ``cancel``) → ``None``;
        * timeout → ``None``.

        L'entry pendente è ripulita in TUTTI i percorsi di uscita.

        Args:
            kind: Etichetta diagnostica della richiesta (solo log).
            frame_out: Frame outbound; il ``correlation_id`` è assegnato qui.
            timeout_s: Timeout di attesa della risposta.
            cancel: Evento cooperativo di cancellazione del turno.

        Returns:
            Il frame di risposta, oppure ``None`` su cancel/timeout.

        Raises:
            EngineDisconnected: se il client cade prima della risposta.
        """
        correlation_id = uuid.uuid4().hex
        outbound = {**frame_out, "correlation_id": correlation_id}
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any] | None] = loop.create_future()
        self._pending[correlation_id] = future
        disconnect_waiter = asyncio.create_task(self._disconnected_event.wait())
        cancel_waiter = asyncio.create_task(cancel.wait())
        try:
            await self.send_json(outbound)
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
                    f"client WS caduto in attesa della risposta '{kind}'"
                )
            # cancel o timeout: entrambi → None.
            if not cancel_waiter.done():
                logger.debug(
                    "WsTransport: request '{}' scaduta dopo {}s", kind, timeout_s,
                )
            return None
        finally:
            self._pending.pop(correlation_id, None)
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
        """Smista un frame inbound: cancel, risposta correlata, o messaggio utente."""
        if frame.get("type") == "cancel":
            self._cancel.set()
            self._resolve_all_pending_to_none()
            return
        correlation_id = frame.get("correlation_id")
        if correlation_id is not None:
            future = self._pending.pop(correlation_id, None)
            if future is None:
                logger.warning(
                    "WsTransport: risposta stale scartata (correlation_id={})",
                    correlation_id,
                )
                return
            if not future.done():
                future.set_result(frame)
            return
        self._user_messages.put_nowait(frame)

    def _resolve_all_pending_to_none(self) -> None:
        """Risoluzione a ``None`` (esito cancel) di tutte le request pendenti."""
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
            translator: Mappa un ``AgentEvent`` in zero o più frame wire
                (in Mossa 1 sarà l'adapter di parità, Task 15).
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
    """``InteractionPort`` sul trasporto WS: frame legacy + request correlate.

    Non riceve la ``EventPort``: gli eventi canonici
    ``interaction.requested``/``resolved`` sono emessi dal MOTORE (un evento =
    un fatto del turno); questa porta possiede solo il giro wire legacy.
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
        verdict: GateVerdict,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> InteractionOutcome:
        """Chiede la conferma utente per una tool call rischiosa.

        Su disconnessione ritorna ``DISCONNECTED`` come DATO (adjudicazione
        T4): il motore persiste la tool response sintetica prima di fermarsi.
        """
        risk_level = (
            verdict.risk_level
            if verdict.risk_level in _RISK_LEVELS
            else _DEFAULT_RISK
        )
        frame = {
            "type": "tool_confirmation_required",
            "execution_id": call.call_id,
            "tool_name": call.name,
            "args": call.args,
            "risk_level": risk_level,
            "description": verdict.description or "",
            "reasoning": verdict.reason,
            "allow_remember": True,
        }
        try:
            response = await self._transport.request(
                "tool_confirmation", frame, timeout_s=timeout_s, cancel=cancel,
            )
        except EngineDisconnected:
            return InteractionOutcome.DISCONNECTED
        if response is None:
            if cancel.is_set():
                return InteractionOutcome.CANCELLED
            return InteractionOutcome.TIMEOUT
        if bool(response.get("approved")):
            return InteractionOutcome.APPROVED
        return InteractionOutcome.REJECTED

    async def run_client_tool(
        self,
        call: ToolInvocation,
        *,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput:
        """Delegazione al client di un tool UI-side (``client_tool_call``).

        Raises:
            EngineDisconnected: se il client cade prima del risultato (il
                tipo di ritorno non può codificarla; il motore la gestisce).
        """
        frame = {
            "type": "client_tool_call",
            "execution_id": call.call_id,
            "tool_name": call.name,
            "args": call.args,
        }
        response = await self._transport.request(
            "client_tool_call", frame, timeout_s=timeout_s, cancel=cancel,
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
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> ToolExecutionOutput:
        """Pone all'utente le domande del wizard ``ask_user_required``.

        Raises:
            EngineDisconnected: se il client cade prima delle risposte.
        """
        frame = {
            "type": "ask_user_required",
            "execution_id": call.call_id,
            "questions": _normalize_questions(call.args.get("questions")),
        }
        response = await self._transport.request(
            "ask_user", frame, timeout_s=timeout_s, cancel=cancel,
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


def _normalize_questions(raw: Any) -> list[dict[str, Any]]:
    """Normalizza le domande di ``ask_user`` alla forma del contratto wire.

    Il contratto (``WsAskUserQuestion``, extra='forbid') richiede esattamente
    ``id``/``text``/``type``/``options``/``allow_free_text``: chiavi estranee
    sono filtrate, default riempiti, tipi coartati in modo difensivo.
    """
    questions: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return questions
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        qtype = item.get("type")
        options = item.get("options")
        questions.append({
            "id": str(item.get("id") or f"q{index + 1}"),
            "text": str(item.get("text") or ""),
            "type": qtype if qtype in ("radio", "checkbox") else "radio",
            "options": [str(o) for o in options] if isinstance(options, list) else [],
            "allow_free_text": bool(item.get("allow_free_text", False)),
        })
    return questions


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
