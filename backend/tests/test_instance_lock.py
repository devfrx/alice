"""Tests for the process single-instance guard (:mod:`core.instance_lock`)."""

from __future__ import annotations

from pathlib import Path

import portalocker
import pytest

from backend.core.instance_lock import InstanceAlreadyRunningError, InstanceLock


async def test_acquire_creates_lock_file(tmp_path: Path) -> None:
    """Acquiring creates the lock file and holds an open handle."""
    lock = InstanceLock(tmp_path / "data" / ".instance.lock")
    await lock.acquire()
    try:
        assert (tmp_path / "data" / ".instance.lock").exists()
    finally:
        await lock.release()


async def test_release_is_idempotent(tmp_path: Path) -> None:
    """Releasing an un-acquired (or already-released) lock never raises."""
    lock = InstanceLock(tmp_path / ".instance.lock")
    await lock.release()  # never acquired
    await lock.acquire()
    await lock.release()
    await lock.release()  # double release


async def test_second_instance_refuses_when_lock_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the lock stays held, acquisition fails fast with a clear error.

    ``portalocker.lock`` is patched to always signal contention so the test is
    deterministic across platforms (OS lock semantics differ within a single
    process on POSIX vs. Windows).
    """
    def _always_locked(*_args: object, **_kwargs: object) -> None:
        raise portalocker.exceptions.LockException("held")

    monkeypatch.setattr(portalocker, "lock", _always_locked)

    lock = InstanceLock(tmp_path / ".instance.lock", retries=3, delay=0.0)
    with pytest.raises(InstanceAlreadyRunningError, match="already running"):
        await lock.acquire()


async def test_retries_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock freed mid-retry (reload handoff) is acquired on a later attempt."""
    calls = {"n": 0}
    real_lock = portalocker.lock

    def _locked_then_free(*args: object, **kwargs: object) -> None:
        calls["n"] += 1
        if calls["n"] < 3:
            raise portalocker.exceptions.LockException("held")
        real_lock(*args, **kwargs)

    monkeypatch.setattr(portalocker, "lock", _locked_then_free)

    lock = InstanceLock(tmp_path / ".instance.lock", retries=5, delay=0.0)
    await lock.acquire()
    try:
        assert calls["n"] == 3
    finally:
        await lock.release()
