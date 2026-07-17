"""Adapter ``ContextPort`` -> ``ContextManager`` (piattaforma).

Consuma ``backend/services/context_manager.py`` (``ContextManager``). La Port
del motore (``estimate_tokens``, ``should_compact``, ``compact``) e l'API
reale del servizio non coincidono 1:1 — le divergenze e il mapping adottato
sono documentati qui:

- ``ContextPort.estimate_tokens(messages) -> int`` vs
  ``ContextManager.estimate_tokens(text: str) -> int`` (singola stringa).
  Il servizio espone anche ``count_messages_tokens(messages) -> int``, che è
  la funzione realmente equivalente alla firma della Port — usata qui.
- ``ContextPort.should_compact(*, tokens, context_window) -> bool`` vs
  ``ContextManager.should_compress(usage: ContextUsage) -> bool`` (prende uno
  snapshot già costruito, non tokens/context_window grezzi). Costruiamo lo
  snapshot con ``get_usage_real(tokens, context_window)`` (stessa formula di
  percentuale/available usata per i conteggi "reali" da token-count API) e
  deleghiamo la soglia a ``should_compress``.
- ``ContextPort.compact(*, messages, context_window) -> CompactionResult`` vs
  ``ContextManager.compress(messages, llm, context_window, reserve,
  tool_tokens=0) -> CompressionResult``: la Port NON passa ``llm``/``reserve``/
  ``tool_tokens`` — l'adapter li porta come stato di costruzione
  (``llm_service`` iniettato al costruttore per compattazioni riassuntive via
  ``complete_nonstreaming``; ``reserve`` da ``LLMConfig.context_compression_reserve``,
  la stessa lettura usata dagli altri call-site di piattaforma, es.
  ``backend/api/routes/chat/_persist.py``). ``tool_tokens`` non è comunicabile
  dalla Port attuale (il motore non passa il costo-token delle tool
  definitions a ``compact``) — resta a 0, quindi il budget calcolato da
  ``compress`` è leggermente ottimistico quando le tool definitions occupano
  una fetta non trascurabile della finestra; accettabile per Fase 1
  (nessuna regressione, solo un margine di sicurezza in meno).
- ``CompressionResult`` non porta ID messaggio per gli archiviati (lavora su
  dict di messaggio, non ID persistiti). ``CompactionResult.archived_message_ids``
  è quindi ricavato per posizione: separiamo ``messages`` in ``system`` /
  ``conv`` esattamente come fa ``compress`` internamente, prendiamo i primi
  ``result.split_index`` messaggi di conversazione come "archiviati" ed
  estraiamo la loro chiave ``"id"`` quando presente nel dict (i messaggi
  passati a questo livello sono spesso semplici dict OpenAI-shape senza
  ``id`` — in quel caso la tupla risultante è vuota: nessun ID da segnalare,
  ma la compattazione è comunque avvenuta con successo).
- Un'eccezione durante ``compress`` (tipicamente ``CompressionError``, ma
  qualunque eccezione non-``CancelledError``) viene catturata e mappata a
  ``performed=False, error=str(exc)`` — mai propagata.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from backend.services.agent.ports import CompactionResult

if TYPE_CHECKING:
    from backend.core.config import LLMConfig
    from backend.services.context_manager import ContextManager
    from backend.services.llm_service import LLMService


class ContextManagerAdapter:
    """Implementa ``ContextPort`` sopra ``ContextManager``."""

    def __init__(
        self,
        context_manager: ContextManager,
        llm_service: LLMService,
        config: LLMConfig,
    ) -> None:
        """Inizializza l'adapter.

        Args:
            context_manager: Il servizio di gestione/compattazione contesto.
            llm_service: LLM usato da ``ContextManager.compress`` per
                generare il riassunto (``complete_nonstreaming``).
            config: Config LLM di piattaforma, da cui si legge
                ``context_compression_reserve`` (la Port non lo passa
                per-call).
        """
        self._cm = context_manager
        self._llm = llm_service
        self._reserve = config.context_compression_reserve

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Stima i token totali della lista messaggi."""
        return self._cm.count_messages_tokens(messages)

    def should_compact(self, *, tokens: int, context_window: int) -> bool:
        """Decide se compattare, dato il conteggio token corrente."""
        usage = self._cm.get_usage_real(tokens, context_window)
        return self._cm.should_compress(usage)

    async def compact(
        self, *, messages: list[dict[str, Any]], context_window: int,
    ) -> CompactionResult:
        """Compatta la lista messaggi via riassunto LLM; non solleva mai."""
        tokens_before = self._cm.count_messages_tokens(messages)
        try:
            result = await self._cm.compress(
                messages, self._llm, context_window, self._reserve,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — mai propagare, mappa in CompactionResult
            return CompactionResult(
                performed=False,
                summary_text=None,
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                error=str(exc),
            )

        conv_msgs = [m for m in messages if m.get("role") != "system"]
        archived = conv_msgs[: result.split_index]
        archived_ids = tuple(
            str(m["id"]) for m in archived if isinstance(m, dict) and "id" in m
        )

        return CompactionResult(
            performed=True,
            summary_text=result.summary_text,
            tokens_before=tokens_before,
            tokens_after=result.usage.used_tokens,
            kept_messages=tuple(result.messages),
            archived_message_ids=archived_ids,
        )
