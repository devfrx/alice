"""AL\\CE — Interactive PTY terminal service (Fase 7 E1).

A real, interactive pseudo-terminal subsystem that is the session-level
counterpart to the bounded, one-shot ``run_terminal_command`` tool in
:mod:`backend.plugins.terminal`.  Where that plugin runs a single validated
command and returns, this service opens *persistent* shells the user can type
into live, multiple per conversation, with exactly one assignable to the agent.

Layering mirrors :mod:`backend.services.scope_service`: an in-memory,
per-conversation registry (:class:`~backend.services.terminal.manager.TerminalSessionManager`)
with synchronous reads for the engine and async mutations that emit events onto
the events WebSocket.  Confinement reuses the proven primitives in
:mod:`backend.services.terminal.security` (``validate_cwd_within_scope`` /
``ensure_sandbox``); process-tree teardown uses a Win32 Job Object
(:mod:`backend.services.terminal.job`).  The PTY itself is abstracted behind the
:class:`~backend.services.terminal.pty_backend.PtyProcess` protocol so the
manager is unit-testable against :class:`~backend.services.terminal.pty_backend.FakePtyProcess`.
"""

from __future__ import annotations

from backend.services.terminal.manager import TerminalSessionManager
from backend.services.terminal.pty_backend import (
    FakePtyProcess,
    PtyProcess,
    PtySpawnError,
    spawn_pty,
)
from backend.services.terminal.session import TerminalSession

__all__ = [
    "FakePtyProcess",
    "PtyProcess",
    "PtySpawnError",
    "TerminalSession",
    "TerminalSessionManager",
    "spawn_pty",
]
