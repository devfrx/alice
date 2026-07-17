"""DTO del motore: normalizzazione tool call e mapping finish_reason."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TurnSource(StrEnum):
    """Origine del turno."""

    CHAT = "chat"
    VOICE = "voice"
    HEADLESS = "headless"


class StopReason(StrEnum):
    """Motivo della fine dell'esecuzione del turno."""

    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    CANCELLED = "cancelled"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    LENGTH = "length"


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """Tool call normalizzato dal modello.

    Attributi:
        call_id: ID univoco normalizzato (call_<uuid> se assente).
        name: Nome del tool.
        args: Argomenti parsati come dict. {} se JSON invalido.
        raw_args: Stringa grezzo degli argomenti.
        parse_error: Messaggio di errore se parsing fallito, None altrimenti.
    """

    call_id: str
    name: str
    args: dict[str, Any]
    raw_args: str
    parse_error: str | None = None


@dataclass(frozen=True, slots=True)
class ToolMeta:
    """Metadati di un tool dal registry.

    Attributi:
        exists: True se il tool esiste nel registry.
        client_executed: True se eseguito dal client/UI.
        interactive: Tipo di interazione ("ask_user" per wizard, None altrimenti).
        timeout_s: Timeout in secondi, None per default.
    """

    exists: bool
    client_executed: bool = False
    interactive: str | None = None
    timeout_s: float | None = None


@dataclass(frozen=True, slots=True)
class TurnRequest:
    """Richiesta di esecuzione di un turno.

    Attributi:
        conversation_id: ID della conversazione.
        system_prompt: Prompt di sistema per il modello.
        history: Cronologia messaggi in formato OpenAI.
        tools: Definizioni tool in formato OpenAI.
        source: Origine del turno.
        max_steps: Budget di step LLM.
        context_window: Dimensione della finestra di contesto.
        resolved_max_tokens: Token massimi risolti, None se non disponibile.
        client_ip: IP del client, None se headless.
        version_group_id: ID del gruppo versione della conversazione.
        version_index: Indice della versione.
        max_tool_calls: Budget di tool call ESEGUITE nel turno (trim voce,
            `agent.voice.max_tools`). None = illimitato (default).
    """

    conversation_id: str
    system_prompt: str
    history: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    source: TurnSource
    max_steps: int
    context_window: int
    resolved_max_tokens: int | None
    client_ip: str | None
    version_group_id: str | None
    version_index: int | None
    max_tool_calls: int | None = None


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """Risultato dell'esecuzione di un turno.

    Attributi:
        content: Contenuto della risposta finale.
        thinking: Testo del ragionamento del modello.
        finish_reason: Vocabolario legacy (Global Constraints).
        stop_reason: Motivo della fine (nuovo vocabolario).
        steps: Numero di step LLM eseguiti.
        tool_calls: Numero di tool call eseguiti.
        input_tokens: Token di input utilizzati.
        output_tokens: Token di output generati.
        cost: Costo computazionale.
        final_assistant_message_id: ID del messaggio assistant finale.
    """

    content: str
    thinking: str
    finish_reason: str
    stop_reason: StopReason
    steps: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost: float
    final_assistant_message_id: str | None


def normalize_tool_invocations(
    raw: list[dict[str, Any]],
) -> tuple[ToolInvocation, ...]:
    """Normalizza le tool call del modello: ID sempre presenti, JSON validato.

    Invariante §6.1.2: gli ID sono assegnati QUI, una volta, così assistant
    message e tool response condividono lo stesso valore.

    Args:
        raw: Lista raw di tool call dal modello.

    Returns:
        Tuple di ToolInvocation normalizzati.
    """
    out: list[ToolInvocation] = []
    for item in raw:
        fn = item.get("function") or {}
        call_id = item.get("id") or f"call_{uuid.uuid4().hex}"
        name = fn.get("name") or ""
        raw_args = fn.get("arguments") or "{}"
        args: dict[str, Any] = {}
        parse_error: str | None = None
        if not name:
            parse_error = "tool call senza nome"
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                args = parsed
            else:
                parse_error = parse_error or "argomenti non-oggetto"
        except json.JSONDecodeError as exc:
            parse_error = parse_error or f"argomenti non parsabili: {exc}"
        out.append(
            ToolInvocation(
                call_id=call_id,
                name=name,
                args=args,
                raw_args=raw_args,
                parse_error=parse_error,
            )
        )
    return tuple(out)


STOP_TO_FINISH: dict[StopReason, str] = {
    StopReason.COMPLETED: "stop",
    StopReason.MAX_STEPS: "stop",
    StopReason.LENGTH: "length",
    StopReason.CANCELLED: "cancelled",
    StopReason.DISCONNECTED: "disconnected",
    StopReason.ERROR: "error",
}
