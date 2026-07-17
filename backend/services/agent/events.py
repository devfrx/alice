"""Vocabolario eventi interni: type letterali, frozen, union esaustiva."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from backend.services.agent.models import ToolInvocation


class TurnStartedEvent(BaseModel):
    """Evento: turno avviato."""

    type: Literal["turn.started"] = "turn.started"
    turn_id: str
    conversation_id: str
    source: str
    model_config = ConfigDict(frozen=True)


class TurnDeltaEvent(BaseModel):
    """Evento: delta di output del turno."""

    type: Literal["turn.delta"] = "turn.delta"
    turn_id: str
    step: int
    kind: Literal["text", "thinking"]
    text: str
    model_config = ConfigDict(frozen=True)


class LlmStepEvent(BaseModel):
    """Evento: step LLM completato."""

    type: Literal["turn.llm_step"] = "turn.llm_step"
    turn_id: str
    step: int
    model_config = ConfigDict(frozen=True)


class ToolCallEvent(BaseModel):
    """Evento: tool call emesso dal modello."""

    type: Literal["tool.call"] = "tool.call"
    turn_id: str
    step: int
    call: ToolInvocation
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class ToolStartedEvent(BaseModel):
    """Evento: tool avviato."""

    type: Literal["tool.started"] = "tool.started"
    turn_id: str
    call_id: str
    name: str
    model_config = ConfigDict(frozen=True)


class ToolProgressEvent(BaseModel):
    """Evento: progresso di esecuzione tool."""

    type: Literal["tool.progress"] = "tool.progress"
    turn_id: str
    call_id: str
    name: str
    progress: dict[str, Any]
    model_config = ConfigDict(frozen=True)


class ToolResultEvent(BaseModel):
    """Evento: risultato di esecuzione tool.

    ``content_preview`` è il troncamento (200 char) del corpo, sempre presente.
    ``result`` porta il corpo COMPLETO ma SOLO per gli esiti di successo
    (``status == "ok"``): per i rami sintetici (rejection/deny/error/dedup/
    budget) è ``None``, perché quel testo è prosa engine-authored che diverge
    legittimamente dal wording legacy e non va confrontato verbatim.
    ``content_type`` è il MIME della tool response quando la piattaforma lo
    espone (threaded da ``ToolExecutionOutput``), altrimenti ``None``.
    """

    type: Literal["tool.result"] = "tool.result"
    turn_id: str
    call_id: str
    name: str
    status: str
    content_preview: str
    artifact_id: str | None
    result: str | None = None
    content_type: str | None = None
    model_config = ConfigDict(frozen=True)


class InteractionRequestedEvent(BaseModel):
    """Evento: interazione richiesta (payload COMPLETO, spec §4).

    ``payload`` per kind:
      * ``confirm``: args, risk_level, description, reasoning, allow_remember.
      * ``ask_user``: questions RAW dagli args del tool, NON ancora
        normalizzate al wire (la normalizzazione è responsabilità del layer
        wire: oggi ``adapters/ws.py``, dal Task 7 ``wire.py``).
      * ``client``: args.
    """

    type: Literal["interaction.requested"] = "interaction.requested"
    turn_id: str
    interaction_id: str
    kind: str
    call_id: str
    payload: dict[str, Any]
    tool_name: str | None = None
    model_config = ConfigDict(frozen=True)


class InteractionResolvedEvent(BaseModel):
    """Evento: interazione risolta.

    ``call_id`` correla la risoluzione all'attività della tool call lato FE
    (il ``request`` porta lo stesso ``call_id``); ``outcome`` è l'esito wire
    per kind: ``confirm`` → approved/rejected/timeout/cancelled/disconnected;
    ``ask_user`` → answered/failed/disconnected; ``client`` →
    executed/failed/disconnected.
    """

    type: Literal["interaction.resolved"] = "interaction.resolved"
    turn_id: str
    interaction_id: str
    kind: str
    call_id: str
    outcome: str
    model_config = ConfigDict(frozen=True)


class ContextUsageEvent(BaseModel):
    """Evento: utilizzo contesto."""

    type: Literal["context.usage"] = "context.usage"
    turn_id: str
    tokens: int
    context_window: int
    model_config = ConfigDict(frozen=True)


class CompactionEvent(BaseModel):
    """Evento: compattazione contesto."""

    type: Literal["context.compaction"] = "context.compaction"
    turn_id: str
    phase: Literal["started", "done", "failed"]
    tokens_before: int | None
    tokens_after: int | None
    error: str | None
    model_config = ConfigDict(frozen=True)


class TurnWarningEvent(BaseModel):
    """Evento: avvertimento durante turno."""

    type: Literal["turn.warning"] = "turn.warning"
    turn_id: str
    code: str
    message: str
    model_config = ConfigDict(frozen=True)


class TurnErrorEvent(BaseModel):
    """Evento: errore durante turno."""

    type: Literal["turn.error"] = "turn.error"
    turn_id: str
    code: str
    message: str
    model_config = ConfigDict(frozen=True)


class TurnUsageEvent(BaseModel):
    """Evento: utilizzo tokenico del turno.

    ``tool_calls`` è il conteggio corrente delle tool call EMESSE nel turno
    ("issued so far": ogni call ben formata presentata al gate, indipendente
    dalla disposizione — distinto dal conteggio delle sole ESEGUITE che governa
    il budget); ``max_steps`` è il budget di step del turno
    (``TurnRequest.max_steps``). Entrambi accompagnano ogni snapshot di usage.
    """

    type: Literal["turn.usage"] = "turn.usage"
    turn_id: str
    step: int
    input_tokens: int
    output_tokens: int
    cost: float
    tool_calls: int
    max_steps: int
    model_config = ConfigDict(frozen=True)


class TurnFinishedEvent(BaseModel):
    """Evento: turno completato."""

    type: Literal["turn.finished"] = "turn.finished"
    turn_id: str
    finish_reason: str
    steps: int
    tool_calls: int
    cost: float
    final_message_id: str | None
    model_config = ConfigDict(frozen=True)


class RawToolCallDeltaEvent(BaseModel):
    """Evento diagnostico: delta grezzo di tool call (solo Mossa 1)."""

    type: Literal["diag.tool_call_delta"] = "diag.tool_call_delta"
    turn_id: str
    payload: dict[str, Any]
    model_config = ConfigDict(frozen=True)


AgentEvent = (
    TurnStartedEvent | TurnDeltaEvent | LlmStepEvent | ToolCallEvent
    | ToolStartedEvent | ToolProgressEvent | ToolResultEvent
    | InteractionRequestedEvent | InteractionResolvedEvent
    | ContextUsageEvent | CompactionEvent | TurnWarningEvent | TurnErrorEvent
    | TurnUsageEvent | TurnFinishedEvent | RawToolCallDeltaEvent
)
