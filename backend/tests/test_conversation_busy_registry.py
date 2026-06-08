"""AL\\CE — Tests for the per-conversation busy registry (Fase 6b).

Pure unit tests of the idle-guard primitives in
:mod:`backend.api.routes.chat._shared`.  No WebSocket and no app
construction are involved — only the module-level ``set[str]`` registry and
its public query/context-manager API.
"""

from __future__ import annotations

import pytest

from backend.api.routes.chat import _shared
from backend.api.routes.chat._shared import (
    conversation_active,
    is_conversation_active,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    """Isolate each test: empty the registry before and after."""
    _shared._active_conversations.clear()
    yield
    _shared._active_conversations.clear()


def test_unknown_conversation_is_idle() -> None:
    """A never-seen conversation reports idle (not busy)."""
    assert is_conversation_active("c1") is False


def test_context_manager_marks_active_then_clears() -> None:
    """The CM marks the id busy inside the block and idle after exit."""
    assert is_conversation_active("c1") is False
    with conversation_active("c1"):
        assert is_conversation_active("c1") is True
    assert is_conversation_active("c1") is False


def test_context_manager_clears_on_exception() -> None:
    """The ``finally`` discard runs even when the body raises."""
    # ``conversation_active`` is the inner (rightmost) context, so its
    # ``finally``/discard runs before ``pytest.raises`` catches the error.
    with pytest.raises(RuntimeError), conversation_active("c1"):
        assert is_conversation_active("c1") is True
        raise RuntimeError("boom")
    # Proves the registry is not wedged "busy" after a crashed turn.
    assert is_conversation_active("c1") is False


def test_reentrant_single_membership() -> None:
    """Nested entries collapse to one ``set[str]`` membership.

    Entering the CM twice for the same id and exiting once leaves the
    conversation idle: the accepted ``set[str]`` semantics carry no
    ref-count, so the inner exit's ``discard`` already removes the id.
    """
    with conversation_active("c1"):
        with conversation_active("c1"):
            assert is_conversation_active("c1") is True
        # Inner CM exited -> the single membership is already gone.
        assert is_conversation_active("c1") is False
    assert is_conversation_active("c1") is False


def test_distinct_conversations_are_independent() -> None:
    """Marking one conversation busy does not affect another."""
    with conversation_active("c1"):
        assert is_conversation_active("c1") is True
        assert is_conversation_active("c2") is False
    assert is_conversation_active("c1") is False
    assert is_conversation_active("c2") is False
