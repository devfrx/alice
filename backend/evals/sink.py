"""AL\\CE — Sink di registrazione per l'eval harness.

Deliberatamente indipendente da ``backend.services.turn`` (in demolizione,
Task 19 del piano Fase 1 AgentEngine): l'eval harness è il gate che valida
la demolizione, quindi non può dipendere dal modulo che sta morendo.

:class:`RecordingSink` soddisfa per tipizzazione strutturale il parametro
``sink: WSEventSink | None`` di
:func:`backend.api.routes.chat.headless.run_headless_turn` — stessa forma
(``send``/``is_connected``) del protocollo ``WSEventSink``
(``services/turn/sink.py``), senza importarlo.
"""

from __future__ import annotations

import contextlib
from typing import Any


class RecordingSink:
    """Test double dell'eval harness: registra ogni evento del turno.

    ``is_connected`` è sempre ``True`` per contratto: la Fase 0 ha fissato
    che l'executor tronca lo stream quando il sink risulta disconnesso, e
    l'eval harness deve sempre osservare la trace completa.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def send(self, event: dict[str, Any]) -> None:
        """Registra ``event`` (copia shallow); non solleva mai."""
        with contextlib.suppress(Exception):
            event = dict(event)
        self.events.append(event)

    @property
    def is_connected(self) -> bool:
        """Sempre ``True`` — contratto dell'eval harness."""
        return True


__all__ = ["RecordingSink"]
