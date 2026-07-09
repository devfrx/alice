"""AL\\CE — Terminal plugin subprocess executor (Fase 6d).

The execution layer for the scoped terminal.  It launches an **already
validated** ``argv`` in an **already validated** working directory and captures
the result *safely and boundedly*.  It is the deliberate counterpart to
:mod:`backend.services.terminal.security`: that module decides *whether* a
command may run; this one decides *how* it runs so that it can never exceed its
time, memory, or process budget.  This module performs **no** input validation
and never imports :mod:`.security` — the trust boundary (tokenised argv, in-scope
resolved cwd, mandatory user confirmation) is the caller's contract.

Security / robustness properties (every one is load-bearing):

* **No shell, ever.**  Execution is :func:`asyncio.create_subprocess_exec`
  (``shell=False`` semantics).  ``create_subprocess_shell`` / ``shell=True`` are
  never used, so shell metacharacters in argv are inert literal tokens — the
  absence of a shell *is* the injection defense.

* **Subprocess-capable event loop required.**  ``create_subprocess_exec`` needs
  a loop that implements child-process support — on Windows that is the
  **ProactorEventLoop**, which is the Python 3.13 default and is what both the
  application and the test runner use.  A ``SelectorEventLoop`` raises
  ``NotImplementedError``; we catch it and re-raise a legible
  :class:`RuntimeError` so the misconfiguration is obvious rather than opaque.

* **Pinned cwd.**  ``cwd`` is passed through verbatim (``cwd=str(cwd)``); the
  child starts in the exact resolved, in-scope directory the caller validated.

* **Reduced environment.**  The child env is built from a hard-coded allowlist
  (:data:`_ENV_ALLOWLIST`) copied out of :data:`os.environ`, so backend process
  secrets / tokens (e.g. ``ALICE_*``, API keys) never leak into the child.
  ``PATH`` is intentionally copied through so real developer tools (git, python,
  node) stay resolvable: the security boundary is the scoped cwd plus the
  mandatory confirmation, **not** ``PATH`` starvation.

* **``allow_network`` is advisory only.**  Windows has no reliable per-process
  network block without job objects / AppContainer, so this flag is reserved /
  documented and currently adds **no** hard network isolation.  We do not fake it
  with bogus proxy variables.

* **Bounded memory.**  Each stream is read through :func:`_read_capped`, which
  never retains more than ``max_output_bytes``; a runaway producer is capped and
  the process is killed rather than drained.

* **Bounded time.**  The whole read+wait is bounded by ``timeout_s``; on expiry
  the child is killed and whatever was captured is returned (a timeout is a
  normal terminal outcome, not an error to raise).

* **Guaranteed reap + cancel safety.**  A ``finally`` always kills a surviving
  child and awaits it (no zombies), including on ``asyncio.CancelledError`` when
  the turn engine cancels — that cancellation is re-raised, never swallowed.

* **Reap cannot hang on undrained output (Windows).**  On the ProactorEventLoop
  ``proc.wait()`` blocks indefinitely while a child pipe still holds *undrained*
  bytes — precisely the state left behind when we stop reading at the output cap
  or kill a runaway producer mid-write.  After any kill the pipe transports are
  therefore force-closed (:func:`_force_close_pipes`), which cancels the pending
  reads and discards the unread bytes so the reap returns promptly.

Documented limitation: only the **direct** child is killed.  A child that itself
spawns grandchildren can leave those grandchildren running after a
timeout/cancel/cap kill — a job-object tree-kill would be required to close that
gap and is out of scope for this module.  (Force-closing our pipe ends means even
a grandchild holding a pipe open cannot wedge the reap, but it does keep running.)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from loguru import logger

__all__ = ["TerminalResult", "run_command"]

# Keys copied from ``os.environ`` into the child (only if present).  Everything
# else — including every backend secret / token — is dropped.  ``PATH`` /
# ``PATHEXT`` are included on purpose so real dev tools remain resolvable; the
# confinement boundary is the scoped cwd + mandatory confirmation, not the PATH.
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
)

# Per-read request size.  A single ``StreamReader.read`` is asked for at most
# this many bytes (and never more than the remaining cap), so the transient
# memory of an in-flight read is bounded by this constant on top of the cap.
_READ_CHUNK_BYTES: Final[int] = 65536


@dataclass(frozen=True, slots=True)
class TerminalResult:
    """The bounded outcome of a single :func:`run_command` invocation.

    Attributes:
        returncode: The process exit code on a clean exit, or ``None`` when the
            child was **killed** by us (timeout, output cap, or cancellation)
            before it could exit on its own.
        stdout: Captured standard output, decoded UTF-8 with ``errors="replace"``
            and never longer than ``max_output_bytes`` of source bytes.
        stderr: Captured standard error, same decoding/cap as ``stdout``.
        truncated: ``True`` iff *either* stream hit the byte cap (and the process
            was consequently killed).
        timed_out: ``True`` iff the child was killed for exceeding ``timeout_s``.
        duration_ms: Wall-clock spawn→finish duration in whole milliseconds.
    """

    returncode: int | None
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool
    duration_ms: int


def _reduced_env() -> dict[str, str]:
    """Build the child environment from the allowlist.

    Copies only the keys in :data:`_ENV_ALLOWLIST` that are actually present in
    the parent :data:`os.environ`, dropping everything else so backend secrets
    never reach the child.

    Returns:
        A new ``dict`` suitable for ``create_subprocess_exec(env=...)``.
    """
    env: dict[str, str] = {}
    for key in _ENV_ALLOWLIST:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    return env


async def _read_capped(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
    """Read *stream* accumulating at most *limit* bytes, then stop.

    Bounded-memory capture: the returned buffer never exceeds *limit* bytes.
    Truncation is detected precisely — once the cap is reached we *peek* exactly
    one further byte (which is discarded, never buffered) to distinguish output
    that was exactly *limit* bytes (not truncated) from output that had more
    waiting (truncated).  Pipe-teardown errors that can surface when the child is
    killed (``ConnectionResetError`` / ``BrokenPipeError``) are treated as a
    normal end-of-stream so a kill never turns into a raised exception here.

    Args:
        stream: The child's ``stdout`` or ``stderr`` reader.
        limit: Maximum number of bytes to retain (the per-stream cap).

    Returns:
        A ``(data, truncated)`` tuple: *data* is at most *limit* bytes, and
        *truncated* is ``True`` iff more output was available beyond the cap.
    """
    buf = bytearray()
    while True:
        remaining = limit - len(buf)
        if remaining <= 0:
            # Cap reached: peek one more byte to classify truncation, discard it.
            try:
                overflow = await stream.read(1)
            except (ConnectionResetError, BrokenPipeError):
                return bytes(buf), False
            return bytes(buf), bool(overflow)
        try:
            chunk = await stream.read(min(_READ_CHUNK_BYTES, remaining))
        except (ConnectionResetError, BrokenPipeError):
            # Child went away mid-read (e.g. we killed it): treat as EOF.
            return bytes(buf), False
        if not chunk:  # genuine EOF
            return bytes(buf), False
        buf.extend(chunk)


def _force_close_pipes(proc: asyncio.subprocess.Process) -> None:
    """Force-close the child's stdout/stderr pipe transports.

    This is the load-bearing anti-hang step on Windows.  On the ProactorEventLoop
    ``proc.wait()`` blocks **indefinitely** while a child pipe still holds
    *undrained* bytes — exactly what happens when we stop reading a stream at the
    output cap, or when we kill a runaway producer mid-write.  Closing the
    subprocess transport cancels the pending overlapped pipe reads and discards
    the unread bytes on our side, so the reap completes promptly.  Unlike draining
    the pipe to EOF, it also cannot wedge on a grandchild that inherited the pipe
    write handle (such a grandchild keeps the writer open, so EOF would never
    arrive) — it just closes *our* read end.

    Best-effort and idempotent: the transport handle is asyncio-internal, so it is
    reached defensively and any error is swallowed — tearing down must never mask
    the real result.

    Args:
        proc: The child whose pipe transports should be closed.
    """
    transport = getattr(proc, "_transport", None)
    if transport is None:
        # The transport handle is asyncio-internal; if a future CPython renames
        # it this lookup returns None and the anti-hang close silently no-ops,
        # so make the regression LOUD rather than let reaps wedge in silence.
        logger.warning(
            "terminal: subprocess transport not found (asyncio internals "
            "changed?) — reap may hang on undrained output"
        )
        return
    with contextlib.suppress(Exception):
        transport.close()


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Kill *proc* if still running, close its pipes, and await it to reap.

    Robust by construction: ``proc.kill()`` can race the child's own exit and
    raise :class:`ProcessLookupError`, which is suppressed.  The pipe transports
    are then force-closed (see :func:`_force_close_pipes`) so a ``proc.wait()``
    cannot hang on undrained output, and that wait always follows so the OS
    process-table entry is reaped.  Idempotent — safe to call more than once and
    safe to call on an already-exited child.

    Args:
        proc: The child process to terminate.
    """
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    # Discard any undrained pipe bytes so the reap below cannot hang (Windows).
    _force_close_pipes(proc)
    # Reap.  Suppress a re-delivered cancellation so the wait still completes;
    # the caller's original CancelledError (if any) keeps propagating regardless.
    with contextlib.suppress(asyncio.CancelledError):
        await proc.wait()


