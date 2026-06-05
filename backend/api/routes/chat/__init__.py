"""AL\\CE — Chat routes package.

Aggregates the chat route modules onto a single ``APIRouter`` and
re-exports the public surface consumed elsewhere in the codebase:

* ``router`` — registered by :mod:`backend.api.routes`.
* ``_filter_messages_by_active_versions`` / ``_filter_history_for_llm`` —
  imported directly by the test suite.

Importing the route submodules here triggers their ``@router`` decorators
so every endpoint is registered on the shared router instance.
"""

from __future__ import annotations

# Import side-effect: register all route handlers on ``router``.
from . import (
    conversations,  # noqa: E402,F401
    io,  # noqa: E402,F401
    ws,  # noqa: E402,F401
)
from ._helpers import (
    _filter_history_for_llm,
    _filter_messages_by_active_versions,
)
from ._shared import router

__all__ = [
    "router",
    "_filter_history_for_llm",
    "_filter_messages_by_active_versions",
]
