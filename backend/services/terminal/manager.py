"""AL\\CE — Interactive terminal session manager (Fase 7 E1).

The in-memory, per-conversation registry of live PTY sessions — the session-level
counterpart to :class:`~backend.services.scope_service.ScopeService`, and the
single owner of terminal lifecycle for the turn engine and the REST/WS layer.

Design (mirrors ``ScopeService``):

* a ``conversation_id -> {session_id -> TerminalSession}`` dict with **sync**
  reads (:meth:`get_session`, :meth:`list_sessions`, :meth:`assigned_session`)
  so the agent path never awaits to find its terminal;
* **async** mutations (:meth:`create_session`, :meth:`kill_session`,
  :meth:`rename`, :meth:`assign_to_agent`, :meth:`resize`, :meth:`write_input`)
  that each emit a best-effort event through the registered callback (wired to
  the events WebSocket in the app lifespan);
* **exactly one** ``agent_assigned`` session per conversation — assigning a new
  one clears the previous;
* working-directory confinement reuses the proven, separately-reviewed
  primitives in :mod:`backend.plugins.terminal.security`
  (``validate_cwd_within_scope`` / ``ensure_sandbox``) — the single tested copy
  rather than a third replica;
* process-tree teardown via a Win32 :class:`~backend.services.terminal.job.ProcessJob`.

The PTY backend and the job factory are injectable so the manager is unit-tested
against :class:`~backend.services.terminal.pty_backend.FakePtyProcess` with no
real process and no real job.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from loguru import logger

from backend.core.config import WorkspaceScopeConfig
from backend.plugins.terminal.security import ensure_sandbox, validate_cwd_within_scope
from backend.services.terminal.job import ProcessJob
from backend.services.terminal.pty_backend import PtyProcess, spawn_pty
from backend.services.terminal.session import TerminalSession

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Awaitable callback invoked after each terminal lifecycle event."""

# Injection points (defaults bind the production backends).
PtyFactory = Callable[..., PtyProcess]
JobFactory = Callable[[int | None], "ProcessJob | None"]

# Scope provider: same signature as ScopeService.scope_roots (sync, may be None).
ScopeProvider = Callable[[str], "list[Path] | None"]


