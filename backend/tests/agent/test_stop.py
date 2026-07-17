"""Stop conditions: precedenza disconnect > cancel > error > budget > length."""

from backend.services.agent.models import StopReason
from backend.services.agent.stop import BudgetTracker, resolve_stop


def test_budget_tracker_counts_and_caps() -> None:
    b = BudgetTracker(max_steps=2)
    assert b.begin_step() == 1
    assert b.out_of_steps() is False
    assert b.begin_step() == 2
    assert b.out_of_steps() is True


def test_precedence_disconnect_beats_everything() -> None:
    assert resolve_stop(
        llm_finish="stop", cancelled=True, disconnected=True,
        out_of_steps=True, errored=True,
    ) is StopReason.DISCONNECTED


def test_precedence_cancel_beats_error_and_budget() -> None:
    assert resolve_stop(
        llm_finish=None, cancelled=True, disconnected=False,
        out_of_steps=True, errored=True,
    ) is StopReason.CANCELLED


def test_length_and_completed() -> None:
    common = dict(cancelled=False, disconnected=False, out_of_steps=False, errored=False)
    assert resolve_stop(llm_finish="length", **common) is StopReason.LENGTH
    assert resolve_stop(llm_finish="stop", **common) is StopReason.COMPLETED


def test_precedence_error_beats_budget() -> None:
    assert resolve_stop(
        llm_finish=None, cancelled=False, disconnected=False,
        out_of_steps=True, errored=True,
    ) is StopReason.ERROR


def test_precedence_budget_beats_length() -> None:
    assert resolve_stop(
        llm_finish="length", cancelled=False, disconnected=False,
        out_of_steps=True, errored=False,
    ) is StopReason.MAX_STEPS
