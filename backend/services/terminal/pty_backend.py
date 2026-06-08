"""AL\\CE — Pseudo-terminal backends (Fase 7 E1).

A thin abstraction over a real interactive PTY so the session manager never
depends on a concrete library.  Three implementations sit behind one
:class:`PtyProcess` protocol:

* :class:`WinptyPtyProcess` — the production Windows backend over **pywinpty**
  (ConPTY).  pywinpty's ``read`` is a *blocking* call, so the manager always
  drives it from a dedicated reader thread and bridges chunks back onto the
  asyncio loop with ``loop.call_soon_threadsafe`` (the ProactorEventLoop has no
  non-blocking PTY read).
* :class:`PosixPtyProcess` — a working ``os.openpty`` backend for non-Windows
  development / CI, so the feature is exercisable off Windows too.
* :class:`FakePtyProcess` — a fully in-memory double for unit tests: queue-backed
  blocking ``read``, recorded ``write`` / ``setwinsize``, and a ``feed`` /
  ``feed_eof`` test API.

The reduced child environment **replicates** (rather than imports) the allowlist
in :mod:`backend.plugins.terminal.executor` — the codebase intentionally keeps
security-critical primitives decoupled so no module reaches into another's
internals.  ``PATH`` is copied through on purpose so real dev tools resolve; the
confinement boundary is the scoped cwd, not a starved ``PATH``.
"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Final, Protocol, runtime_checkable

from loguru import logger

__all__ = [
    "FakePtyProcess",
    "PosixPtyProcess",
    "PtyProcess",
    "PtySpawnError",
    "WinptyPtyProcess",
    "reduced_pty_env",
    "spawn_pty",
]


class PtySpawnError(RuntimeError):
    """Raised when a PTY cannot be spawned (missing backend or OS error)."""


# Keys copied from ``os.environ`` into the child (only if present).  Replicated
# from ``backend.plugins.terminal.executor._ENV_ALLOWLIST`` on purpose (see the
# module docstring): security-critical constants are duplicated, never shared,
# so the two terminals can never drift each other's behaviour by coupling.
_ENV_ALLOWLIST: Final[tuple[str, ...]] = (
    "SystemRoot",
    "windir",
    "SystemDrive",
    "ComSpec",
    "PATH",
    "PATHEXT",
    "TEMP",
    "TMP",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "OS",
    "USERNAME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    # POSIX extras so an interactive shell behaves on dev machines.
    "HOME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TERM",
)


def reduced_pty_env() -> dict[str, str]:
    """Build the child environment from the allowlist plus ``TERM``.

    Drops every backend secret/token (only allowlisted keys survive) and
    guarantees a ``TERM`` so curses/ANSI programs render sensibly in the PTY.

    Returns:
        A new ``dict`` suitable as the child's environment.
    """
    env: dict[str, str] = {}
    for key in _ENV_ALLOWLIST:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    env.setdefault("TERM", "xterm-256color")
    return env


@runtime_checkable
class PtyProcess(Protocol):
    """Structural type for an interactive pseudo-terminal process.

    All implementations return decoded ``str`` from :meth:`read` (never bytes)
    and treat the empty string as end-of-stream, so the reader bridge is
    backend-agnostic.
    """

    @property
    def pid(self) -> int | None:
        """The child process id, or ``None`` when unavailable."""
        ...

    def isalive(self) -> bool:
        """Return whether the child is still running."""
        ...

    def read(self, size: int = 1024) -> str:
        """Block until output is available; return it, or ``""`` on EOF."""
        ...

    def write(self, data: str) -> int:
        """Write *data* to the PTY input; return the number of chars written."""
        ...

    def setwinsize(self, rows: int, cols: int) -> None:
        """Resize the PTY to *rows* × *cols*."""
        ...

    def terminate(self, force: bool = True) -> None:
        """Terminate the child (best-effort; never raises)."""
        ...


def spawn_pty(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str] | None = None,
    rows: int = 24,
    cols: int = 80,
) -> PtyProcess:
    """Spawn a real PTY using the best backend for the platform.

    Windows uses pywinpty (ConPTY); other platforms use ``os.openpty``.  The
    caller is trusted to have validated *argv* and *cwd* upstream (the manager
    does, via the terminal security primitives).

    Args:
        argv: The shell command to launch (program + args), already tokenised.
        cwd: The validated, in-scope working directory.
        env: The child environment; defaults to :func:`reduced_pty_env`.
        rows: Initial terminal height.
        cols: Initial terminal width.

    Returns:
        A live :class:`PtyProcess`.

    Raises:
        PtySpawnError: If no PTY backend is available or the spawn fails.
    """
    child_env = env if env is not None else reduced_pty_env()
    if sys.platform == "win32":
        return WinptyPtyProcess(argv, cwd=cwd, env=child_env, rows=rows, cols=cols)
    return PosixPtyProcess(argv, cwd=cwd, env=child_env, rows=rows, cols=cols)


class WinptyPtyProcess:
    """Production Windows PTY over **pywinpty** (ConPTY).

    pywinpty is imported lazily so this module loads on any platform (and on
    Windows installs without the wheel, yielding a legible :class:`PtySpawnError`
    instead of an import-time crash).
    """

    def __init__(
        self,
        argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        rows: int,
        cols: int,
    ) -> None:
        try:
            # Import via importlib so mypy (which has no pywinpty stubs and may
            # run where the wheel is absent) never tries to resolve it statically.
            import importlib

            winpty = importlib.import_module("winpty")
        except Exception as exc:  # ImportError or DLL load failure
            raise PtySpawnError(
                "pywinpty is not available; install 'pywinpty' to use the "
                "interactive terminal on Windows."
            ) from exc
        try:
            # winpty accepts a command line string; join with subprocess-style
            # quoting so paths with spaces survive.
            from subprocess import list2cmdline

            self._p = winpty.PtyProcess.spawn(
                list2cmdline(argv),
                cwd=cwd,
                env=env,
                dimensions=(rows, cols),
            )
        except Exception as exc:
            raise PtySpawnError(f"Failed to spawn PTY: {exc}") from exc

    @property
    def pid(self) -> int | None:
        pid = getattr(self._p, "pid", None)
        return int(pid) if pid is not None else None

    def isalive(self) -> bool:
        try:
            return bool(self._p.isalive())
        except Exception:
            return False

    def read(self, size: int = 1024) -> str:
        try:
            return str(self._p.read(size))
        except EOFError:
            return ""
        except Exception:
            return ""

    def write(self, data: str) -> int:
        try:
            return int(self._p.write(data))
        except EOFError:
            return 0  # PTY already closed — input is a no-op, never raise.

    def setwinsize(self, rows: int, cols: int) -> None:
        try:
            self._p.setwinsize(rows, cols)
        except Exception as exc:  # pragma: no cover — backend-specific
            logger.debug("winpty setwinsize failed: {}", exc)

    def terminate(self, force: bool = True) -> None:
        try:
            self._p.terminate(force)
        except Exception as exc:  # pragma: no cover — best-effort
            logger.debug("winpty terminate failed: {}", exc)


class PosixPtyProcess:
    """``os.openpty``-based PTY for non-Windows development / CI."""

    def __init__(
        self,
        argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        rows: int,
        cols: int,
    ) -> None:
        import subprocess

        try:
            self._master_fd, slave_fd = os.openpty()  # type: ignore[attr-defined]  # POSIX-only
        except OSError as exc:
            raise PtySpawnError(f"openpty failed: {exc}") from exc
        try:
            self._set_size(rows, cols)
            self._proc = subprocess.Popen(  # noqa: S603 — argv validated upstream
                argv,
                cwd=cwd,
                env=env,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                close_fds=True,
            )
        except Exception as exc:
            os.close(self._master_fd)
            os.close(slave_fd)
            raise PtySpawnError(f"Failed to spawn PTY: {exc}") from exc
        finally:
            # The child owns the slave end; the parent only needs the master.
            with contextlib.suppress(OSError):
                os.close(slave_fd)

    def _set_size(self, rows: int, cols: int) -> None:
        import fcntl
        import struct
        import termios

        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        tiocswinsz = termios.TIOCSWINSZ  # type: ignore[attr-defined]  # POSIX-only
        with contextlib.suppress(OSError):
            fcntl.ioctl(self._master_fd, tiocswinsz, winsize)  # type: ignore[attr-defined]  # POSIX-only

    @property
    def pid(self) -> int | None:
        return self._proc.pid

    def isalive(self) -> bool:
        return self._proc.poll() is None

    def read(self, size: int = 1024) -> str:
        try:
            data = os.read(self._master_fd, size)
        except OSError:
            return ""
        if not data:
            return ""
        return data.decode("utf-8", errors="replace")

    def write(self, data: str) -> int:
        return os.write(self._master_fd, data.encode("utf-8", errors="replace"))

    def setwinsize(self, rows: int, cols: int) -> None:
        self._set_size(rows, cols)

    def terminate(self, force: bool = True) -> None:
        import signal

        with contextlib.suppress(OSError):
            # Kill the whole process group (start_new_session gave the child its
            # own group), so a shell's children die with it.
            sig = signal.SIGKILL if force else signal.SIGTERM  # type: ignore[attr-defined]  # POSIX-only
            os.killpg(os.getpgid(self._proc.pid), sig)  # type: ignore[attr-defined]  # POSIX-only
        with contextlib.suppress(OSError):
            os.close(self._master_fd)


class FakePtyProcess:
    """In-memory PTY double for unit tests.

    Output is driven by the test via :meth:`feed` / :meth:`feed_eof`; :meth:`read`
    blocks on a queue exactly like a real PTY, so the manager's reader-thread
    bridge is exercised faithfully without spawning a process.  ``write`` and
    ``setwinsize`` are recorded for assertions.
    """

    def __init__(self, *, pid: int = 4242) -> None:
        import queue

        self._pid = pid
        self._alive = True
        self._out: queue.Queue[str | None] = queue.Queue()
        self.written: list[str] = []
        self.sizes: list[tuple[int, int]] = []
        self.terminated = False

    # -- test driver API ----------------------------------------------------

    def feed(self, data: str) -> None:
        """Queue *data* to be returned by the next :meth:`read`."""
        self._out.put(data)

    def feed_eof(self) -> None:
        """Signal end-of-stream; the next :meth:`read` returns ``""``."""
        self._out.put(None)

    # -- PtyProcess protocol ------------------------------------------------

    @property
    def pid(self) -> int | None:
        return self._pid

    def isalive(self) -> bool:
        return self._alive

    def read(self, size: int = 1024) -> str:
        item = self._out.get()  # blocks (like a real PTY) until fed
        if item is None:
            return ""
        return item

    def write(self, data: str) -> int:
        self.written.append(data)
        return len(data)

    def setwinsize(self, rows: int, cols: int) -> None:
        self.sizes.append((rows, cols))

    def terminate(self, force: bool = True) -> None:
        self.terminated = True
        self._alive = False
        # Unblock any pending read so the reader thread can exit.
        self._out.put(None)
