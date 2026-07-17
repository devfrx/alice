"""Adapter di parità: traduce ``AgentEvent`` nei frame wire ATTUALI.

THROWAWAY (Mossa 2 lo elimina). Vive per DIMOSTRARE che il motore greenfield
produce uno stream wire equivalente al legacy: ogni frame prodotto qui DEVE
validare contro il contratto chat corrente (``backend/api/ws_schema/chat.py``).

PILASTRO: questo modulo NON legge ``backend.services.turn``. La tabella di
mappatura sotto è la fonte normativa; l'unico codice esistente consultato è il
CONTRATTO wire (``chat.py``), non il motore legacy.

Tabella normativa (evento interno → frame wire attuali, legacy + canonici):

    TurnStartedEvent          → [turn.started]
    LlmStepEvent              → [llm_requery (solo step>1), turn.llm_step]
    TurnDeltaEvent(text)      → [token]
    TurnDeltaEvent(thinking)  → [thinking]
    RawToolCallDeltaEvent     → [tool_call]                 # relay raw legacy
    ToolCallEvent             → [tool.call]
    ToolStartedEvent          → [tool_execution_start]
    ToolProgressEvent         → [tool_progress]
    ToolResultEvent           → [tool_execution_done, tool.result]
    InteractionRequestedEvent → [interaction.requested]
    InteractionResolvedEvent  → [interaction.resolved]
    ContextUsageEvent         → [context_info]
    CompactionEvent           → [context_compression_start|done|failed]
    TurnWarningEvent          → [warning]
    TurnErrorEvent            → [error]
    TurnUsageEvent            → [turn.usage]
    TurnFinishedEvent         → [turn.finished]             # `done` lo emette
                                # _persist_final_turn in ws.py, NON il translator

Note su campi assenti nell'evento greenfield rispetto al frame legacy (il
motore ha scartato deliberatamente campi ridondanti, recuperabili altrove):

* ``ToolStartedEvent`` porta solo ``call_id`` → ``tool_execution_start.tool_name``
  è ``""`` (il nome vive sul ``tool.call`` correlato per ``execution_id``).
* ``InteractionRequestedEvent`` non porta il nome tool → ``tool_name`` omesso.
* ``TurnUsageEvent`` non porta ``tool_calls``/``max_steps`` → riempiti a ``0``
  (i contatori veri vivono su ``turn.finished`` e sui contatori di turno).

Le chiavi opzionali ``None`` (``content_type``/``artifact_id``/``tool_name``)
sono OMESSE dai frame, come fanno i builder canonici legacy, così i frame
restano stretti e la parità sul wire non inciampa su ``None`` vs assente.
"""

from __future__ import annotations

from typing import Any

from backend.services.agent import events as ev
from backend.services.agent.events import AgentEvent

# Mappa il ``kind`` interno dell'interazione al vocabolario wire
# (``InteractionKind`` in chat.py: tool_confirmation|client_tool_call|ask_user).
_INTERACTION_KIND: dict[str, str] = {
    "confirm": "tool_confirmation",
    "client": "client_tool_call",
    "ask_user": "ask_user",
}


def _interaction_kind(kind: str) -> str:
    """Traduce il ``kind`` interno nel valore ``InteractionKind`` del contratto."""
    return _INTERACTION_KIND.get(kind, kind)


