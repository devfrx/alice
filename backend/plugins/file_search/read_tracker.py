"""Per-conversation read-before-write tracking (Claude Code model).

In-memory, process-lifetime: after a backend restart the agent simply re-reads.
Keys are RESOLVED paths; staleness is detected via mtime_ns.  Consumed by the
``edit_text_file``/``write_text_file`` guards (spec Fase 2 §4.4).

Note: on filesystems with coarse mtime granularity (FAT/exFAT ~2s, vs ns on
NTFS) an extremely fast rewrite may go undetected (false FRESH); acceptable —
the guard protects against agent forgetfulness, not against an adversary.
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
    """Two-level LRU map ``conversation_id -> {resolved path: mtime_ns at read}``.

    Both levels are capped: per-conversation entries (``max_entries``) and the
    number of tracked conversations (``max_conversations``, least-recently-USED
    conversation evicted first — both ``record`` and ``verify`` count as use).
    """

    def __init__(self, max_entries: int = 256, max_conversations: int = 64) -> None:
        self._max_entries = max_entries
        self._max_conversations = max_conversations
        self._by_conversation: OrderedDict[str, OrderedDict[Path, int]] = OrderedDict()

    def record(self, conversation_id: str, path: Path) -> None:
        """Register a successful read of ``path`` for the conversation."""
        entries = self._by_conversation.setdefault(conversation_id, OrderedDict())
        self._by_conversation.move_to_end(conversation_id)
        while len(self._by_conversation) > self._max_conversations:
            self._by_conversation.popitem(last=False)
        resolved = path.resolve()
        entries.pop(resolved, None)
        entries[resolved] = resolved.stat().st_mtime_ns
        while len(entries) > self._max_entries:
            entries.popitem(last=False)

    def verify(self, conversation_id: str, path: Path) -> ReadState:
        """Check whether ``path`` was read and is still unmodified."""
        entries = self._by_conversation.get(conversation_id)
        if entries is not None:
            self._by_conversation.move_to_end(conversation_id)
        resolved = path.resolve()
        if entries is None or resolved not in entries:
            return ReadState.UNREAD
        try:
            current = resolved.stat().st_mtime_ns
        except OSError:
            return ReadState.STALE
        return ReadState.FRESH if current == entries[resolved] else ReadState.STALE
