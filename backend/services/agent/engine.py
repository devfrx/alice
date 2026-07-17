"""AgentEngine: loop agentico unificato, I/O solo attraverso le porte.

Questo modulo copre, per ora, SOLO il percorso senza tool call (Task 8 del
piano Fase 1 Mossa 1): stream di uno step LLM, retry su risposta vuota,
cancel cooperativo, fallimento LLM non recuperabile. La gestione delle tool
call (gate permessi, interazione, esecuzione, dedup) arriva col Task 9.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from backend.services.agent import events as ev
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
)
from backend.services.agent.retry import RetryPolicy
from backend.services.agent.stop import BudgetTracker, resolve_stop


@dataclass(slots=True)
class _TurnState:
    """Stato mutabile di un turno, accumulato attraverso gli step."""

    request: TurnRequest
    working_messages: list[dict[str, Any]] = field(default_factory=list)
    content: str = ""
    thinking: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    tool_calls: int = 0
    empty_attempts: int = 0
    failure_attempts: int = 0
    errored: bool = False
    final_assistant_message_id: str | None = None

    def __post_init__(self) -> None:
        self.working_messages = list(self.request.history)


@dataclass(slots=True)
class _StepResult:
    """Esito grezzo di uno step LLM, prima delle decisioni di ``_after_step``."""

    finish_reason: str | None
    tool_calls: tuple[ToolInvocation, ...]
    failure: LLMFailure | None
    step_content: str


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
                await self._events.emit(ev.LlmStepEvent(turn_id=turn_id, step=step))
                step_result = await self._run_llm_step(turn_id, step, state, cancel)
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
        finish_reason: str | None = None
        tool_calls: tuple[ToolInvocation, ...] = ()
        failure: LLMFailure | None = None

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
                ))
            elif isinstance(event, LLMStepDone):
                finish_reason = event.finish_reason
                tool_calls = event.tool_calls
            elif isinstance(event, LLMFailure):
                failure = event

        return _StepResult(
            finish_reason=finish_reason, tool_calls=tool_calls,
            failure=failure, step_content=step_content,
        )

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
            # Task 9: gate permessi, interazione, esecuzione, dedup.
            raise NotImplementedError("Task 9")

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

    async def _finish(
        self,
        turn_id: str,
        stop: StopReason | None,
        state: _TurnState,
        budget: BudgetTracker,
    ) -> TurnOutcome:
        """Emette ``TurnFinishedEvent`` e costruisce il ``TurnOutcome`` finale.

        Chiamato SEMPRE, indipendentemente da come il loop si è fermato.
        """
        resolved_stop = stop if stop is not None else StopReason.ERROR
        finish_reason = STOP_TO_FINISH[resolved_stop]
        await self._events.emit(ev.TurnFinishedEvent(
            turn_id=turn_id, finish_reason=finish_reason, steps=budget.steps,
            tool_calls=state.tool_calls, cost=state.cost,
            final_message_id=state.final_assistant_message_id,
        ))
        return TurnOutcome(
            content=state.content, thinking=state.thinking,
            finish_reason=finish_reason, stop_reason=resolved_stop,
            steps=budget.steps, tool_calls=state.tool_calls,
            input_tokens=state.input_tokens, output_tokens=state.output_tokens,
            cost=state.cost, final_assistant_message_id=state.final_assistant_message_id,
        )