def to_wire_frames(event: AgentEvent) -> list[dict[str, Any]]:
    """Traduce un evento interno nei frame wire attuali (legacy + canonici).

    Args:
        event: L'``AgentEvent`` emesso dal motore.

    Returns:
        Zero o più frame wire (dict JSON-serializzabili). Ogni frame DEVE
        validare contro ``validate_chat_server`` (guard strict).
    """
    if isinstance(event, ev.TurnStartedEvent):
        return [{
            "type": "turn.started",
            "turn_id": event.turn_id,
            "conversation_id": event.conversation_id,
        }]

    if isinstance(event, ev.TurnDeltaEvent):
        frame_type = "token" if event.kind == "text" else "thinking"
        return [{"type": frame_type, "content": event.text}]

    if isinstance(event, ev.LlmStepEvent):
        frames: list[dict[str, Any]] = []
        if event.step > 1:
            # ``iteration`` legacy = numero della RE-QUERY (1-based): lo step N
            # (N>1) è la (N-1)-esima re-query dopo l'esecuzione tool.
            frames.append({"type": "llm_requery", "iteration": event.step - 1})
        frames.append({
            "type": "turn.llm_step",
            "turn_id": event.turn_id,
            "step": event.step,
        })
        return frames

    if isinstance(event, ev.RawToolCallDeltaEvent):
        payload = event.payload
        function = payload.get("function") or {}
        return [{
            "type": "tool_call",
            "id": str(payload.get("id") or ""),
            "function": {
                "name": str(function.get("name") or ""),
                "arguments": str(function.get("arguments") or ""),
            },
        }]

    if isinstance(event, ev.ToolCallEvent):
        return [{
            "type": "tool.call",
            "turn_id": event.turn_id,
            "execution_id": event.call.call_id,
            "tool_name": event.call.name,
            "args": event.call.args,
        }]

    if isinstance(event, ev.ToolStartedEvent):
        # ToolStartedEvent porta solo call_id: il nome vive sul tool.call.
        return [{
            "type": "tool_execution_start",
            "tool_name": "",
            "execution_id": event.call_id,
        }]

    if isinstance(event, ev.ToolProgressEvent):
        frame: dict[str, Any] = {
            **event.progress,
            "type": "tool_progress",
            "tool_name": "",
            "execution_id": event.call_id,
        }
        return [frame]

    if isinstance(event, ev.ToolResultEvent):
        success = event.status == "ok"
        done: dict[str, Any] = {
            "type": "tool_execution_done",
            "tool_name": event.name,
            "result": event.content_preview,
            "execution_id": event.call_id,
            "success": success,
        }
        canonical: dict[str, Any] = {
            "type": "tool.result",
            "turn_id": event.turn_id,
            "execution_id": event.call_id,
            "tool_name": event.name,
            "success": success,
            "result": event.content_preview,
        }
        if event.artifact_id is not None:
            done["artifact_id"] = event.artifact_id
            canonical["artifact_id"] = event.artifact_id
        return [done, canonical]

    if isinstance(event, ev.InteractionRequestedEvent):
        # Il nome tool non è nell'evento greenfield → chiave omessa.
        return [{
            "type": "interaction.requested",
            "turn_id": event.turn_id,
            "execution_id": event.call_id,
            "kind": _interaction_kind(event.kind),
        }]

    if isinstance(event, ev.InteractionResolvedEvent):
        # L'evento greenfield non porta call_id: usa interaction_id come
        # execution_id (id volatile, normalizzato via drop nel harness).
        return [{
            "type": "interaction.resolved",
            "turn_id": event.turn_id,
            "execution_id": event.interaction_id,
            "kind": _interaction_kind(event.kind),
            "outcome": event.outcome,
        }]

    if isinstance(event, ev.ContextUsageEvent):
        window = event.context_window or 1
        used = event.tokens
        return [{
            "type": "context_info",
            "used": used,
            "available": max(window - used, 0),
            "context_window": event.context_window,
            "percentage": (used / window) * 100.0,
            "was_compressed": False,
            "messages_summarized": 0,
        }]

    if isinstance(event, ev.CompactionEvent):
        if event.phase == "started":
            return [{"type": "context_compression_start"}]
        if event.phase == "done":
            return [{
                "type": "context_compression_done",
                "messages_summarized": 0,
            }]
        return [{"type": "context_compression_failed"}]

    if isinstance(event, ev.TurnWarningEvent):
        return [{"type": "warning", "content": event.message}]

    if isinstance(event, ev.TurnErrorEvent):
        return [{"type": "error", "content": event.message}]

    if isinstance(event, ev.TurnUsageEvent):
        # tool_calls/max_steps non sono nell'evento greenfield → 0.
        return [{
            "type": "turn.usage",
            "turn_id": event.turn_id,
            "step": event.step,
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
            "tool_calls": 0,
            "max_steps": 0,
        }]

    if isinstance(event, ev.TurnFinishedEvent):
        # TurnFinishedEvent non porta i token del passo finale → 0.
        return [{
            "type": "turn.finished",
            "turn_id": event.turn_id,
            "finish_reason": event.finish_reason,
            "input_tokens": 0,
            "output_tokens": 0,
            "steps": event.steps,
            "cost": event.cost,
        }]

    # Difesa: un evento non mappato non produce frame (mai solleva).
    return []