class TerminalSessionManager:
    """Own and serve all interactive PTY sessions, keyed by conversation."""

    def __init__(
        self,
        *,
        scope_provider: ScopeProvider,
        scope_config: WorkspaceScopeConfig,
        event_callback: EventCallback | None = None,
        pty_factory: PtyFactory = spawn_pty,
        job_factory: JobFactory = ProcessJob.assign_pid,
        shell: str | None = None,
        max_sessions: int = 8,
    ) -> None:
        """Build a terminal session manager.

        Args:
            scope_provider: The conversation→scope-roots resolver (typically
                :meth:`ScopeService.scope_roots`); ``None`` means no scope set.
            scope_config: Workspace-scope policy (forbidden roots, fallback mode,
                sandbox root) — drives no-scope behaviour and cwd validation.
            event_callback: Coroutine invoked once per lifecycle event.
            pty_factory: PTY spawner (defaults to the platform backend); injected
                with :class:`FakePtyProcess` in tests.
            job_factory: Win32 job assigner (defaults to real); ``None`` result
                ⇒ fall back to a direct PTY terminate.
            shell: Override the interactive shell program; ``None`` ⇒ ComSpec on
                Windows, ``$SHELL`` on POSIX.
            max_sessions: Per-conversation concurrent-session cap.
        """
        self._scope_provider = scope_provider
        self._scope_config = scope_config
        self._event_callback = event_callback
        self._pty_factory = pty_factory
        self._job_factory = job_factory
        self._shell = shell
        self._max_sessions = max_sessions
        # conversation id (str) -> session id -> session.
        self._sessions: dict[str, dict[str, TerminalSession]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback | None) -> None:
        """Register the coroutine called after each terminal lifecycle event."""
        self._event_callback = callback

    # ------------------------------------------------------------------
    # Sync reads
    # ------------------------------------------------------------------

    def get_session(
        self, conversation_id: str, session_id: str,
    ) -> TerminalSession | None:
        """Return a session by id, or ``None`` if absent (**SYNC**)."""
        return self._sessions.get(str(conversation_id), {}).get(session_id)

    def list_sessions(self, conversation_id: str) -> list[TerminalSession]:
        """Return all sessions for a conversation, oldest first (**SYNC**)."""
        sessions = self._sessions.get(str(conversation_id), {})
        return sorted(sessions.values(), key=lambda s: s.created_at)

    def assigned_session(self, conversation_id: str) -> TerminalSession | None:
        """Return the conversation's agent-assigned session, if any (**SYNC**)."""
        for session in self._sessions.get(str(conversation_id), {}).values():
            if session.agent_assigned:
                return session
        return None

    def active_count(self, conversation_id: str) -> int:
        """Return the number of live sessions for a conversation (**SYNC**)."""
        return len(self._sessions.get(str(conversation_id), {}))

    # ------------------------------------------------------------------
    # Async mutations
    # ------------------------------------------------------------------

    async def create_session(
        self,
        conversation_id: str,
        *,
        cwd: str | None = None,
        title: str | None = None,
        rows: int = 24,
        cols: int = 80,
        assign_to_agent: bool = False,
    ) -> TerminalSession:
        """Spawn a new PTY session confined to the conversation's scope.

        The working directory is resolved exactly as the one-shot terminal
        resolves it: an explicit *cwd* must validate inside the scope; otherwise
        the first scope root is used; with no scope and ``fallback_mode ==
        "sandbox"`` an ephemeral per-conversation sandbox is used; otherwise the
        call is refused (the no-scope breaker).

        Args:
            conversation_id: The owning conversation.
            cwd: Optional explicit working directory (must be in-scope).
            title: Optional display title (auto-generated when omitted).
            rows: Initial terminal height.
            cols: Initial terminal width.
            assign_to_agent: Assign the new session to the agent immediately
                (clearing any previous assignment).

        Returns:
            The created, live :class:`TerminalSession`.

        Raises:
            ValueError: No scope set (and no sandbox fallback), an out-of-scope
                *cwd*, or the per-conversation session cap reached.
            PtySpawnError: The PTY backend failed to spawn.
        """
        conv_key = str(conversation_id)
        sessions = self._sessions.setdefault(conv_key, {})
        if len(sessions) >= self._max_sessions:
            raise ValueError(
                f"Maximum number of terminals ({self._max_sessions}) reached "
                "for this conversation."
            )

        workdir = self._resolve_workdir(conv_key, cwd)
        argv = self._shell_argv()

        pty = self._pty_factory(argv, cwd=str(workdir), rows=rows, cols=cols)
        job = self._job_factory(pty.pid)

        session_id = uuid.uuid4().hex
        session = TerminalSession(
            session_id=session_id,
            conversation_id=conv_key,
            title=title or self._default_title(sessions),
            cwd=workdir,
            pty=pty,
            job=job,
            rows=rows,
            cols=cols,
        )
        sessions[session_id] = session

        self._loop = asyncio.get_running_loop()
        session.start_reader(self._loop, self._on_output, self._on_exit)

        if assign_to_agent:
            self._set_assigned(conv_key, session_id)

        logger.debug(
            "terminal session opened: conv={} id={} cwd={}", conv_key, session_id, workdir,
        )
        await self._emit({
            "type": "terminal.session_opened",
            "conversation_id": conv_key,
            "session": session.snapshot(),
        })
        return session

    async def write_input(
        self, conversation_id: str, session_id: str, data: str,
    ) -> bool:
        """Write raw input to a session's PTY. Returns ``False`` if unknown."""
        session = self.get_session(conversation_id, session_id)
        if session is None:
            return False
        session.write(data)
        return True

    async def resize(
        self, conversation_id: str, session_id: str, rows: int, cols: int,
    ) -> bool:
        """Resize a session's PTY. Returns ``False`` if unknown."""
        session = self.get_session(conversation_id, session_id)
        if session is None:
            return False
        session.resize(rows, cols)
        return True

    async def rename(
        self, conversation_id: str, session_id: str, title: str,
    ) -> bool:
        """Rename a session and emit ``terminal.renamed``. ``False`` if unknown."""
        session = self.get_session(conversation_id, session_id)
        if session is None:
            return False
        session.title = title
        await self._emit({
            "type": "terminal.renamed",
            "conversation_id": str(conversation_id),
            "session_id": session_id,
            "title": title,
        })
        return True

    async def assign_to_agent(
        self, conversation_id: str, session_id: str,
    ) -> bool:
        """Make *session_id* the conversation's agent session (exactly one).

        Returns:
            ``True`` on success, ``False`` if the session is unknown.
        """
        conv_key = str(conversation_id)
        if session_id not in self._sessions.get(conv_key, {}):
            return False
        self._set_assigned(conv_key, session_id)
        await self._emit({
            "type": "terminal.assigned",
            "conversation_id": conv_key,
            "session_id": session_id,
        })
        return True

    async def kill_session(
        self, conversation_id: str, session_id: str,
    ) -> bool:
        """Terminate a session (process tree) and emit ``terminal.closed``.

        Removes the session from the registry *before* terminating so the reader
        thread's EOF-driven exit callback finds it already gone and does not emit
        a duplicate ``terminal.closed``.

        Returns:
            ``True`` if a session was killed, ``False`` if it was unknown.
        """
        conv_key = str(conversation_id)
        sessions = self._sessions.get(conv_key)
        if not sessions or session_id not in sessions:
            return False
        session = sessions.pop(session_id)
        if not sessions:
            self._sessions.pop(conv_key, None)
        session.kill()
        await self._emit({
            "type": "terminal.closed",
            "conversation_id": conv_key,
            "session_id": session_id,
            "exit_code": None,
        })
        return True

    async def echo_agent_output(
        self, conversation_id: str, session_id: str, text: str,
    ) -> bool:
        """Mirror agent-run output into a session's stream (display-only).

        Emits a ``terminal.output`` event so the assigned terminal tab shows what
        the agent ran — it does **not** write to the PTY (the agent's bounded
        command runs in its own subprocess, not by injecting keystrokes).

        Returns:
            ``True`` if the session exists, ``False`` otherwise.
        """
        if self.get_session(conversation_id, session_id) is None:
            return False
        await self._emit({
            "type": "terminal.output",
            "conversation_id": str(conversation_id),
            "session_id": session_id,
            "data": text,
        })
        return True

    async def ensure_agent_session(
        self, conversation_id: str,
    ) -> TerminalSession:
        """Return the agent session, creating + assigning one if none exists.

        Used by the agent path (Fase E2) so a tool command always has a terminal
        to run in.  Honours the same scope confinement as :meth:`create_session`
        (raises when no scope is set and there is no sandbox fallback).

        Raises:
            ValueError / PtySpawnError: As :meth:`create_session`.
        """
        existing = self.assigned_session(conversation_id)
        if existing is not None:
            return existing
        return await self.create_session(conversation_id, assign_to_agent=True)

    async def cleanup_conversation(self, conversation_id: str) -> None:
        """Kill and forget every session for a conversation (on conv delete)."""
        conv_key = str(conversation_id)
        sessions = self._sessions.pop(conv_key, None)
        if not sessions:
            return
        for session in list(sessions.values()):
            session.kill()
        for session_id in list(sessions.keys()):
            await self._emit({
                "type": "terminal.closed",
                "conversation_id": conv_key,
                "session_id": session_id,
                "exit_code": None,
            })

    async def shutdown(self) -> None:
        """Kill every session across all conversations (app shutdown)."""
        for sessions in self._sessions.values():
            for session in sessions.values():
                session.kill()
        self._sessions.clear()
        for task in list(self._bg_tasks):
            task.cancel()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_workdir(self, conversation_id: str, cwd: str | None) -> Path:
        """Resolve the in-scope working directory (mirrors the one-shot terminal).

        Raises:
            ValueError: No scope and no sandbox fallback, or an out-of-scope cwd.
        """
        scope_roots = self._scope_provider(conversation_id)
        forbidden = self._scope_config.forbidden_paths
        if cwd and str(cwd).strip():
            return validate_cwd_within_scope(str(cwd), scope_roots or [], forbidden)
        if scope_roots:
            return scope_roots[0]
        if self._scope_config.fallback_mode == "sandbox":
            return ensure_sandbox(conversation_id, self._scope_config.sandbox_root)
        raise ValueError(
            "No workspace folder scope is set for this conversation."
        )

    def _shell_argv(self) -> list[str]:
        """Return the argv for the interactive shell."""
        if self._shell:
            return [self._shell]
        if sys.platform == "win32":
            return [os.environ.get("COMSPEC", "cmd.exe")]
        return [os.environ.get("SHELL", "/bin/bash")]

    def _default_title(self, sessions: dict[str, TerminalSession]) -> str:
        """Generate a stable default title (``Terminal N``)."""
        return f"Terminal {len(sessions)}"

    def _set_assigned(self, conversation_id: str, session_id: str) -> None:
        """Assign exactly one session to the agent within a conversation."""
        for sid, session in self._sessions.get(conversation_id, {}).items():
            session.agent_assigned = sid == session_id

    # -- reader-thread bridge (runs on the loop via call_soon_threadsafe) --

    def _on_output(self, session: TerminalSession, chunk: str) -> None:
        """Bridge a PTY output chunk into a ``terminal.output`` event."""
        self._schedule_emit({
            "type": "terminal.output",
            "conversation_id": session.conversation_id,
            "session_id": session.id,
            "data": chunk,
        })

    def _on_exit(self, session: TerminalSession) -> None:
        """Handle a PTY reaching EOF (process exited on its own).

        No-ops when the session was already removed by :meth:`kill_session`
        (which emits its own ``terminal.closed``), so a natural exit and an
        explicit kill never double-emit.
        """
        conv_key = session.conversation_id
        sessions = self._sessions.get(conv_key)
        if not sessions or session.id not in sessions:
            return
        sessions.pop(session.id, None)
        if not sessions:
            self._sessions.pop(conv_key, None)
        self._schedule_emit({
            "type": "terminal.closed",
            "conversation_id": conv_key,
            "session_id": session.id,
            "exit_code": None,
        })

    def _schedule_emit(self, event: dict[str, Any]) -> None:
        """Schedule an async emit from a loop-thread sync callback."""
        loop = self._loop
        if loop is None:
            return
        task = loop.create_task(self._emit(event))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _emit(self, event: dict[str, Any]) -> None:
        """Invoke the event callback (best-effort, never raises)."""
        cb = self._event_callback
        if cb is None:
            return
        try:
            await cb(event)
        except Exception as exc:
            logger.warning("terminal event callback failed: {}", exc)
