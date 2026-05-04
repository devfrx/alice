"""AL\\CE — Single MCP server session manager."""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import traceback
from typing import Any

from loguru import logger

from backend.core.config import McpServerConfig
from backend.core.plugin_models import ConnectionStatus, ToolDefinition


# ---------------------------------------------------------------------------
# Command resolution
# ---------------------------------------------------------------------------
#
# Hardcoding interpreter paths like ``backend/.venv/Scripts/python.exe`` in
# ``mcp.servers[*].command`` breaks for the packaged installer (no venv) and
# for users running from a different cwd.  We support a small set of
# placeholders that are expanded at session start so the same configuration
# works in dev and frozen modes:
#
#   ``{python}``               -> ``sys.executable`` (works anywhere a real
#                                 Python interpreter is available; in a
#                                 PyInstaller build this is ``backend.exe``).
#   ``{builtin:fetch_primp}``  -> the full command needed to launch the
#                                 bundled ``mcp_fetch_primp`` MCP server.
#
# Builtin tokens MUST appear as the only entry in ``command``; the resolver
# replaces the whole list with the runtime-appropriate one.

_BUILTIN_FETCH_PRIMP = "{builtin:fetch_primp}"


def _resolve_command(command: list[str]) -> list[str]:
    """Expand placeholder tokens in an MCP stdio command list.

    Args:
        command: Raw command from configuration.

    Returns:
        New list with every supported placeholder replaced by its concrete
        runtime value.  Tokens not recognised are left untouched so plain
        commands (``npx``, ``uvx``, absolute paths, ...) still work.
    """
    if not command:
        return list(command)

    # Builtin commands replace the entire list.
    head = command[0]
    if head == _BUILTIN_FETCH_PRIMP:
        if getattr(sys, "frozen", False):
            # In the packaged backend.exe, dispatch to the bundled MCP
            # server via the dedicated CLI flag wired in backend/__main__.py.
            return [sys.executable, "--mcp-fetch-primp"]
        # In dev mode invoke the same flag through ``python -m backend``.
        return [sys.executable, "-m", "backend", "--mcp-fetch-primp"]

    # Per-token substitution for everything else.
    resolved: list[str] = []
    for token in command:
        if token == "{python}":
            resolved.append(sys.executable)
        else:
            resolved.append(token)
    return resolved


