"""AL\\CE — Turn execution package.

Provides the ``TurnExecutor`` abstraction that decouples LLM turn
orchestration from the WebSocket protocol layer in ``api/routes/chat.py``.

Public surface:
    * :class:`TurnInput`, :class:`TurnResult` — DTOs (immutable).
    * :class:`WSEventSink`, :class:`WebSocketEventSink`,
      :class:`RecordingEventSink` — event sink abstractions.
    * :class:`DirectTurnExecutor` — default executor wrapping the legacy
      stream + tool loop pipeline 1:1.
    * :func:`create_turn_executor` — factory used by ``ws_chat``.
"""

from backend.services.turn.agent_executor import AgentTurnExecutor, AnnotatingSink
from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.factory import create_turn_executor
from backend.services.turn.models import TurnInput, TurnResult
from backend.services.turn.sink import (
    RecordingEventSink,
    WebSocketEventSink,
    WSEventSink,
)

__all__ = [
    "AgentTurnExecutor",
    "AnnotatingSink",
    "DirectTurnExecutor",
    "RecordingEventSink",
    "TurnInput",
    "TurnResult",
    "WSEventSink",
    "WebSocketEventSink",
    "create_turn_executor",
]
