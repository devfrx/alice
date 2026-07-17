"""AgentEngine: loop agentico unificato, I/O solo attraverso le porte.

Orchestratore centrale del turno: per ogni step, stream della risposta LLM
(con retry su risposta vuota via ``RetryPolicy`` e cancel cooperativo),
seguito — se il modello ha emesso tool call — dal gate permessi per-call
(``PermissionPort.decide``: EXECUTE / DENY / CONFIRM) e dal routing di ogni
call risolta verso uno di tre percorsi: interattiva (conferma utente via
``InteractionPort``), client-executed (``app_command`` e simili, delegati al
frontend), o batch server-side greenlit — eseguito in PARALLELO
(``asyncio.gather``, ``_run_tool_batch``) dopo il dedup (``DedupRegistry``).
Prima di ogni step successivo al primo, valuta ed eventualmente esegue la
compaction del contesto (``ContextPort.should_compact``/``compact``,
fail-open: un errore di compaction non affonda il turno). Lo stop del turno
(budget step/token, finish naturale, errore LLM non recuperabile, cancel) è
risolto da ``resolve_stop``/``BudgetTracker`` (``stop.py``). Tutto l'I/O
verso piattaforma — LLM, permessi, esecuzione tool, interazione utente,
persistenza, contesto, eventi — passa esclusivamente attraverso le
``Port`` Protocol di ``services/agent/ports.py``; il motore non conosce le
implementazioni concrete di piattaforma (quelle vivono negli adapter,
``services/agent/adapters/``).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from backend.services.agent import events as ev
from backend.services.agent.dedup import DedupRegistry
from backend.services.agent.models import (
    STOP_TO_FINISH,
    StopReason,
    ToolInvocation,
    TurnOutcome,
    TurnRequest,
)
from backend.services.agent.ports import (
    ContextPort,
    EngineDisconnected,
    EventPort,
    ExecutionPort,
    GateAction,
    GateVerdict,
    InteractionOutcome,
    InteractionPort,
    LLMFailure,
    LLMPort,
    LLMStepDone,
    LLMTextDelta,
    LLMThinkingDelta,
    LLMToolCallDelta,
    LLMUsage,
    PermissionPort,
    PersistencePort,
    ToolExecutionOutput,
)
from backend.services.agent.retry import RetryPolicy
from backend.services.agent.stop import BudgetTracker, resolve_stop

# Etichette di stato per la tool response, per ramo del gate (§6.1.1).
_STATUS_OK = "ok"
_STATUS_ERROR = "error"
_STATUS_PARSE_ERROR = "parse_error"
_STATUS_DUPLICATE = "duplicate"
_STATUS_UNKNOWN = "unknown_tool"
_STATUS_DENIED = "denied"
_STATUS_REJECTED = "rejected"
_STATUS_TIMEOUT = "timeout"
_STATUS_CANCELLED = "cancelled"
_STATUS_BUDGET = "budget_exhausted"


@dataclass(slots=True)
class _TurnState:
    """Stato mutabile di un turno, accumulato attraverso gli step.

    ``content`` NON è cumulativo attraverso gli step (fix review T16): è
    resettato a inizio di ogni ``_run_llm_step`` e accumula SOLO i delta
    di QUELLO step, cosicché rifletta il testo dello step corrente (o, se
    l'eccezione arriva a metà stream, il testo parziale di quello step in
    corso). ``last_step_content`` è il testo dell'ULTIMO step che ne ha
    prodotto uno non vuoto — non viene mai sovrascritto da uno step vuoto
    (retry/nudge) — usato SOLO come fallback nei rami di stop
    cancelled/disconnected/error quando lo step interrotto non ha
    accumulato nulla di suo (recovery message, §ws.py `full_content`).
    ``thinking`` resta cumulativo su tutto il turno (nessun requisito di
    finale-solo per il ragionamento).
    """

    request: TurnRequest
    working_messages: list[dict[str, Any]] = field(default_factory=list)
    dedup: DedupRegistry = field(default_factory=DedupRegistry)
    content: str = ""
    last_step_content: str = ""
    thinking: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    tool_calls: int = 0
    issued_tool_calls: int = 0
    empty_attempts: int = 0
    failure_attempts: int = 0
    errored: bool = False
    final_assistant_message_id: str | None = None
    pending_tool_intent: bool = False

    def __post_init__(self) -> None:
        self.working_messages = list(self.request.history)


@dataclass(slots=True)
class _StepResult:
    """Esito grezzo di uno step LLM, prima delle decisioni di ``_after_step``."""

    finish_reason: str | None
    tool_calls: tuple[ToolInvocation, ...]
    failure: LLMFailure | None
    step_content: str
    step_thinking: str = ""


@dataclass(slots=True)
class _CallResolution:
    """Esito di UNA tool call: la tool response da persistire (§6.1.1).

    Attributi:
        content: Contenuto testuale della tool response (sintetico o reale).
        status: Etichetta di stato del ramo (ok/denied/rejected/...).
        output: L'output d'esecuzione, solo per i success con artefatti; None
            per i rami sintetici (parse_error, dedup, deny, ...).
        disconnect: True se il ramo impone lo stop per disconnessione DOPO che
            la tool response è stata persistita (§6.5 persist-prima-di-cancel).
    """

    content: str
    status: str
    output: ToolExecutionOutput | None = None
    disconnect: bool = False


def _assistant_tool_message(
    content: str, calls: tuple[ToolInvocation, ...],
) -> dict[str, Any]:
    """Messaggio assistant con ``tool_calls`` in formato OpenAI per la working history."""
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": call.call_id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.raw_args},
            }
            for call in calls
        ],
    }


def _tool_message(call: ToolInvocation, content: str) -> dict[str, Any]:
    """Messaggio ``tool`` (una per call_id) in formato OpenAI per la working history."""
    return {"role": "tool", "tool_call_id": call.call_id, "content": content}


class AgentEngine:
    """Motore agentico: un loop unificato, I/O solo attraverso le porte."""

    def __init__(
        self,
        *,
        llm: LLMPort,
        permissions: PermissionPort,
        interaction: InteractionPort,
        events: EventPort,
        persistence: PersistencePort,
        context: ContextPort,
        execution: ExecutionPort,
        retry: RetryPolicy,
        confirmation_timeout_s: float = 120.0,
    ) -> None:
        self._llm = llm
        self._permissions = permissions
        self._interaction = interaction
        self._events = events
        self._persistence = persistence
        self._context = context
        self._execution = execution
        self._retry = retry
        self._confirmation_timeout_s = confirmation_timeout_s

    async def run(self, request: TurnRequest, *, cancel: asyncio.Event) -> TurnOutcome:
        """Esegue un turno completo e ritorna il ``TurnOutcome``.

        Args:
            request: la richiesta di turno assemblata dal chiamante.
            cancel: evento cooperativo di cancellazione, controllato a
                inizio di ogni step.

        Returns:
            Il ``TurnOutcome`` popolato, indipendentemente dall'esito
            (successo, cancel, errore, disconnessione): il motore non
            lascia mai trapelare eccezioni.
        """
        turn_id = uuid.uuid4().hex
        state = _TurnState(request=request)
        await self._events.emit(ev.TurnStartedEvent(
            turn_id=turn_id, conversation_id=request.conversation_id,
            source=request.source.value,
        ))
        budget = BudgetTracker(max_steps=request.max_steps)
        stop: StopReason | None = None
        try:
            while stop is None:
                if cancel.is_set():
                    stop = StopReason.CANCELLED
                    break
                step = budget.begin_step()
                if step > 1:
                    await self._maybe_compact(turn_id, step, state)
                await self._events.emit(ev.LlmStepEvent(turn_id=turn_id, step=step))
                step_result = await self._run_llm_step(turn_id, step, state, cancel)
                # `state.content` = testo di QUESTO step (fix review T16, vedi
                # `_TurnState`); `last_step_content` si aggiorna SOLO se non
                # vuoto, per non essere sovrascritto da uno step vuoto
                # (retry/nudge) — resta il fallback per i rami di stop
                # cancelled/disconnected/error in `_finish`.
                state.content = step_result.step_content
                if step_result.step_content:
                    state.last_step_content = step_result.step_content
                stop = await self._after_step(
                    turn_id, step, step_result, state, budget, cancel,
                )
        except EngineDisconnected:
            stop = StopReason.DISCONNECTED
        except Exception as exc:  # difesa: mai trapelare
            logger.exception("AgentEngine: errore non gestito")
            state.errored = True
            await self._events.emit(ev.TurnErrorEvent(
                turn_id=turn_id, code="engine_error", message=str(exc),
            ))
            stop = StopReason.ERROR
        return await self._finish(turn_id, stop, state, budget)

    async def _run_llm_step(
        self, turn_id: str, step: int, state: _TurnState, cancel: asyncio.Event,
    ) -> _StepResult:
        """Consuma lo stream di uno step LLM, accumulando nel `state`.

        Ritorna un ``_StepResult`` grezzo: il contenuto testuale di QUESTO
        step (per decidere se è vuoto), il finish_reason, le tool call e
        un eventuale ``LLMFailure``.
        """
        step_content = ""
        step_thinking = ""
        finish_reason: str | None = None
        tool_calls: tuple[ToolInvocation, ...] = ()
        failure: LLMFailure | None = None
        # Reset PRIMA dello stream (fix review T16): `state.content` deve
        # riflettere SOLO questo step (non il cumulato) — se un'eccezione
        # arriva a metà stream, resta comunque il parziale di QUESTO step,
        # non un residuo di step precedenti.
        state.content = ""

        stream = self._llm.stream_step(
            system_prompt=state.request.system_prompt,
            messages=state.working_messages,
            tools=state.request.tools,
            max_tokens=state.request.resolved_max_tokens,
            cancel=cancel,
        )
        async for event in stream:
            if isinstance(event, LLMTextDelta):
                state.content += event.text
                step_content += event.text
                await self._events.emit(ev.TurnDeltaEvent(
                    turn_id=turn_id, step=step, kind="text", text=event.text,
                ))
            elif isinstance(event, LLMThinkingDelta):
                state.thinking += event.text
                step_thinking += event.text
                await self._events.emit(ev.TurnDeltaEvent(
                    turn_id=turn_id, step=step, kind="thinking", text=event.text,
                ))
            elif isinstance(event, LLMToolCallDelta):
                await self._events.emit(ev.RawToolCallDeltaEvent(
                    turn_id=turn_id, payload=event.payload,
                ))
            elif isinstance(event, LLMUsage):
                state.input_tokens += event.input_tokens
                state.output_tokens += event.output_tokens
                state.cost += event.cost
                await self._events.emit(ev.TurnUsageEvent(
                    turn_id=turn_id, step=step,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                    cost=event.cost,
                    tool_calls=state.issued_tool_calls,
                    max_steps=state.request.max_steps,
                ))
            elif isinstance(event, LLMStepDone):
                finish_reason = event.finish_reason
                tool_calls = event.tool_calls
            elif isinstance(event, LLMFailure):
                failure = event

        return _StepResult(
            finish_reason=finish_reason, tool_calls=tool_calls,
            failure=failure, step_content=step_content, step_thinking=step_thinking,
        )

    async def _maybe_compact(self, turn_id: str, step: int, state: _TurnState) -> None:
        """Valuta ed eventualmente esegue la compaction PRIMA di uno step LLM.

        Chiamato solo per gli step successivi al primo (§ compaction, flusso
        1-5). Fail-open: un errore, o un ``CompactionResult(performed=False)``,
        non interrompe il turno — si prosegue senza compattare.
        """
        context_window = state.request.context_window
        tokens = self._context.estimate_tokens(state.working_messages)
        await self._events.emit(ev.ContextUsageEvent(
            turn_id=turn_id, tokens=tokens, context_window=context_window,
        ))
        if not self._context.should_compact(tokens=tokens, context_window=context_window):
            return
        await self._events.emit(ev.CompactionEvent(
            turn_id=turn_id, phase="started",
            tokens_before=None, tokens_after=None, error=None,
        ))
        try:
            result = await self._context.compact(
                messages=state.working_messages, context_window=context_window,
            )
        except Exception as exc:  # fail-open: la compaction non affonda il turno
            logger.exception("AgentEngine: context.compact ha sollevato")
            await self._events.emit(ev.CompactionEvent(
                turn_id=turn_id, phase="failed",
                tokens_before=None, tokens_after=None, error=str(exc),
            ))
            return
        if not result.performed:
            await self._events.emit(ev.CompactionEvent(
                turn_id=turn_id, phase="failed",
                tokens_before=result.tokens_before, tokens_after=result.tokens_after,
                error=result.error,
            ))
            return
        summary_text = result.summary_text or ""
        await self._persistence.archive_compacted(
            summary_text=summary_text,
            upto_message_ids=list(result.archived_message_ids),
        )
        await self._persistence.checkpoint()
        # ``kept_messages`` dall'adapter è GIÀ la history nuova completa:
        # ContextManager.compress ritorna system_msgs + summary_msg (role
        # assistant, prefisso "[Context summary of N...]" con conteggio
        # corretto) + to_keep — nessuna entry sintetica da aggiungere qui
        # (una seconda copia duplicherebbe il riassunto nel prompt).
        state.working_messages = list(result.kept_messages)
        await self._events.emit(ev.CompactionEvent(
            turn_id=turn_id, phase="done",
            tokens_before=result.tokens_before, tokens_after=result.tokens_after,
            error=None,
        ))

    async def _after_step(
        self,
        turn_id: str,
        step: int,
        step_result: _StepResult,
        state: _TurnState,
        budget: BudgetTracker,
        cancel: asyncio.Event,
    ) -> StopReason | None:
        """Decide cosa fare dopo uno step: retry, tool, stop.

        Ritorna una ``StopReason`` per fermare il loop, o ``None`` per
        proseguire con un altro step (retry su vuoto/fallimento transitorio).
        """
        if step_result.failure is not None:
            state.failure_attempts += 1
            decision = self._retry.on_failure(step_result.failure, state.failure_attempts)
            if decision.retry:
                return None
            state.errored = True
            await self._events.emit(ev.TurnErrorEvent(
                turn_id=turn_id, code="llm_failure", message=step_result.failure.message,
            ))
            return resolve_stop(
                llm_finish=None, cancelled=False, disconnected=False,
                out_of_steps=False, errored=True,
            )

        if step_result.tool_calls:
            return await self._run_tool_step(turn_id, step, step_result, state, budget, cancel)

        if not step_result.step_content:
            state.empty_attempts += 1
            decision = self._retry.on_empty_response(state.empty_attempts)
            if decision.retry and decision.nudge is not None:
                state.working_messages.append({"role": "user", "content": decision.nudge})
                return None
            # Retry esaurito su risposta vuota: chiude come completato
            # (nessun contenuto da produrre, ma nessun errore di per sé).
            return resolve_stop(
                llm_finish=step_result.finish_reason, cancelled=False,
                disconnected=False, out_of_steps=budget.out_of_steps(),
                errored=False,
            )

        return resolve_stop(
            llm_finish=step_result.finish_reason, cancelled=False,
            disconnected=False, out_of_steps=budget.out_of_steps(),
            errored=False,
        )

    async def _run_tool_step(
        self,
        turn_id: str,
        step: int,
        step_result: _StepResult,
        state: _TurnState,
        budget: BudgetTracker,
        cancel: asyncio.Event,
    ) -> StopReason | None:
        """Esegue lo step con tool secondo il flusso normativo 1-5 (§6).

        Ritorna una ``StopReason`` per fermare il loop (cancel/disconnect
        DOPO la persistenza, o budget di step esaurito) oppure ``None`` per
        proseguire con un nuovo step: la working history si è arricchita di
        assistant + tool messages.
        """
        calls = step_result.tool_calls
        # 1. save_assistant_step PRIMA di tutto (§6.1.2), poi checkpoint (§6.15:
        #    rilascia il write-lock prima dell'esecuzione parallela).
        await self._persistence.save_assistant_step(
            content=step_result.step_content,
            thinking=step_result.step_thinking,
            tool_calls=calls,
        )
        await self._persistence.checkpoint()
        state.working_messages.append(
            _assistant_tool_message(step_result.step_content, calls)
        )

        # 2. gate per-call, in ordine: ogni ramo produce una _CallResolution;
        #    i greenlit server-side (None) confluiscono nel batch parallelo.
        resolutions: dict[str, _CallResolution] = {}
        batch: list[ToolInvocation] = []
        for call in calls:
            resolution = await self._gate_call(turn_id, step, call, state, cancel)
            if resolution is None:
                batch.append(call)
            else:
                resolutions[call.call_id] = resolution

        # 3. batch server-side greenlit in PARALLELO (asyncio.gather).
        if batch:
            resolutions.update(await self._run_tool_batch(turn_id, batch, state))

        # 4. persistenza: UNA tool response per OGNI call_id (§6.1.1), in ordine.
        #    TUTTI i save_tool_result PRIMA del checkpoint, e SOLO DOPO il
        #    checkpoint si registrano gli artifact (§ fix review T13):
        #    ``register_artifacts`` committa su una sessione propria
        #    (ArtifactRegistry, non l'adapter del motore) e la riga Artifact
        #    porta una FK verso la riga Message del tool result. Se si
        #    registrasse PRIMA del checkpoint, un crash tra la registrazione
        #    e il checkpoint lascerebbe un Artifact durevole con FK verso un
        #    Message poi rollback-ato — dangling, silenzioso perché SQLite ha
        #    l'enforcement dei FK disattivato. Registrando dopo il
        #    checkpoint, la FK punta SEMPRE a righe già durevoli.
        for call in calls:
            resolution = resolutions[call.call_id]
            await self._persistence.save_tool_result(
                call=call, content=resolution.content, status=resolution.status,
            )
        await self._persistence.checkpoint()

        disconnect = False
        for call in calls:
            resolution = resolutions[call.call_id]
            artifact_id: str | None = None
            if resolution.output is not None and resolution.output.ok:
                artifact_id = await self._persistence.register_artifacts(
                    call=call, output=resolution.output,
                )
            state.working_messages.append(_tool_message(call, resolution.content))
            await self._events.emit(ev.ToolResultEvent(
                turn_id=turn_id, call_id=call.call_id, name=call.name,
                status=resolution.status, result=resolution.content,
                artifact_id=artifact_id,
                content_type=(
                    resolution.output.content_type
                    if resolution.output is not None else None
                ),
            ))
            disconnect = disconnect or resolution.disconnect

        # 5. SOLO DOPO la persistenza (checkpoint + registrazione artifact):
        #    disconnect / cancel (§6.4) / budget
        #    di step esaurito → stop.
        if disconnect:
            return resolve_stop(
                llm_finish=None, cancelled=False, disconnected=True,
                out_of_steps=False, errored=False,
            )
        if cancel.is_set():
            return resolve_stop(
                llm_finish=None, cancelled=True, disconnected=False,
                out_of_steps=False, errored=False,
            )
        if budget.out_of_steps():
            # Il budget si esaurisce PROPRIO su uno step con tool call: il
            # loop si sarebbe fermato con intent pendente, non su una
            # risposta finale pulita (§ fix review T10).
            state.pending_tool_intent = True
            return resolve_stop(
                llm_finish=None, cancelled=False, disconnected=False,
                out_of_steps=True, errored=False,
            )
        return None

    async def _gate_call(
        self,
        turn_id: str,
        step: int,
        call: ToolInvocation,
        state: _TurnState,
        cancel: asyncio.Event,
    ) -> _CallResolution | None:
        """Applica il gate a UNA call. Ritorna la resolution, o ``None`` se
        la call è greenlit server-side e va nel batch parallelo.
        """
        # a. parse_error → result sintetico d'errore (niente gate).
        if call.parse_error is not None:
            return _CallResolution(
                content=f"Argomenti non validi: {call.parse_error}",
                status=_STATUS_PARSE_ERROR,
            )
        # tool.call per OGNI call ben formata, prima del gate.
        await self._events.emit(ev.ToolCallEvent(turn_id=turn_id, step=step, call=call))
        # "issued": ogni call ben formata presentata al gate conta come EMESSA
        # (indipendentemente dalla disposizione: dedup/deny/reject/exec). È il
        # contatore che alimenta lo snapshot turn.usage (semantica "issued so
        # far"), distinto da ``tool_calls`` che conta le sole ESEGUITE (budget).
        state.issued_tool_calls += 1
        # b. dedup → result sintetico "duplicata".
        if state.dedup.seen_before(call):
            return _CallResolution(
                content="Chiamata duplicata: riusa il risultato precedente.",
                status=_STATUS_DUPLICATE,
            )
        # c. tool sconosciuto → result "tool sconosciuto".
        meta = self._execution.describe(call.name)
        if not meta.exists:
            return _CallResolution(
                content=f"Tool sconosciuto: {call.name}.", status=_STATUS_UNKNOWN,
            )
        # c.bis trim voce: budget di tool call ESEGUITE raggiunto (§10) →
        # result sintetico, niente gate. Contatore = ``state.tool_calls``,
        # incrementato SOLO alle call che raggiungono l'esecuzione reale
        # (routing, sotto), così una duplicata/negata non consuma budget.
        max_tool_calls = state.request.max_tool_calls
        if max_tool_calls is not None and state.tool_calls >= max_tool_calls:
            return _CallResolution(
                content="Budget voce esaurito: chiamata non eseguita.",
                status=_STATUS_BUDGET,
            )
        # d. gate permessi, per-call (§6.9).
        verdict = await self._permissions.decide(
            call, conversation_id=state.request.conversation_id,
        )
        if verdict.action == GateAction.DENY:
            await self._persistence.save_audit(
                call=call, verdict=verdict, interaction=None,
            )
            reason = verdict.reason or verdict.outcome
            return _CallResolution(
                content=f"Chiamata negata: {reason}.", status=_STATUS_DENIED,
            )
        if verdict.action == GateAction.CONFIRM:
            confirm_res = await self._confirm_call(turn_id, call, verdict, cancel)
            if confirm_res is not None:
                return confirm_res
            # APPROVED → prosegue al routing.
        # e. routing: ask_user / client_executed / batch server-side. Da qui
        # in poi la call è ESEGUITA per davvero: conta verso outcome.tool_calls
        # (e verso il budget voce del prossimo controllo trim).
        state.tool_calls += 1
        timeout_s = meta.timeout_s or self._confirmation_timeout_s
        if meta.interactive == "ask_user":
            return await self._run_interactive(
                turn_id, call, kind="ask_user", timeout_s=timeout_s, cancel=cancel,
            )
        if meta.client_executed:
            return await self._run_interactive(
                turn_id, call, kind="client", timeout_s=timeout_s, cancel=cancel,
            )
        return None

    async def _confirm_call(
        self,
        turn_id: str,
        call: ToolInvocation,
        verdict: GateVerdict,
        cancel: asyncio.Event,
    ) -> _CallResolution | None:
        """Flusso di conferma: eventi requested/resolved, audit, mappatura esito.

        Ritorna ``None`` se APPROVED (la call prosegue al routing); altrimenti
        la resolution sintetica. DISCONNECTED è un DATO: result sintetico +
        flag disconnect (lo stop scatta DOPO la persistenza, §6.5).

        INVARIANTE: nessun ``await`` tra il ritorno di
        ``emit(InteractionRequestedEvent)`` e la chiamata alla porta
        (``confirm_tool``) — la porta registra il proprio waiter in modo
        sincrono prima del suo primo await (Task 8), così una risposta del
        client non può andare persa nella finestra tra emissione e attesa.
        """
        interaction_id = uuid.uuid4().hex
        await self._events.emit(ev.InteractionRequestedEvent(
            turn_id=turn_id, interaction_id=interaction_id, kind="confirm",
            call_id=call.call_id, tool_name=call.name,
            payload={
                "args": call.args,
                "risk_level": verdict.risk_level,
                "description": verdict.description,
                "reasoning": verdict.reason,
                "allow_remember": True,
            },
        ))
        outcome = await self._interaction.confirm_tool(
            call, interaction_id=interaction_id, verdict=verdict,
            timeout_s=self._confirmation_timeout_s, cancel=cancel,
        )
        await self._events.emit(ev.InteractionResolvedEvent(
            turn_id=turn_id, interaction_id=interaction_id, kind="confirm",
            call_id=call.call_id, outcome=outcome.value,
        ))
        await self._persistence.save_audit(
            call=call, verdict=verdict, interaction=outcome,
        )
        if outcome == InteractionOutcome.APPROVED:
            return None
        if outcome == InteractionOutcome.REJECTED:
            return _CallResolution(
                content="Chiamata rifiutata dall'utente.", status=_STATUS_REJECTED,
            )
        if outcome == InteractionOutcome.TIMEOUT:
            return _CallResolution(
                content="Conferma scaduta (timeout).", status=_STATUS_TIMEOUT,
            )
        if outcome == InteractionOutcome.CANCELLED:
            return _CallResolution(
                content="Chiamata annullata.", status=_STATUS_CANCELLED,
            )
        # DISCONNECTED
        return _CallResolution(
            content="Chiamata annullata (disconnesso).", status=_STATUS_CANCELLED,
            disconnect=True,
        )

    async def _run_interactive(
        self,
        turn_id: str,
        call: ToolInvocation,
        *,
        kind: str,
        timeout_s: float,
        cancel: asyncio.Event,
    ) -> _CallResolution:
        """Esegue una call interattiva (ask_user o client-side) con eventi
        requested/resolved (carry #4).

        La disconnessione arriva come eccezione dalla porta: la si cattura,
        si sintetizza la tool response e si segnala lo stop DOPO la
        persistenza (§6.5), senza sollevare fuori dal motore.

        INVARIANTE: nessun ``await`` tra il ritorno di
        ``emit(InteractionRequestedEvent)`` e la chiamata alla porta
        (``ask_user``/``run_client_tool``) — la porta registra il proprio
        waiter in modo sincrono prima del suo primo await (Task 8), così una
        risposta del client non può andare persa nella finestra tra emissione
        e attesa.
        """
        interaction_id = uuid.uuid4().hex
        if kind == "ask_user":
            payload: dict[str, Any] = {"questions": call.args.get("questions")}
        else:
            payload = {"args": call.args}
        await self._events.emit(ev.InteractionRequestedEvent(
            turn_id=turn_id, interaction_id=interaction_id, kind=kind,
            call_id=call.call_id, tool_name=call.name, payload=payload,
        ))
        try:
            if kind == "ask_user":
                output = await self._interaction.ask_user(
                    call, interaction_id=interaction_id,
                    timeout_s=timeout_s, cancel=cancel,
                )
            else:
                output = await self._interaction.run_client_tool(
                    call, interaction_id=interaction_id,
                    timeout_s=timeout_s, cancel=cancel,
                )
        except EngineDisconnected:
            await self._events.emit(ev.InteractionResolvedEvent(
                turn_id=turn_id, interaction_id=interaction_id, kind=kind,
                call_id=call.call_id, outcome="disconnected",
            ))
            return _CallResolution(
                content="Chiamata annullata (disconnesso).",
                status=_STATUS_CANCELLED, disconnect=True,
            )
        # timeout/cancel/errore client convergono su "failed": la porta ritorna
        # un ToolExecutionOutput e non distingue l'esito wire (residuo
        # deliberato, censito nel ledger).
        if not output.ok:
            outcome = "failed"
        elif kind == "ask_user":
            outcome = "answered"
        else:
            outcome = "executed"
        await self._events.emit(ev.InteractionResolvedEvent(
            turn_id=turn_id, interaction_id=interaction_id, kind=kind,
            call_id=call.call_id, outcome=outcome,
        ))
        status = _STATUS_OK if output.ok else _STATUS_ERROR
        return _CallResolution(content=output.content, status=status, output=output)

    async def _run_tool_batch(
        self,
        turn_id: str,
        batch: list[ToolInvocation],
        state: _TurnState,
    ) -> dict[str, _CallResolution]:
        """Esegue il batch greenlit server-side in PARALLELO (asyncio.gather).

        Per ciascuna call: ``ToolStartedEvent`` prima dell'esecuzione. Un
        errore di una call viene catturato e sintetizzato (§6.1.1): nessuna
        call può affondare le altre.
        """
        async def _one(call: ToolInvocation) -> tuple[str, _CallResolution]:
            await self._events.emit(ev.ToolStartedEvent(
                turn_id=turn_id, call_id=call.call_id, name=call.name,
            ))

            async def _on_progress(payload: dict[str, Any]) -> None:
                # Best-effort: il progresso non puo affondare il tool.
                await self._events.emit(ev.ToolProgressEvent(
                    turn_id=turn_id, call_id=call.call_id, name=call.name,
                    progress=dict(payload),
                ))

            try:
                output = await self._execution.execute(
                    call, client_ip=state.request.client_ip,
                    conversation_id=state.request.conversation_id,
                    on_progress=_on_progress,
                )
            except Exception as exc:  # §6.1.1: la call fallisce da sola
                logger.exception("AgentEngine: tool {} ha sollevato", call.name)
                return call.call_id, _CallResolution(
                    content=f"Errore nell'esecuzione del tool: {exc}",
                    status=_STATUS_ERROR,
                )
            status = _STATUS_OK if output.ok else _STATUS_ERROR
            return call.call_id, _CallResolution(
                content=output.content, status=status, output=output,
            )

        pairs: list[tuple[str, _CallResolution]] = await asyncio.gather(
            *(_one(call) for call in batch)
        )
        return dict(pairs)

    async def _finish(
        self,
        turn_id: str,
        stop: StopReason | None,
        state: _TurnState,
        budget: BudgetTracker,
    ) -> TurnOutcome:
        """Persiste il messaggio finale (matrice sotto), emette
        ``TurnFinishedEvent`` e costruisce il ``TurnOutcome``.

        Chiamato SEMPRE, indipendentemente da come il loop si è fermato.
        """
        resolved_stop = stop if stop is not None else StopReason.ERROR
        finish_reason = STOP_TO_FINISH[resolved_stop]
        if resolved_stop is StopReason.MAX_STEPS and state.pending_tool_intent:
            await self._events.emit(ev.TurnWarningEvent(
                turn_id=turn_id, code="max_steps",
                message="Budget di step esaurito con tool call in sospeso.",
            ))
        # Fix review T16: `final_content` = testo dell'ULTIMO step, non il
        # cumulato di tutti gli step (altrimenti la prosa pre-tool, già
        # persistita da `save_assistant_step`, verrebbe ri-scritta come
        # messaggio finale — duplicata).
        #
        # - COMPLETED / LENGTH / MAX_STEPS: `state.content` è ESATTAMENTE il
        #   testo dello step che ha determinato lo stop (letterale, anche se
        #   vuoto — nessun fallback: uno step con tool call e senza prosa
        #   nuova chiude con content="").
        # - CANCELLED / DISCONNECTED / ERROR: lo stop può arrivare a metà
        #   dello step (interazione interrotta, eccezione non gestita) — si
        #   usa il parziale accumulato da QUELLO step, e SOLO se quello step
        #   non ha prodotto nulla di suo si ripiega sull'ultimo step non
        #   vuoto (preserva il recovery message parziale su disconnect,
        #   §ws.py `full_content`).
        if resolved_stop in (
            StopReason.CANCELLED, StopReason.DISCONNECTED, StopReason.ERROR,
        ):
            final_content = state.content or state.last_step_content
        else:
            final_content = state.content

        # Matrice di salvataggio del messaggio finale (carry #2/#3):
        #   COMPLETED/LENGTH/MAX_STEPS -> prosa finale, o turno senza tool
        #   CANCELLED                  -> parziale (content o thinking)
        #   DISCONNECTED               -> recovery message (era in ws.py)
        #   ERROR                      -> mai (il persist path fa solo rollback)
        if resolved_stop in (
            StopReason.COMPLETED, StopReason.LENGTH, StopReason.MAX_STEPS,
        ):
            should_save = bool(final_content.strip()) or state.tool_calls == 0
        elif resolved_stop is StopReason.CANCELLED:
            should_save = bool(final_content or state.thinking)
        elif resolved_stop is StopReason.DISCONNECTED:
            should_save = bool(final_content)
        else:  # ERROR
            should_save = False
        if should_save:
            try:
                state.final_assistant_message_id = (
                    await self._persistence.save_final_message(
                        content=final_content, thinking=state.thinking,
                        input_tokens=state.input_tokens,
                        output_tokens=state.output_tokens, cost=state.cost,
                    )
                )
                await self._persistence.checkpoint()
            except Exception as exc:
                logger.exception("AgentEngine: persistenza finale fallita")
                await self._events.emit(ev.TurnErrorEvent(
                    turn_id=turn_id, code="persist_failed", message=str(exc),
                ))
                resolved_stop = StopReason.ERROR
                finish_reason = STOP_TO_FINISH[resolved_stop]
                state.final_assistant_message_id = None

        await self._events.emit(ev.TurnFinishedEvent(
            turn_id=turn_id, finish_reason=finish_reason,
            conversation_id=state.request.conversation_id,
            final_message_id=state.final_assistant_message_id,
            user_message_id=state.request.user_message_id,
            version_group_id=state.request.version_group_id,
            version_index=state.request.version_index or 0,
            steps=budget.steps, tool_calls=state.tool_calls,
            input_tokens=state.input_tokens, output_tokens=state.output_tokens,
            cost=state.cost,
        ))
        return TurnOutcome(
            content=final_content, thinking=state.thinking,
            finish_reason=finish_reason, stop_reason=resolved_stop,
            steps=budget.steps, tool_calls=state.tool_calls,
            input_tokens=state.input_tokens, output_tokens=state.output_tokens,
            cost=state.cost, final_assistant_message_id=state.final_assistant_message_id,
        )