class McpSession:
    """Manages the lifecycle of a single MCP server connection.

    Uses the official ``mcp`` SDK for transport abstraction (stdio/SSE).

    The entire session lifecycle — connect, serve, disconnect — runs inside
    a single **background asyncio.Task** (``_session_task``).  This ensures
    that the anyio ``CancelScope`` objects created by ``stdio_client``'s
    internal ``TaskGroup`` are always entered and exited within the same
    task, avoiding the ``RuntimeError: Attempted to exit cancel scope in a
    different task`` that arises when the exit stack is closed from a
    different task during uvicorn lifespan teardown.

    ``start()`` spawns the task and waits until it signals that the handshake
    is complete (or that it failed).  ``stop()`` signals the task to exit and
    awaits its completion.
    """

    def __init__(self, config: McpServerConfig) -> None:
        self._config = config
        self._status: ConnectionStatus = ConnectionStatus.DISCONNECTED
        self._cached_tools: list[ToolDefinition] = []
        self._session: Any = None  # mcp.ClientSession, set by _session_task
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._ready_event: asyncio.Event | None = None
        self._init_error: BaseException | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn the background session task and wait until it is ready.

        Raises:
            RuntimeError: If the connection or MCP handshake fails, or
                if the session is already started.
        """
        if self._task is not None and not self._task.done():
            raise RuntimeError(
                f"MCP session '{self._config.name}' is already running. "
                "Call stop() before starting again."
            )
        self._stop_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._init_error = None

        self._task = asyncio.create_task(
            self._session_task(),
            name=f"mcp-{self._config.name}",
        )

        # Wait until the background task signals readiness (or dies early).
        wait_ready: asyncio.Task[None] = asyncio.ensure_future(
            self._ready_event.wait()
        )
        done, pending = await asyncio.wait(
            {self._task, wait_ready},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # If wait_ready finished first (normal case), self._task is in pending.
        # We must NOT cancel it — it is the live session task that must keep running.
        # Only cancel wait_ready if the background task crashed first.
        for fut in pending:
            if fut is self._task:
                # Keep the session task alive.
                continue
            fut.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await fut

        # Re-raise any initialisation error surfaced by the background task.
        if self._init_error is not None:
            raise self._init_error

        # If the task ended without setting the ready event, it crashed.
        if self._task in done and not self._ready_event.is_set():
            exc = self._task.exception()
            raise exc or RuntimeError(
                f"MCP session '{self._config.name}' task died unexpectedly"
            )

    async def stop(self) -> None:
        """Signal the background task to disconnect and wait for it."""
        if self._stop_event is not None:
            self._stop_event.set()

        if self._task is not None:
            if not self._task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(self._task), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        "MCP session '{}' did not stop in time, cancelling",
                        self._config.name,
                    )
                    self._task.cancel()
                    with contextlib.suppress(BaseException):
                        await self._task
                except Exception as exc:
                    logger.warning(
                        "Error waiting for MCP session '{}' task: {}",
                        self._config.name,
                        exc,
                    )
            else:
                # Retrieve exception from completed task to prevent
                # asyncio "Task exception was never retrieved" warning.
                if not self._task.cancelled():
                    with contextlib.suppress(BaseException):
                        self._task.result()

        self._session = None
        self._status = ConnectionStatus.DISCONNECTED
        self._cached_tools = []
        self._task = None

    def get_tools(self) -> list[ToolDefinition]:
        """Return cached tool definitions (populated after ``start()``)."""
        return list(self._cached_tools)

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute a tools/call request and return the string result.

        Args:
            tool_name: Original tool name (without ``mcp_`` prefix).
            args: Tool arguments dict.

        Returns:
            String content of the tool result.

        Raises:
            RuntimeError: If the session is not connected.
        """
        if self._session is None or self._status != ConnectionStatus.CONNECTED:
            raise RuntimeError(
                f"MCP server '{self._config.name}' is not connected"
            )
        result = await self._session.call_tool(tool_name, args)
        return "\n".join(
            block.text
            for block in result.content
            if hasattr(block, "text")
        )

    @property
    def status(self) -> ConnectionStatus:
        """Current connection status."""
        return self._status

    @property
    def server_name(self) -> str:
        """Server name from configuration."""
        return self._config.name

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log_exception(self, exc: BaseException, depth: int = 0) -> None:
        """Recursively log all leaf exceptions inside an ExceptionGroup.

        Anyio's TaskGroup wraps task errors in ``ExceptionGroup``; this
        unwraps every level and logs each leaf error with its full
        traceback so the root cause is always visible in the logs.
        """
        indent = "  " * depth
        if hasattr(exc, "exceptions") and exc.exceptions:  # ExceptionGroup
            logger.warning(
                "{}MCP '{}' TaskGroup error ({}): {}",
                indent,
                self._config.name,
                type(exc).__name__,
                exc,
            )
            for sub in exc.exceptions:
                self._log_exception(sub, depth + 1)
        else:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            logger.warning(
                "{}MCP '{}' exception — {}: {}\n{}",
                indent,
                self._config.name,
                type(exc).__name__,
                exc,
                tb,
            )

    # ------------------------------------------------------------------
    # Background task
    # ------------------------------------------------------------------

    async def _session_task(self) -> None:
        """Run the complete MCP session lifecycle in a single task.

        This is the critical design point: by keeping the entire
        ``async with AsyncExitStack()`` block inside one task, anyio's
        ``CancelScope`` objects (created by ``stdio_client``'s internal
        ``TaskGroup``) are always exited from the same task they were
        entered in.  Closing from a *different* task is what caused the
        ``RuntimeError: Attempted to exit cancel scope in a different task``
        during uvicorn lifespan teardown.
        """
        assert self._ready_event is not None
        assert self._stop_event is not None

        import mcp
        import mcp.client.stdio
        import mcp.client.sse

        try:
            async with contextlib.AsyncExitStack() as stack:
                if self._config.transport == "stdio":
                    if not self._config.command:
                        raise RuntimeError(
                            f"MCP server '{self._config.name}': "
                            "stdio transport requires 'command'"
                        )
                    import shutil
                    resolved_command = _resolve_command(list(self._config.command))
                    exe = resolved_command[0]
                    # Accept both PATH-resolvable commands (e.g. "uvx", "npx")
                    # and direct file paths (absolute or relative with a separator).
                    has_separator = (os.sep in exe) or ("/" in exe)
                    if has_separator:
                        if not os.path.isfile(exe):
                            raise RuntimeError(
                                f"MCP server '{self._config.name}': "
                                f"executable path '{exe}' does not exist"
                            )
                    elif not shutil.which(exe):
                        raise RuntimeError(
                            f"MCP server '{self._config.name}': "
                            f"executable '{exe}' not found in PATH"
                        )
                    server_params = mcp.StdioServerParameters(
                        command=resolved_command[0],
                        args=resolved_command[1:],
                        env={**os.environ, **self._config.env},
                    )
                    read, write = await stack.enter_async_context(
                        mcp.client.stdio.stdio_client(server_params)
                    )
                else:  # sse
                    if not self._config.url:
                        raise RuntimeError(
                            f"MCP server '{self._config.name}': "
                            "sse transport requires 'url'"
                        )
                    read, write = await stack.enter_async_context(
                        mcp.client.sse.sse_client(self._config.url)
                    )

                session = await stack.enter_async_context(
                    mcp.ClientSession(read, write)
                )
                await session.initialize()

                tools_response = await session.list_tools()
                self._cached_tools = [
                    ToolDefinition(
                        name=tool.name,
                        # MCP servers can have very long descriptions; truncate to
                        # the 1024-char limit enforced by ToolDefinition.validate().
                        description=(tool.description or "")[:1024],
                        parameters=(
                            tool.inputSchema
                            if tool.inputSchema
                            else {"type": "object", "properties": {}}
                        ),
                    )
                    for tool in tools_response.tools
                ]
                self._session = session
                self._status = ConnectionStatus.CONNECTED
                logger.info(
                    "MCP session '{}' connected — {} tools available",
                    self._config.name,
                    len(self._cached_tools),
                )
                # Signal start() that we are ready.
                self._ready_event.set()

                # Block here until stop() signals us to disconnect.
                # All context managers above are exited inside this task.
                await self._stop_event.wait()

        except asyncio.CancelledError:
            # Normal shutdown: the task was cancelled cleanly (stop() or
            # server/app shutdown).  Do not treat this as a connection error.
            self._status = ConnectionStatus.DISCONNECTED
            raise  # re-raise so asyncio marks the task as cancelled

        except Exception as exc:
            self._init_error = exc
            self._status = ConnectionStatus.ERROR
            # Unblock start() so it can raise the error.
            if self._ready_event is not None:
                self._ready_event.set()
            # Recursively unwrap ExceptionGroup (anyio TaskGroup errors) and
            # log every leaf exception with its full traceback.
            self._log_exception(exc)
