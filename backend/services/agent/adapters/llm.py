"""Adapter ``LLMPort`` -> ``LLMService`` (piattaforma).

Traduce i chunk dict grezzi prodotti da :class:`backend.services.llm_service.LLMService`
(che delega a :class:`backend.services.llm.client.LLMClient`) negli ``LLMEvent``
tipizzati del motore.

Contratto reale dei chunk (verificato leggendo il codice, NON assunto dallo
spec) — ``backend/services/llm/client.py``:

- ``{"type": "token", "content": str}`` — delta di testo
  (``_chat_openai_compat`` riga 756, ``_stream_lmstudio_native_sse`` righe
  403/398).
- ``{"type": "thinking", "content": str}`` — delta di ragionamento
  (riga 744 / 389).
- ``{"type": "tool_call", "id": str, "function": {"name": str, "arguments": str}}``
  — righe 678-685 e 804-811: **UNA tool-call GIA COMPLETA per chunk**, non un
  delta parziale incrementale con indice. ``LLMClient`` accumula internamente
  i frammenti SSE del provider (``tool_calls_acc``, chiave = indice OpenAI) e
  fa il flush di UN chunk per tool-call completa quando arriva ``[DONE]`` (o a
  fine stream). Non esiste quindi, al livello del contratto consumato da
  questo adapter, un chunk ``tool_call`` con argomenti parziali da fondere per
  indice — l'accumulo "incrementale" richiesto dal brief di Task 12 è
  comunque implementato qui in forma difensiva (accumula per ``id``, gestisce
  ``name``/``arguments`` mancanti come stringa vuota) per restare corretto
  anche se il contratto dovesse tornare a essere realmente incrementale in
  futuro, ma con l'attuale servizio ogni tool-call arriva già completa in un
  solo chunk.
- ``{"type": "usage", "input_tokens": int, "output_tokens": int, "cost"?: float}``
  — righe 686-692 (OAI-compat, ``cost`` presente solo se il provider la
  riporta, es. OpenRouter) e righe 422-429 (nativo LM Studio, **senza**
  ``cost``).
- ``{"type": "error", "content": str}`` — righe 711-726 (OAI-compat) e
  453-475 (nativo). **Nessuno status HTTP è incluso nel chunk emesso** — sia
  il path nativo che quello OAI-compat catturano solo un messaggio testuale
  (l'eventuale ``err_type``/status HTTP viene solo loggato, mai propagato nel
  dict yieldato). Questo diverge dall'assunzione del brief ("status HTTP 4xx
  identificabile nel chunk"): l'adapter cerca comunque, in modo difensivo, le
  chiavi ``status_code``/``status``/``http_status`` nel chunk (per restare
  compatibile con un futuro arricchimento del contratto), ma con il
  comportamento ATTUALE del servizio questi campi sono sempre assenti, quindi
  ``retryable`` sarà sempre ``True`` per gli errori di streaming reali oggi.
  **Divergenza documentata dal legacy fail-fast** (Minor da review): poiché
  nessun errore di streaming reale porta oggi uno status code, un errore
  permanente (es. un 4xx del provider mascherato da messaggio testuale senza
  status strutturato) viene comunque riprovato — ``RetryPolicy.on_failure``
  ritenta fino a ``max_transient_retries`` tentativi (default 2, vedi
  ``backend/services/agent/retry.py``) prima di fallire il turno, invece di
  fallire immediatamente come faceva la pipeline legacy sugli errori 4xx. Se
  il servizio LLM viene arricchito in futuro con lo status code reale nel
  chunk ``error``, questo adapter lo userà già correttamente (``retryable``
  diventerebbe ``False`` per i 4xx, ripristinando il fail-fast) senza alcuna
  modifica.
- ``{"type": "done", "finish_reason": str}`` — ``finish_reason`` è il valore
  grezzo del provider (``"stop"``, ``"length"``, ``"cancelled"``,
  ``"tool_calls"``, ...), propagato verbatim.

Nota: questo adapter non passa mai ``user_content`` a ``LLMService.chat`` (la
porta del motore lavora solo su ``messages``/``system_prompt``), quindi il
path nativo LM Studio (``use_native`` in ``client.py``, che richiede
``user_content is not None``) non viene mai selezionato da qui: lo streaming
passa sempre per l'endpoint OpenAI-compatibile. Comportamento corretto e
atteso per il motore greenfield (nessuna dipendenza dalla convenzione
``user_content`` del pipeline legacy).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from backend.services.agent.models import normalize_tool_invocations
from backend.services.agent.ports import (
    LLMEvent,
    LLMFailure,
    LLMStepDone,
    LLMTextDelta,
    LLMThinkingDelta,
    LLMUsage,
)

if TYPE_CHECKING:
    from backend.services.llm_service import LLMService


class LLMServiceAdapter:
    """Implementa ``LLMPort`` sopra ``LLMService.chat``."""

    def __init__(self, llm: LLMService) -> None:
        """Inizializza l'adapter.

        Args:
            llm: Il servizio LLM di piattaforma (facade su ``backend/services/llm/``).
        """
        self._llm = llm

    def supports_vision(self) -> bool:
        """True se il modello attivo accetta input immagine (vision).

        Delega alla property ``LLMService.supports_vision`` (che a sua volta
        interroga ``ModelResolver.supports_vision`` sul modello attivo).
        """
        return bool(self._llm.supports_vision)

    async def stream_step(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None,
        cancel: asyncio.Event,
    ) -> AsyncIterator[LLMEvent]:
        """Stream di uno step LLM, tradotto in ``LLMEvent`` tipizzati.

        Accumula i chunk ``tool_call`` (per ``id``, vedi docstring di modulo)
        e li normalizza in un unico ``LLMStepDone`` quando arriva ``done``.
        """
        # Accumulatore: id tool-call -> raw dict OpenAI-shape per
        # normalize_tool_invocations. L'ordine di prima apparizione è
        # preservato (dict Python 3.7+).
        accumulated: dict[str, dict[str, Any]] = {}
        # Tool-call senza id (difensivo — non accade nel contratto attuale):
        # accumulate per posizione crescente in una chiave sintetica.
        _anon_counter = 0

        async for chunk in self._llm.chat(
            messages,
            tools=tools or None,
            cancel_event=cancel,
            system_prompt=system_prompt,
            max_output_tokens=max_tokens,
        ):
            chunk_type = chunk.get("type")

            if chunk_type == "token":
                yield LLMTextDelta(text=chunk.get("content", "") or "")
            elif chunk_type == "thinking":
                yield LLMThinkingDelta(text=chunk.get("content", "") or "")
            elif chunk_type == "tool_call":
                call_id = chunk.get("id") or ""
                fn = chunk.get("function") or {}
                key = call_id
                if not key:
                    _anon_counter += 1
                    key = f"__anon_{_anon_counter}"
                if key in accumulated:
                    entry = accumulated[key]
                    if fn.get("name"):
                        entry["function"]["name"] = fn["name"]
                    if fn.get("arguments") is not None:
                        entry["function"]["arguments"] += fn["arguments"]
                else:
                    accumulated[key] = {
                        "id": call_id,
                        "function": {
                            "name": fn.get("name", "") or "",
                            "arguments": fn.get("arguments", "") or "",
                        },
                    }
            elif chunk_type == "usage":
                yield LLMUsage(
                    input_tokens=chunk.get("input_tokens", 0) or 0,
                    output_tokens=chunk.get("output_tokens", 0) or 0,
                    cost=chunk.get("cost") or 0.0,
                )
            elif chunk_type == "error":
                status = (
                    chunk.get("status_code")
                    or chunk.get("status")
                    or chunk.get("http_status")
                )
                status_code = status if isinstance(status, int) else None
                retryable = not (status_code is not None and 400 <= status_code < 500)
                yield LLMFailure(
                    message=chunk.get("content", "") or "unknown LLM error",
                    status_code=status_code,
                    retryable=retryable,
                )
            elif chunk_type == "done":
                yield LLMStepDone(
                    finish_reason=chunk.get("finish_reason", "stop") or "stop",
                    tool_calls=normalize_tool_invocations(list(accumulated.values())),
                )
            # Chunk di tipo sconosciuto: ignorato (parity difensiva —
            # il contratto verificato non ne produce altri).
