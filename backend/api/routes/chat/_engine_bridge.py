"""Ponte TEMPORANEO fra il turno legacy e il motore greenfield (Fase 1).

Vive nell'api layer (non nel package ``services/agent``, che resta pulito) e
muore col Task 19, quando il motore v2 diventa l'unico path e il ``TurnInput``/
``TurnResult`` legacy spariscono. Fornisce due sole traduzioni, condivise dai
due call site del flag ``agent.engine`` (``ws.py`` e ``headless.py``):

* :func:`build_turn_request` — ``TurnInput`` (assemblato dal ``TurnAssembler``)
  → ``TurnRequest`` (input del motore);
* :func:`outcome_to_turn_result` — ``TurnOutcome`` (output del motore) →
  ``TurnResult`` (ciò che il persist path legacy, ``_persist_final_turn``,
  consuma).

Note di mappatura (``TurnInput`` → ``TurnRequest``):

* ``history`` = ``turn.messages`` — il prompt COMPLETAMENTE assemblato (system
  + memoria + storia + user), già compattato in pre-gen. È ciò che il motore
  passa come ``messages`` al path OpenAI-compatibile (l'unico usato dal motore;
  ``system_prompt`` è ridondante lì ma popolato per completezza).
* ``max_steps`` = ``llm.max_tool_iterations + 1`` — identico al calcolo del
  ``DirectTurnExecutor`` legacy.
* ``final_assistant_message_id`` resta ``None`` (come nel legacy: la
  persistenza del messaggio finale è del persist path, non del motore).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.services.agent.models import TurnRequest, TurnSource
from backend.services.turn.models import TurnResult

if TYPE_CHECKING:
    from backend.core.context import AppContext
    from backend.services.agent.models import TurnOutcome
    from backend.services.turn.models import TurnInput


def build_turn_request(
    ctx: AppContext,
    turn: TurnInput,
    *,
    source: TurnSource,
    max_tool_calls: int | None,
) -> TurnRequest:
    """Traduce un ``TurnInput`` assemblato in una ``TurnRequest`` per il motore.

    Args:
        ctx: L'``AppContext`` (per ``llm.max_tool_iterations``).
        turn: Il ``TurnInput`` prodotto dal ``TurnAssembler``.
        source: Origine del turno (chat/voice/headless).
        max_tool_calls: Cap di tool call ESEGUITE (trim voce), o ``None``.

    Returns:
        La ``TurnRequest`` equivalente.
    """
    return TurnRequest(
        conversation_id=str(turn.conv_id),
        system_prompt=turn.cached_sys_prompt or "",
        history=turn.messages,
        tools=turn.tools or [],
        source=source,
        max_steps=ctx.config.llm.max_tool_iterations + 1,
        context_window=turn.context_window,
        resolved_max_tokens=turn.resolved_max_tokens,
        client_ip=turn.client_ip,
        version_group_id=(
            str(turn.version_group_id) if turn.version_group_id else None
        ),
        version_index=turn.version_index,
        max_tool_calls=max_tool_calls,
    )


def outcome_to_turn_result(outcome: TurnOutcome) -> TurnResult:
    """Traduce un ``TurnOutcome`` del motore nel ``TurnResult`` del persist path.

    ``had_tool_calls`` deriva da ``outcome.tool_calls > 0`` (il persist path lo
    usa per decidere se saltare la persistenza di un messaggio finale vuoto:
    gli intermedi con tool call sono già stati committati dal motore).
    """
    return TurnResult(
        content=outcome.content,
        thinking=outcome.thinking,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
        finish_reason=outcome.finish_reason,
        cost=outcome.cost,
        final_assistant_message_id=None,
        had_tool_calls=outcome.tool_calls > 0,
    )
