"""Per-conversation read-before-write tracking (Claude Code model).

In-memory, process-lifetime: after a backend restart the agent simply re-reads.
Keys are RESOLVED paths; staleness is detected via mtime_ns.  Consumed by the
``edit_text_file``/``write_text_file`` guards (spec Fase 2 §4.4).
"""

from __future__ import annotations

import enum
from collections import OrderedDict
from pathlib import Path


class ReadState(enum.Enum):
    """Outcome of a read-tracking lookup."""

    UNREAD = "unread"
    STALE = "stale"
    FRESH = "fresh"


class ReadTracker:
    """LRU map ``conversation_id -> {resolved path: mtime_ns at read}``."""

    def __init__(self, max_entries: int = 256) -> None:
        self._max_entries = max_entries
        self._by_conversation: dict[str, OrderedDict[Path, int]] = {}

    def record(self, conversation_id: str, path: Path) -> None:
        """Register a successful read of ``path`` for the conversation."""
        entries = self._by_conversation.setdefault(conversation_id, OrderedDict())
        resolved = path.resolve()
        entries.pop(resolved, None)
        entries[resolved] = resolved.stat().st_mtime_ns
        while len(entries) > self._max_entries:
            entries.popitem(last=False)

    def verify(self, conversation_id: str, path: Path) -> ReadState:
        """Check whether ``path`` was read and is still unmodified."""
        entries = self._by_conversation.get(conversation_id)
        resolved = path.resolve()
        if entries is None or resolved not in entries:
            return ReadState.UNREAD
        try:
            current = resolved.stat().st_mtime_ns
        except OSError:
            return ReadState.STALE
        return ReadState.FRESH if current == entries[resolved] else ReadState.STALE
