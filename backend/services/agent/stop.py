"""Budget tracking e stop conditions con precedenza esplicita."""

from __future__ import annotations

from backend.services.agent.models import StopReason


class BudgetTracker:
    """Tracker per il budget di step LLM.

    Attributi:
        max_steps: Numero massimo di step consentiti.
        _steps: Numero di step attuali (0-based internamente).
    """

    def __init__(self, *, max_steps: int) -> None:
        """Inizializza il tracker.

        Args:
            max_steps: Numero massimo di step consentiti.
        """
        self.max_steps = max_steps
        self._steps = 0

    def begin_step(self) -> int:
        """Incrementa il contatore e ritorna il numero step (1-based).

        Returns:
            Numero dello step corrente (1-based).
        """
        self._steps += 1
        return self._steps

    @property
    def steps(self) -> int:
        """Ritorna il numero di step eseguiti.

        Returns:
            Numero di step attuali.
        """
        return self._steps

    def out_of_steps(self) -> bool:
        """Verifica se il budget è esaurito.

        Returns:
            True se steps >= max_steps, False altrimenti.
        """
        return self._steps >= self.max_steps


def resolve_stop(
    *,
    llm_finish: str | None,
    cancelled: bool,
    disconnected: bool,
    out_of_steps: bool,
    errored: bool,
) -> StopReason:
    """Risolve il motivo della fine dell'esecuzione secondo precedenza esplicita.

    Precedenza (dall'alto): disconnected → DISCONNECTED; cancelled →
    CANCELLED; errored → ERROR; out_of_steps → MAX_STEPS; llm_finish ==
    "length" → LENGTH; altrimenti COMPLETED.

    Args:
        llm_finish: Finish reason dal modello (es. "stop", "length").
        cancelled: True se il turno è stato cancellato.
        disconnected: True se il client si è disconnesso.
        out_of_steps: True se il budget di step è esaurito.
        errored: True se si è verificato un errore.

    Returns:
        StopReason risolta secondo la precedenza.
    """
    if disconnected:
        return StopReason.DISCONNECTED
    if cancelled:
        return StopReason.CANCELLED
    if errored:
        return StopReason.ERROR
    if out_of_steps:
        return StopReason.MAX_STEPS
    if llm_finish == "length":
        return StopReason.LENGTH
    return StopReason.COMPLETED
