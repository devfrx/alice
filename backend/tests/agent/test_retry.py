"""Retry policy: empty-response nudge; transient sì, HTTP status fail-fast."""

from backend.services.agent.ports import LLMFailure
from backend.services.agent.retry import EMPTY_NUDGE, RetryPolicy


def test_empty_response_retries_with_nudge_then_gives_up() -> None:
    p = RetryPolicy(max_empty_retries=2)
    d1 = p.on_empty_response(attempt=1)
    assert d1.retry is True and d1.nudge == EMPTY_NUDGE
    assert p.on_empty_response(attempt=2).retry is True
    assert p.on_empty_response(attempt=3).retry is False


def test_transient_failure_retries_within_budget() -> None:
    p = RetryPolicy(max_transient_retries=2)
    f = LLMFailure(message="conn reset", status_code=None, retryable=True)
    assert p.on_failure(f, attempt=1).retry is True
    assert p.on_failure(f, attempt=3).retry is False


def test_http_status_failure_is_fail_fast() -> None:
    p = RetryPolicy()
    f = LLMFailure(message="400 bad request", status_code=400, retryable=False)
    assert p.on_failure(f, attempt=1).retry is False
