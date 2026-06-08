"""AL\\CE — Tests for the PTY backends (Fase 7 E1).

Covers the in-memory :class:`FakePtyProcess` double (the contract the manager
relies on) and :func:`reduced_pty_env` (the secret-dropping child environment).
Real-process spawning (winpty / openpty) is exercised manually on the target
platform — here we pin the pure, deterministic surface.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from backend.services.terminal.pty_backend import (
    FakePtyProcess,
    PtyProcess,
    reduced_pty_env,
    spawn_pty,
)


def test_fake_is_a_pty_process() -> None:
    """The fake satisfies the structural PtyProcess protocol."""
    fake = FakePtyProcess()
    assert isinstance(fake, PtyProcess)


def test_fake_read_returns_fed_data_then_eof() -> None:
    """read() yields fed chunks in order, then '' after feed_eof()."""
    fake = FakePtyProcess()
    fake.feed("one")
    fake.feed("two")
    fake.feed_eof()
    assert fake.read() == "one"
    assert fake.read() == "two"
    assert fake.read() == ""  # EOF


def test_fake_records_writes_and_sizes() -> None:
    """write()/setwinsize() are recorded; write returns the char count."""
    fake = FakePtyProcess()
    n = fake.write("echo hi\r")
    fake.setwinsize(40, 120)
    assert n == len("echo hi\r")
    assert fake.written == ["echo hi\r"]
    assert fake.sizes == [(40, 120)]


def test_fake_terminate_unblocks_read_and_marks_dead() -> None:
    """terminate() flips isalive() and unblocks a pending read with EOF."""
    fake = FakePtyProcess()
    assert fake.isalive() is True
    fake.terminate()
    assert fake.terminated is True
    assert fake.isalive() is False
    assert fake.read() == ""  # terminate queued an EOF sentinel


def test_reduced_env_drops_secrets_keeps_path_and_sets_term() -> None:
    """The child env keeps allowlisted keys, sets TERM, and drops the rest."""
    os.environ["ALICE_SECRET_TOKEN"] = "do-not-leak"
    os.environ["PATH"] = os.environ.get("PATH", "x")
    try:
        env = reduced_pty_env()
    finally:
        os.environ.pop("ALICE_SECRET_TOKEN", None)
    assert "ALICE_SECRET_TOKEN" not in env
    assert "PATH" in env
    assert env.get("TERM")  # always present so ANSI programs render


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ConPTY backend")
def test_real_winpty_interactive_roundtrip(tmp_path) -> None:
    """End-to-end: a real ConPTY shell echoes typed input and EOFs on exit.

    Guarded by pywinpty availability so non-Windows / extras-less envs skip it.
    Proves the production ``WinptyPtyProcess`` path — not just the fake — actually
    spawns, accepts input, streams output, and terminates.
    """
    pytest.importorskip("winpty")
    proc = spawn_pty(["cmd.exe"], cwd=str(tmp_path), rows=24, cols=80)
    try:
        assert proc.isalive() is True
        time.sleep(0.7)  # let the prompt initialise
        proc.write("echo ALICE_PTY_OK\r\n")
        time.sleep(0.5)
        proc.write("exit\r\n")
        buf: list[str] = []
        deadline = time.time() + 5
        while time.time() < deadline:
            chunk = proc.read(1024)
            if chunk == "":
                break  # EOF — shell exited
            buf.append(chunk)
        out = "".join(buf)
        assert "ALICE_PTY_OK" in out
    finally:
        proc.terminate(force=True)
