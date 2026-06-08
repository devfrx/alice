"""AL\\CE — Tests for the terminal plugin subprocess executor (Fase 6d).

These are **real-process** tests: every case spawns ``sys.executable -c "..."``
so the runner is exercised against a genuine child with no shell involved (no
shell builtins, fully cross-platform, deterministic).  Each runs in its own
``tmp_path`` working directory.  They pin the security-critical guarantees of
:func:`backend.plugins.terminal.executor.run_command` — reduced env, pinned cwd,
bounded output, timeout-kill, cancel-reap — and the timeout / cancellation cases
assert *wall-clock* bounds far below the child's own sleep so a hung kill/reap
fails loudly instead of silently waiting.

Requires a subprocess-capable event loop (the Windows ProactorEventLoop, which is
the Python 3.13 default used by the test runner).
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from backend.plugins.terminal.executor import TerminalResult, run_command


def _py(script: str) -> list[str]:
    """Build a shell-free argv that runs *script* via the test interpreter."""
    import sys

    return [sys.executable, "-c", script]


# ---------------------------------------------------------------------------
# Happy path: exit codes, stream split, cwd, decoding
# ---------------------------------------------------------------------------


async def test_run_command_success(tmp_path: Path) -> None:
    result = await run_command(
        _py("print('hello')"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1_000_000,
    )

    assert isinstance(result, TerminalResult)
    assert result.returncode == 0
    assert "hello" in result.stdout
    assert result.truncated is False
    assert result.timed_out is False
    assert result.duration_ms >= 0


async def test_run_command_nonzero_exit(tmp_path: Path) -> None:
    result = await run_command(
        _py("import sys; sys.exit(3)"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1_000_000,
    )

    assert result.returncode == 3
    assert result.timed_out is False
    assert result.truncated is False


async def test_run_command_stdout_stderr_split(tmp_path: Path) -> None:
    result = await run_command(
        _py("import sys; sys.stdout.write('OUTTEXT'); sys.stderr.write('ERRTEXT')"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1_000_000,
    )

    assert result.returncode == 0
    assert "OUTTEXT" in result.stdout
    assert "ERRTEXT" in result.stderr
    assert "ERRTEXT" not in result.stdout
    assert "OUTTEXT" not in result.stderr


async def test_run_command_cwd_is_pinned(tmp_path: Path) -> None:
    result = await run_command(
        _py("import os; print(os.getcwd())"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1_000_000,
    )

    assert result.returncode == 0
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()


async def test_run_command_decodes_invalid_utf8_with_replacement(tmp_path: Path) -> None:
    """Invalid UTF-8 on stdout must not raise — it is decoded with replacement."""
    result = await run_command(
        _py("import sys; sys.stdout.buffer.write(b'\\xff\\xfe'); sys.stdout.flush()"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1_000_000,
    )

    assert result.returncode == 0
    assert "�" in result.stdout  # U+FFFD REPLACEMENT CHARACTER


# ---------------------------------------------------------------------------
# Reduced environment (secrets stripped, essentials passed through)
# ---------------------------------------------------------------------------


async def test_run_command_reduced_env_strips_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parent secret outside the allowlist must NOT reach the child."""
    monkeypatch.setenv("ALICE_SECRET_LEAK", "topsecret")

    result = await run_command(
        _py("import os; print(os.environ.get('ALICE_SECRET_LEAK', 'MISSING'))"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1_000_000,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "MISSING"
    assert "topsecret" not in result.stdout


async def test_run_command_reduced_env_keeps_essentials(tmp_path: Path) -> None:
    """The allowlist passes essentials through: SystemRoot (Windows) or PATH."""
    result = await run_command(
        _py("import os; print(os.environ.get('SystemRoot') or os.environ.get('PATH') or '')"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1_000_000,
    )

    assert result.returncode == 0
    assert result.stdout.strip() != ""  # an essential env var came through


async def test_run_command_reduced_env_keeps_path(tmp_path: Path) -> None:
    """PATH specifically is copied through so real dev tools stay resolvable."""
    result = await run_command(
        _py("import os; print(os.environ.get('PATH', 'MISSING'))"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1_000_000,
    )

    assert result.returncode == 0
    assert result.stdout.strip() not in ("", "MISSING")


# ---------------------------------------------------------------------------
# Bounded time: timeout kills the child fast
# ---------------------------------------------------------------------------


async def test_run_command_timeout_kills(tmp_path: Path) -> None:
    """A 30s sleeper with a 0.5s budget must be killed in well under 5s."""
    t0 = time.monotonic()
    result = await run_command(
        _py("import time; time.sleep(30)"),
        tmp_path,
        timeout_s=0.5,
        max_output_bytes=1_000_000,
    )
    elapsed = time.monotonic() - t0

    assert result.timed_out is True
    assert result.returncode is None  # killed, never exited on its own
    assert elapsed < 5.0, f"timeout did not kill promptly (took {elapsed:.2f}s)"


# ---------------------------------------------------------------------------
# Bounded memory: output cap truncates and kills
# ---------------------------------------------------------------------------


async def test_run_command_output_cap_truncates(tmp_path: Path) -> None:
    """A 1 MB producer with a 1 KB cap is truncated; we never buffer the 1 MB."""
    t0 = time.monotonic()
    result = await run_command(
        _py("print('x' * 1_000_000)"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1000,
    )
    elapsed = time.monotonic() - t0

    assert result.truncated is True
    captured = len(result.stdout.encode("utf-8"))
    assert captured <= 4000, f"captured {captured} bytes — cap not enforced"
    assert captured < 1_000_000  # never the full producer output
    assert elapsed < 5.0, f"cap kill was not prompt (took {elapsed:.2f}s)"


# ---------------------------------------------------------------------------
# Cancel safety: cancelling the task kills+reaps the child fast
# ---------------------------------------------------------------------------


async def test_run_command_cancellation_reaps(tmp_path: Path) -> None:
    """Cancelling mid-run must raise CancelledError and return promptly.

    Returning in well under the child's 30s sleep proves the ``finally`` killed
    and reaped the process instead of awaiting its natural exit.
    """
    task = asyncio.create_task(
        run_command(
            _py("import time; time.sleep(30)"),
            tmp_path,
            timeout_s=30.0,
            max_output_bytes=1_000_000,
        )
    )
    await asyncio.sleep(0.2)  # let the child actually spawn

    t0 = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    elapsed = time.monotonic() - t0

    assert elapsed < 5.0, f"cancellation did not reap promptly (took {elapsed:.2f}s)"


# ---------------------------------------------------------------------------
# Spawn errors propagate (the plugin translates them)
# ---------------------------------------------------------------------------


async def test_run_command_bad_argv_raises_filenotfound(tmp_path: Path) -> None:
    missing = tmp_path / "definitely_not_a_real_program_xyz.exe"

    with pytest.raises(FileNotFoundError):
        await run_command(
            [str(missing)],
            tmp_path,
            timeout_s=5.0,
            max_output_bytes=1000,
        )


# ---------------------------------------------------------------------------
# allow_network is advisory only — it must not change observable behaviour
# ---------------------------------------------------------------------------


async def test_run_command_allow_network_is_advisory(tmp_path: Path) -> None:
    """The advisory flag must not break a normal run (it adds no isolation)."""
    assert os.name  # sanity: os imported and usable
    result = await run_command(
        _py("print('net')"),
        tmp_path,
        timeout_s=30.0,
        max_output_bytes=1_000_000,
        allow_network=True,
    )

    assert result.returncode == 0
    assert "net" in result.stdout
