"""AL\\CE — A single interactive terminal session (Fase 7 E1).

Owns one :class:`~backend.services.terminal.pty_backend.PtyProcess`, its optional
Win32 :class:`~backend.services.terminal.job.ProcessJob` (for tree-kill), and the
dedicated reader thread that bridges the PTY's *blocking* output back onto the
asyncio loop with ``loop.call_soon_threadsafe``.  The session is otherwise inert
state — the registry, scope validation, assignment and event emission live in
:class:`~backend.services.terminal.manager.TerminalSessionManager`.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from backend.services.terminal.job import ProcessJob
from backend.services.terminal.pty_backend import PtyProcess

# Per-read request size for the reader thread (chars).  A real PTY returns
# whatever is available up to this; small enough to stream promptly, large
# enough not to thrash on bulk output.
_READ_SIZE = 4096

#: Type of the manager callbacks the reader thread invokes (on the loop).
OnOutput = Callable[["TerminalSession", str], None]
OnExit = Callable[["TerminalSession"], None]


class TerminalSession:
    """One live PTY shell with a reader thread bridging output to asyncio."""

    def __init__(
        self,
        *,
        session_id: str,
        conversation_id: str,
        title: str,
        cwd: Path,
        pty: PtyProcess,
        job: ProcessJob | None,
        rows: int,
        cols: int,
    ) -> None:
        self.id = session_id
        self.conversation_id = conversation_id
        self.title = title
        self.cwd = cwd
        self.rows = rows
        self.cols = cols
        self.created_at = datetime.now(UTC)
        self.agent_assigned = False

        self._pty = pty
        self._job = job
        self._reader: threading.Thread | None = None
        self._stopped = False

    # ------------------------------------------------------------------
    # Reader
    # ------------------------------------------------------------------

    def start_reader(
        self,
        loop: asyncio.AbstractEventLoop,
        on_output: OnOutput,
        on_exit: OnExit,
    ) -> None:
        """Spawn the daemon thread that pumps PTY output onto *loop*.

        The thread loops on the blocking :meth:`PtyProcess.read`; each non-empty
        chunk is delivered via ``loop.call_soon_threadsafe(on_output, self,
        chunk)``.  On EOF (process exit) or after :meth:`kill`, it fires
        ``on_exit`` exactly once and ends.

        Args:
            loop: The asyncio loop the manager runs on.
            on_output: Called (on the loop) with ``(session, chunk)`` per read.
            on_exit: Called (on the loop) once when the PTY reaches EOF.
        """

        def _run() -> None:
            try:
                while not self._stopped:
                    chunk = self._pty.read(_READ_SIZE)
                    if not chunk:
                        break
                    if self._stopped:
                        break
                    loop.call_soon_threadsafe(on_output, self, chunk)
            except Exception as exc:  # pragma: no cover — defensive
                logger.debug("terminal reader thread error (session {}): {}", self.id, exc)
            finally:
                with contextlib.suppress(RuntimeError):
                    # RuntimeError if the loop is already closed at shutdown.
                    loop.call_soon_threadsafe(on_exit, self)

        self._reader = threading.Thread(
            target=_run, name=f"pty-reader-{self.id[:8]}", daemon=True,
        )
        self._reader.start()

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def write(self, data: str) -> None:
        """Write *data* to the PTY input (best-effort)."""
        with contextlib.suppress(Exception):
            self._pty.write(data)

    def resize(self, rows: int, cols: int) -> None:
        """Resize the PTY and remember the new dimensions."""
        self.rows = rows
        self.cols = cols
        with contextlib.suppress(Exception):
            self._pty.setwinsize(rows, cols)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def alive(self) -> bool:
        """Whether the underlying PTY process is still running."""
        if self._stopped:
            return False
        with contextlib.suppress(Exception):
            return self._pty.isalive()
        return False

    def kill(self) -> None:
        """Terminate the process tree (job first, then the PTY directly).

        Idempotent and never raises.  The Win32 job (when present) takes the
        whole tree down; the direct PTY terminate is always also issued so the
        blocking reader unblocks (EOF) and the reader thread exits even when no
        job was available (non-Windows, or job creation failed).
        """
        self._stopped = True
        if self._job is not None:
            self._job.terminate()
            self._job.close()
        with contextlib.suppress(Exception):
            self._pty.terminate(force=True)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable view for REST responses and WS events."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "title": self.title,
            "cwd": str(self.cwd),
            "rows": self.rows,
            "cols": self.cols,
            "agent_assigned": self.agent_assigned,
            "created_at": self.created_at.isoformat(),
            "pid": self._pty.pid,
            "alive": self.alive,
        }
