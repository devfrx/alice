"""AL\\CE — Lightweight tool-progress emitter.

Allows long-running tools (e.g. ``cad_generate_from_image``) to push
incremental progress updates to the active WebSocket without changing
the synchronous ``ToolResult`` contract.

Mechanism
---------
The currently-active emitter is stored in a :class:`contextvars.ContextVar`.
Under the v2 AgentEngine (``backend.services.agent.engine``) it is set by
``ToolRegistryAdapter.execute`` (``backend.services.agent.adapters.execution``)
for the duration of every tool invocation: the engine passes an ``on_progress``
callback to the ``ExecutionPort``, the adapter publishes it in this ContextVar
(token-based, reset always — even on timeout), and the callback emits a
``ToolProgressEvent`` from the engine, which is forwarded onto the wire. Plugins
call :func:`emit_tool_progress` directly and unconditionally (e.g.
``cad_generate_from_image``); when no emitter is set (tool invoked outside the
engine's execution path, such as REST endpoints or unit tests) it is a safe
no-op for them.

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

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

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
