"""Translator DEFINITIVO: ``AgentEvent`` → frame wire v2 (spec Fase 1 §4).

Ogni frame è costruito ATTRAVERSO il modello Pydantic del contratto
(``backend/api/ws_schema/chat.py``) e serializzato con
``model_dump(mode="json", exclude_none=True)``: un frame che non valida non
può essere costruito — la garanzia sul wire è by-construction, non più solo
a livello di test (chiude il debito M1 "frame del motore non validati a
runtime"). Un evento = un frame; nessun frame legacy.
"""

from __future__ import annotations

from typing import Any

from backend.api.ws_schema import chat as ws
from backend.services.agent import events as ev
from backend.services.agent.events import AgentEvent

#: kind interno → InteractionKind del contratto.
_INTERACTION_KIND: dict[str, str] = {
    "confirm": "tool_confirmation",
    "client": "client_tool_call",
    "ask_user": "ask_user",
}


def _dump(frame: Any) -> dict[str, Any]:
    return frame.model_dump(mode="json", exclude_none=True)


def normalize_questions(raw: Any) -> list[dict[str, Any]]:
    """Normalizza le domande di ``ask_user`` alla forma del contratto.

    ``WsAskUserQuestion`` (extra='forbid') richiede esattamente
    id/text/type/options/allow_free_text: chiavi estranee filtrate, default
    riempiti, tipi coartati in modo difensivo.

    NOTA: una copia della stessa logica vive ancora in ``adapters/ws.py`` per
    i frame legacy ``ask_user_required`` — quella muore nel Task 8, quando il
    round-trip interattivo passa al vocabolario v2 e ``ws.py`` non costruisce
    più frame di richiesta.
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


def to_v2_frames(event: AgentEvent) -> list[dict[str, Any]]:
    """Traduce un evento interno nel suo frame wire v2 (0 o 1 frame).

    Args:
        event: L'``AgentEvent`` emesso dal motore.

    Returns:
        Zero o un frame wire (dict JSON-serializzabili), costruito attraverso
        il modello Pydantic del contratto: le chiavi ``None`` sono OMESSE
        (``exclude_none``), ``origin`` è presente col default ``"agent"``.
    """
    if isinstance(event, ev.TurnStartedEvent):
        return [_dump(ws.WsTurnStarted(
            type="turn.started", turn_id=event.turn_id,
            conversation_id=event.conversation_id, source=event.source,
        ))]
    if isinstance(event, ev.TurnDeltaEvent):
        return [_dump(ws.WsTurnDelta(
            type="turn.delta", turn_id=event.turn_id, step=event.step,
            kind=event.kind, text=event.text,
        ))]
    if isinstance(event, ev.LlmStepEvent):
        return [_dump(ws.WsTurnLlmStep(
            type="turn.llm_step", turn_id=event.turn_id, step=event.step,
        ))]
    if isinstance(event, ev.ToolCallEvent):
        return [_dump(ws.WsTurnToolCall(
            type="tool.call", turn_id=event.turn_id,
            execution_id=event.call.call_id, tool_name=event.call.name,
            args=event.call.args, step=event.step,
        ))]
    if isinstance(event, ev.ToolStartedEvent):
        return [_dump(ws.WsToolStarted(
            type="tool.started", turn_id=event.turn_id,
            execution_id=event.call_id, tool_name=event.name,
        ))]
    if isinstance(event, ev.ToolProgressEvent):
        return [_dump(ws.WsToolProgress(
            type="tool.progress", turn_id=event.turn_id,
            execution_id=event.call_id, tool_name=event.name,
            progress=event.progress,
        ))]
    if isinstance(event, ev.ToolResultEvent):
        return [_dump(ws.WsTurnToolResult(
            type="tool.result", turn_id=event.turn_id,
            execution_id=event.call_id, tool_name=event.name,
            status=event.status, success=event.status == "ok",
            result=event.result, content_type=event.content_type,
            artifact_id=event.artifact_id,
        ))]
    if isinstance(event, ev.InteractionRequestedEvent):
        payload = event.payload
        questions = payload.get("questions")
        return [_dump(ws.WsInteractionRequested(
            type="interaction.requested", turn_id=event.turn_id,
            interaction_id=event.interaction_id,
            execution_id=event.call_id,
            kind=_INTERACTION_KIND.get(event.kind, event.kind),
            tool_name=event.tool_name,
            args=payload.get("args"),
            risk_level=payload.get("risk_level"),
            description=payload.get("description"),
            reasoning=payload.get("reasoning"),
            allow_remember=payload.get("allow_remember"),
            questions=(
                normalize_questions(questions) if questions is not None else None
            ),
        ))]
    if isinstance(event, ev.InteractionResolvedEvent):
        return [_dump(ws.WsInteractionResolved(
            type="interaction.resolved", turn_id=event.turn_id,
            interaction_id=event.interaction_id, execution_id=event.call_id,
            kind=_INTERACTION_KIND.get(event.kind, event.kind),
            outcome=event.outcome,
        ))]
    if isinstance(event, ev.ContextUsageEvent):
        window = event.context_window or 1
        return [_dump(ws.WsContextUsage(
            type="context.usage", turn_id=event.turn_id, used=event.tokens,
            available=max(window - event.tokens, 0),
            context_window=event.context_window,
            percentage=round(event.tokens / window, 4),
            is_estimated=True,
        ))]
    if isinstance(event, ev.CompactionEvent):
        return [_dump(ws.WsContextCompaction(
            type="context.compaction", turn_id=event.turn_id,
            phase=event.phase, tokens_before=event.tokens_before,
            tokens_after=event.tokens_after, error=event.error,
        ))]
    if isinstance(event, ev.TurnWarningEvent):
        return [_dump(ws.WsTurnWarning(
            type="turn.warning", turn_id=event.turn_id, code=event.code,
            message=event.message,
        ))]
    if isinstance(event, ev.TurnErrorEvent):
        return [_dump(ws.WsTurnError(
            type="turn.error", turn_id=event.turn_id, code=event.code,
            message=event.message,
        ))]
    if isinstance(event, ev.TurnUsageEvent):
        return [_dump(ws.WsTurnUsage(
            type="turn.usage", turn_id=event.turn_id, step=event.step,
            input_tokens=event.input_tokens, output_tokens=event.output_tokens,
            cost=event.cost, tool_calls=event.tool_calls,
            max_steps=event.max_steps,
        ))]
    if isinstance(event, ev.TurnFinishedEvent):
        return [_dump(ws.WsTurnFinished(
            type="turn.finished", turn_id=event.turn_id,
            finish_reason=event.finish_reason,
            conversation_id=event.conversation_id,
            message_id=event.final_message_id or "",
            user_message_id=event.user_message_id,
            version_group_id=event.version_group_id,
            version_index=event.version_index,
            steps=event.steps, tool_calls=event.tool_calls,
            input_tokens=event.input_tokens, output_tokens=event.output_tokens,
            cost=event.cost,
        ))]
    if isinstance(event, ev.RawToolCallDeltaEvent):
        # Diagnostico Mossa 1: non ha un frame v2 (muore nel Task 10).
        return []
    return []
