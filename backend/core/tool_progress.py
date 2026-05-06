"""AL\\CE — Lightweight tool-progress emitter.

Allows long-running tools (e.g. ``cad_generate_from_image``) to push
incremental progress updates to the active WebSocket without changing
the synchronous ``ToolResult`` contract.

Mechanism
---------
The currently-active emitter is stored in a :class:`contextvars.ContextVar`
that is set by :func:`backend.api.routes._tool_loop._exec_one` for the
duration of every tool invocation.  Tools that want to publish progress
simply call :func:`emit_tool_progress` — when there is no active emitter
(e.g. unit tests, REST tool calls) the call is a silent no-op.

Frame shape on the wire (``WsToolProgressMessage``):

```jsonc
{
    "type": "tool_progress",
    "tool_name": "cad_generate_from_image",
    "execution_id": "<uuid>",
    "phase": "sampling",       // implementation-specific tag
    "label": "Shape latent",   // optional human-readable stage name
    "step": 7,                 // current step (any monotonic counter)
    "total": 36,               // total steps (>= step)
    "percent": 19,             // 0-100 integer for convenience
    "elapsed_s": 12.3          // optional wall-clock since job start
}
```

Plugins should treat every field except ``type``, ``tool_name`` and
``execution_id`` as best-effort — the frontend tolerates missing keys.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from loguru import logger

#: Async callback signature: receives the partial progress payload
#: (without the ``type`` / ``tool_name`` / ``execution_id`` fields,
#: which are filled in by the emitter).
ProgressEmitter = Callable[[dict[str, Any]], Awaitable[None]]

#: Currently-active progress emitter, scoped to the running tool task.
current_progress_emitter: ContextVar[ProgressEmitter | None] = ContextVar(
    "current_progress_emitter", default=None,
)


async def emit_tool_progress(payload: dict[str, Any]) -> None:
    """Forward a progress update to the active WebSocket, if any.

    Silent no-op when no emitter is set (e.g. tool invoked outside the
    WebSocket tool-loop, such as during unit tests or REST endpoints).

    Args:
        payload: Implementation-specific keys describing the current
            progress (``phase``, ``step``, ``total``, ``percent``, ...).
            See the module docstring for the canonical shape.
    """
    emitter = current_progress_emitter.get()
    if emitter is None:
        return
    try:
        await emitter(payload)
    except Exception as exc:  # pragma: no cover — defensive
        # Never let a broken WebSocket break the actual tool.
        logger.debug("tool_progress emitter failed: {}", exc)
