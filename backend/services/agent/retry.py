"""Retry policy for LLM failures and empty responses."""
from __future__ import annotations

from dataclasses import dataclass

from backend.services.agent.ports import LLMFailure

EMPTY_NUDGE = (
    "La tua risposta precedente era vuota. Continua il lavoro: rispondi con il "
    "contenuto o con la prossima tool call."
)


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """Decision to retry or fail."""

    retry: bool
    nudge: str | None = None


class RetryPolicy:
    """Policy for determining when to retry LLM calls."""

    def __init__(
        self, *, max_empty_retries: int = 2, max_transient_retries: int = 2
    ) -> None:
        """Initialize retry policy.

        Args:
            max_empty_retries: Maximum retries for empty responses (attempt starts at 1).
            max_transient_retries: Maximum retries for transient failures.
        """
        self.max_empty_retries = max_empty_retries
        self.max_transient_retries = max_transient_retries

    def on_empty_response(self, attempt: int) -> RetryDecision:
        """Decide whether to retry an empty response.

        Args:
            attempt: Current attempt number (1-indexed).

        Returns:
            RetryDecision with retry=True and nudge if attempt <= max_empty_retries.
        """
        if attempt <= self.max_empty_retries:
            return RetryDecision(retry=True, nudge=EMPTY_NUDGE)
        return RetryDecision(retry=False)

    def on_failure(self, failure: LLMFailure, attempt: int) -> RetryDecision:
        """Decide whether to retry an LLM failure.

        Args:
            failure: The LLM failure details.
            attempt: Current attempt number (1-indexed).

        Returns:
            RetryDecision. Never retries if failure.retryable=False (fail-fast).
            Retries if retryable=True and attempt <= max_transient_retries.
        """
        if not failure.retryable:
            return RetryDecision(retry=False)
        if attempt <= self.max_transient_retries:
            return RetryDecision(retry=True)
        return RetryDecision(retry=False)