async def _cleanup(
    proc: asyncio.subprocess.Process,
    read_tasks: tuple[asyncio.Task[tuple[bytes, bool]], ...],
) -> None:
    """Finalise a run: stop readers, kill+reap the child, drain the read tasks.

    Invoked from ``finally`` on *every* exit path (normal return, timeout,
    exception, or cancellation), so it must never raise: it cancels any still
    pending read tasks, terminates the process, then awaits the read tasks while
    suppressing their cancellation / teardown errors.

    Args:
        proc: The child process (possibly already exited).
        read_tasks: The stdout/stderr capture tasks to wind down.
    """
    for task in read_tasks:
        if not task.done():
            task.cancel()
    await _terminate(proc)
    for task in read_tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


async def run_command(
    argv: list[str],
    cwd: Path,
    *,
    timeout_s: float,
    max_output_bytes: int,
    allow_network: bool = False,
) -> TerminalResult:
    """Run *argv* in *cwd* with no shell, bounded time, memory, and a guaranteed reap.

    The argv and cwd are trusted to have been validated upstream (see the module
    docstring); this function only launches and captures.  It never raises for a
    timeout or an output overflow — those are normal terminal outcomes encoded in
    the returned :class:`TerminalResult`.  It *does* propagate
    :class:`asyncio.CancelledError` (after killing+reaping the child) so the turn
    engine can cancel a run, and propagates spawn errors such as
    :class:`FileNotFoundError` for an unknown program (the plugin translates
    those for the user).

    Implementation note — the read+wait is supervised with :func:`asyncio.wait`
    (a manual deadline loop) rather than ``asyncio.wait_for`` so that a timeout
    does **not** cancel the capture tasks: after the kill their pipes are
    force-closed and we still collect whatever partial output was buffered, and a
    stream that hits the cap can kill the process *immediately* instead of waiting
    out the full timeout.

    Args:
        argv: The fully-tokenised command (program + args); run with no shell.
        cwd: The resolved, in-scope working directory; passed through verbatim.
        timeout_s: Wall-clock budget for the whole run; on expiry the child is
            killed and the partial result returned.
        max_output_bytes: Per-stream capture cap; exceeding it on either stream
            marks the result truncated and kills the child.
        allow_network: Advisory only — reserved for future isolation.  On Windows
            this adds **no** hard network block (see the module docstring).

    Returns:
        A fully-populated :class:`TerminalResult`.

    Raises:
        RuntimeError: If the running event loop cannot spawn subprocesses
            (a non-Proactor loop raising ``NotImplementedError``).
        FileNotFoundError: If *argv[0]* names a program that does not exist.
        asyncio.CancelledError: If the surrounding task is cancelled (re-raised
            after the child is killed and reaped).
    """
    if allow_network:
        # Surface the advisory nature explicitly; we apply no real isolation.
        logger.debug("terminal: allow_network=True is advisory only (no network block applied)")

    start = time.monotonic()
    logger.debug(
        "terminal exec: argv={!r} cwd={} timeout_s={} cap={}B",
        argv,
        cwd,
        timeout_s,
        max_output_bytes,
    )

    env = _reduced_env()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except NotImplementedError as exc:
        # A SelectorEventLoop (no child-process support) — make the failure legible.
        raise RuntimeError("terminal requires a subprocess-capable event loop") from exc

    # PIPE was requested for both, so the readers are guaranteed present; assert
    # for the type checker rather than defensively branch on an impossible None.
    assert proc.stdout is not None  # invariant: stdout=PIPE
    assert proc.stderr is not None  # invariant: stderr=PIPE

    out_task: asyncio.Task[tuple[bytes, bool]] = asyncio.create_task(
        _read_capped(proc.stdout, max_output_bytes)
    )
    err_task: asyncio.Task[tuple[bytes, bool]] = asyncio.create_task(
        _read_capped(proc.stderr, max_output_bytes)
    )

    timed_out = False
    truncated = False
    killed = False

    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        pending: set[asyncio.Task[tuple[bytes, bool]]] = {out_task, err_task}

        # Supervise both reads until they finish, one truncates, or time runs out.
        while pending:
            remaining = deadline - loop.time()
            if remaining <= 0:
                timed_out = True
                break
            done, pending = await asyncio.wait(
                pending,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:  # asyncio.wait hit the timeout without completing a task
                timed_out = True
                break
            for task in done:
                _, was_truncated = task.result()
                if was_truncated:
                    truncated = True
                    if not killed:
                        killed = True
                        # Kill now so the *other* stream EOFs instead of draining
                        # a runaway producer for the rest of the timeout budget.
                        await _terminate(proc)

        if timed_out and not killed:
            killed = True
            await _terminate(proc)

        # The read tasks were never cancelled by asyncio.wait, so their buffers
        # are intact; after any kill _terminate force-closed the pipes, so these
        # awaits return promptly with whatever partial output was captured.
        out_bytes, out_trunc = await out_task
        err_bytes, err_trunc = await err_task
        truncated = truncated or out_trunc or err_trunc

        exit_code = await proc.wait()
        returncode = None if killed else exit_code

        duration_ms = round((time.monotonic() - start) * 1000)
        if timed_out:
            logger.warning(
                "terminal exec timed out after {}s; child killed (argv={!r})", timeout_s, argv
            )
        elif truncated:
            logger.warning(
                "terminal exec output exceeded cap ({}B/stream); child killed (argv={!r})",
                max_output_bytes,
                argv,
            )

        return TerminalResult(
            returncode=returncode,
            stdout=out_bytes.decode("utf-8", errors="replace"),
            stderr=err_bytes.decode("utf-8", errors="replace"),
            truncated=truncated,
            timed_out=timed_out,
            duration_ms=duration_ms,
        )
    finally:
        # Guaranteed reap + cancel safety: on ANY exit (normal, timeout,
        # exception, or asyncio.CancelledError) stop the readers and kill+reap a
        # surviving child.  A CancelledError raised in the body propagates out of
        # this finally untouched — the engine owns turn cancellation.
        await _cleanup(proc, (out_task, err_task))
