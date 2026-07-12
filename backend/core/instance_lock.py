"""AL\\CE — process single-instance guard.

Embedded Qdrant and the SQLite databases under ``data/`` are **single-writer**:
two backend processes pointed at the same data directory silently corrupt each
other's view — one wins the Qdrant lock, the other degrades to a volatile
in-memory store, and the user's "repair vector store" CTA can never recover
because the lock is held live by the sibling process.

This guard makes that state unreachable.  The first process to start acquires
an exclusive lock on ``<data-dir>/.instance.lock`` and holds it for its whole
lifetime; a second process refuses to start with an actionable error.  A
bounded retry tolerates the brief window during ``--reload`` where the outgoing
worker has not yet released the lock (it releases only after every service —
Qdrant included — has been closed).

The mechanism mirrors :mod:`qdrant_client`'s own embedded lock (``portalocker``,
exclusive + non-blocking) so behaviour is consistent across the stack.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import IO

from loguru import logger

_log = logger.bind(component="InstanceLock")


class InstanceAlreadyRunningError(RuntimeError):
    """Raised when another backend instance already owns the data directory."""


class InstanceLock:
    """Exclusive, process-lifetime lock over a single data directory.

    Args:
        lock_path: Path of the lock file (created if missing).  Its parent is
            the guarded data directory.
        retries: How many times to re-attempt acquisition before giving up.
        delay: Seconds slept between attempts.
    """

    def __init__(
        self,
        lock_path: Path,
        *,
        retries: int = 20,
        delay: float = 0.5,
    ) -> None:
        self._lock_path = lock_path
        self._retries = retries
        self._delay = delay
        self._handle: IO[str] | None = None

    async def acquire(self) -> None:
        """Acquire the exclusive lock, retrying to ride out a reload handoff.

        Raises:
            InstanceAlreadyRunningError: Another live process holds the lock
                after all retries are exhausted.
        """
        # `portalocker` is imported lazily: it probes for writable directories
        # on import and can crash on read-only systems — matching qdrant-client.
        import portalocker
        from portalocker.exceptions import LockException

        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        # The default Windows backend (msvcrt) locks a byte range measured from
        # the file position, so the lock file must be non-empty and opened at
        # offset 0 — mirror qdrant-client's own embedded lock (marker text +
        # "r+") so exclusion is reliable across processes.
        if not self._lock_path.exists() or self._lock_path.stat().st_size == 0:
            self._lock_path.write_text("alice instance lock")
        # Held open for the whole process lifetime (that IS the lock), so a
        # context manager would be wrong here.
        handle = open(self._lock_path, "r+")  # noqa: SIM115
        for attempt in range(1, self._retries + 1):
            try:
                portalocker.lock(
                    handle,
                    portalocker.LockFlags.EXCLUSIVE | portalocker.LockFlags.NON_BLOCKING,
                )
                self._handle = handle
                _log.info("Instance lock acquired ({})", self._lock_path)
                return
            except LockException:
                if attempt < self._retries:
                    _log.debug(
                        "Instance lock held by another process — retry {}/{} in {:.1f}s …",
                        attempt, self._retries, self._delay,
                    )
                    await asyncio.sleep(self._delay)

        handle.close()
        raise InstanceAlreadyRunningError(
            f"Another AL\\CE backend instance is already running against "
            f"'{self._lock_path.parent}'. Stop it before starting a new one — "
            f"embedded Qdrant and the SQLite databases are single-writer. "
            f"To run more than one backend, give each its own data directory "
            f"or switch Qdrant to server mode."
        )

    async def release(self) -> None:
        """Release the lock and close the handle.  Safe if never acquired."""
        if self._handle is None:
            return
        import portalocker

        with contextlib.suppress(Exception):  # releasing must never raise
            portalocker.unlock(self._handle)
        try:
            self._handle.close()
        finally:
            self._handle = None
        _log.info("Instance lock released ({})", self._lock_path)
