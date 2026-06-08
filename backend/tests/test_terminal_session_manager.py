"""AL\\CE — Tests for the interactive terminal session manager (Fase 7 E1).

Drives :class:`TerminalSessionManager` against the in-memory
:class:`FakePtyProcess` (no real process, no real Win32 job), pinning the
load-bearing invariants:

* scope confinement (no-scope refusal, out-of-scope cwd refusal, sandbox
  fallback);
* exactly-one agent assignment;
* lifecycle events (opened / output / closed / renamed / assigned);
* the no-double-close guarantee (explicit kill vs natural EOF);
* the per-conversation session cap and cleanup.

Output/exit events are delivered from the reader thread via
``loop.call_soon_threadsafe``; tests yield with a short ``asyncio.sleep`` to let
that bridge fire before asserting.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.core.config import WorkspaceScopeConfig
from backend.services.terminal.manager import TerminalSessionManager
from backend.services.terminal.pty_backend import FakePtyProcess, spawn_pty

CONV = "11111111-1111-1111-1111-111111111111"


class _Recorder:
    """Records emitted events for assertions."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def of(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == event_type]


class _Factory:
    """PTY factory returning recorded fakes (signature matches spawn_pty)."""

    def __init__(self) -> None:
        self.created: list[FakePtyProcess] = []

    def __call__(
        self, argv: list[str], *, cwd: str, rows: int = 24, cols: int = 80,
        env: dict[str, str] | None = None,
    ) -> FakePtyProcess:
        fake = FakePtyProcess(pid=4242 + len(self.created))
        self.created.append(fake)
        return fake


def _build(
    *,
    scope_roots: list[Path] | None,
    fallback_mode: str = "disabled",
    sandbox_root: str = "data/workspaces",
    max_sessions: int = 8,
) -> tuple[TerminalSessionManager, _Factory, _Recorder]:
    factory = _Factory()
    recorder = _Recorder()

    def scope_provider(_cid: str) -> list[Path] | None:
        return scope_roots

    config = WorkspaceScopeConfig(
        fallback_mode=fallback_mode,  # type: ignore[arg-type]
        sandbox_root=sandbox_root,
    )
    mgr = TerminalSessionManager(
        scope_provider=scope_provider,
        scope_config=config,
        event_callback=recorder,
        pty_factory=factory,
        job_factory=lambda _pid: None,  # no real Win32 job in tests
        max_sessions=max_sessions,
    )
    return mgr, factory, recorder


# ---------------------------------------------------------------------------
# Creation & scope confinement
# ---------------------------------------------------------------------------


async def test_create_session_emits_opened(tmp_path: Path) -> None:
    mgr, factory, rec = _build(scope_roots=[tmp_path])
    try:
        session = await mgr.create_session(CONV)
        assert session.cwd == tmp_path.resolve()
        assert len(factory.created) == 1
        opened = rec.of("terminal.session_opened")
        assert len(opened) == 1
        assert opened[0]["session"]["id"] == session.id
    finally:
        await mgr.shutdown()


async def test_no_scope_refuses(tmp_path: Path) -> None:
    mgr, _factory, _rec = _build(scope_roots=None, fallback_mode="disabled")
    with pytest.raises(ValueError, match="No workspace folder scope"):
        await mgr.create_session(CONV)


async def test_sandbox_fallback_allows_without_scope(tmp_path: Path) -> None:
    mgr, factory, _rec = _build(
        scope_roots=None,
        fallback_mode="sandbox",
        sandbox_root=str(tmp_path / "sb"),
    )
    try:
        session = await mgr.create_session(CONV)
        assert session.cwd.exists()
        # ensure_sandbox places the cwd directly under <sandbox_root>/<conv>.
        assert session.cwd.parent == (tmp_path / "sb").resolve()
    finally:
        await mgr.shutdown()


async def test_out_of_scope_cwd_refused(tmp_path: Path) -> None:
    scope = tmp_path / "scope"
    scope.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    mgr, _factory, _rec = _build(scope_roots=[scope])
    with pytest.raises(ValueError, match="outside the workspace scope"):
        await mgr.create_session(CONV, cwd=str(outside))


async def test_explicit_in_scope_cwd_accepted(tmp_path: Path) -> None:
    scope = tmp_path / "scope"
    sub = scope / "sub"
    sub.mkdir(parents=True)
    mgr, _factory, _rec = _build(scope_roots=[scope])
    try:
        session = await mgr.create_session(CONV, cwd=str(sub))
        assert session.cwd == sub.resolve()
    finally:
        await mgr.shutdown()


async def test_max_sessions_cap(tmp_path: Path) -> None:
    mgr, _factory, _rec = _build(scope_roots=[tmp_path], max_sessions=2)
    try:
        await mgr.create_session(CONV)
        await mgr.create_session(CONV)
        with pytest.raises(ValueError, match="Maximum number of terminals"):
            await mgr.create_session(CONV)
    finally:
        await mgr.shutdown()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def test_sync_reads(tmp_path: Path) -> None:
    mgr, _factory, _rec = _build(scope_roots=[tmp_path])
    try:
        a = await mgr.create_session(CONV)
        b = await mgr.create_session(CONV)
        assert mgr.get_session(CONV, a.id) is a
        assert {s.id for s in mgr.list_sessions(CONV)} == {a.id, b.id}
        assert mgr.active_count(CONV) == 2
        assert mgr.get_session(CONV, "missing") is None
    finally:
        await mgr.shutdown()


# ---------------------------------------------------------------------------
# Agent assignment (exactly one)
# ---------------------------------------------------------------------------


async def test_exactly_one_agent_assignment(tmp_path: Path) -> None:
    mgr, _factory, rec = _build(scope_roots=[tmp_path])
    try:
        a = await mgr.create_session(CONV, assign_to_agent=True)
        assert mgr.assigned_session(CONV) is a
        b = await mgr.create_session(CONV)
        await mgr.assign_to_agent(CONV, b.id)
        assert mgr.assigned_session(CONV) is b
        assert a.agent_assigned is False  # previous assignment cleared
        assert rec.of("terminal.assigned")[-1]["session_id"] == b.id
    finally:
        await mgr.shutdown()


async def test_assign_unknown_returns_false(tmp_path: Path) -> None:
    mgr, _factory, _rec = _build(scope_roots=[tmp_path])
    try:
        assert await mgr.assign_to_agent(CONV, "nope") is False
    finally:
        await mgr.shutdown()


async def test_ensure_agent_session_creates_then_reuses(tmp_path: Path) -> None:
    mgr, factory, _rec = _build(scope_roots=[tmp_path])
    try:
        first = await mgr.ensure_agent_session(CONV)
        assert first.agent_assigned is True
        again = await mgr.ensure_agent_session(CONV)
        assert again is first
        assert len(factory.created) == 1  # reused, not recreated
    finally:
        await mgr.shutdown()


# ---------------------------------------------------------------------------
# I/O & resize
# ---------------------------------------------------------------------------


async def test_write_input_routes_to_pty(tmp_path: Path) -> None:
    mgr, factory, _rec = _build(scope_roots=[tmp_path])
    try:
        session = await mgr.create_session(CONV)
        assert await mgr.write_input(CONV, session.id, "dir\r") is True
        assert factory.created[0].written == ["dir\r"]
        assert await mgr.write_input(CONV, "missing", "x") is False
    finally:
        await mgr.shutdown()


async def test_resize_routes_to_pty(tmp_path: Path) -> None:
    mgr, factory, _rec = _build(scope_roots=[tmp_path])
    try:
        session = await mgr.create_session(CONV)
        assert await mgr.resize(CONV, session.id, 50, 132) is True
        assert factory.created[0].sizes[-1] == (50, 132)
        assert session.rows == 50 and session.cols == 132
    finally:
        await mgr.shutdown()


# ---------------------------------------------------------------------------
# Output / exit bridging
# ---------------------------------------------------------------------------


async def test_output_is_bridged_to_event(tmp_path: Path) -> None:
    mgr, factory, rec = _build(scope_roots=[tmp_path])
    try:
        session = await mgr.create_session(CONV)
        factory.created[0].feed("Hello\r\n")
        await asyncio.sleep(0.1)
        out = rec.of("terminal.output")
        assert any(e["data"] == "Hello\r\n" and e["session_id"] == session.id for e in out)
    finally:
        await mgr.shutdown()


async def test_natural_exit_emits_closed_and_removes(tmp_path: Path) -> None:
    mgr, factory, rec = _build(scope_roots=[tmp_path])
    try:
        session = await mgr.create_session(CONV)
        factory.created[0].feed_eof()  # process exited (user typed `exit`)
        await asyncio.sleep(0.1)
        assert mgr.get_session(CONV, session.id) is None
        assert len(rec.of("terminal.closed")) == 1
    finally:
        await mgr.shutdown()


# ---------------------------------------------------------------------------
# Kill / rename / cleanup
# ---------------------------------------------------------------------------


async def test_kill_session_no_double_close(tmp_path: Path) -> None:
    mgr, factory, rec = _build(scope_roots=[tmp_path])
    try:
        session = await mgr.create_session(CONV)
        assert await mgr.kill_session(CONV, session.id) is True
        assert mgr.get_session(CONV, session.id) is None
        assert factory.created[0].terminated is True
        # kill() also unblocks the reader (EOF) -> on_exit, but the session was
        # already removed, so no SECOND terminal.closed is emitted.
        await asyncio.sleep(0.1)
        assert len(rec.of("terminal.closed")) == 1
        assert await mgr.kill_session(CONV, session.id) is False
    finally:
        await mgr.shutdown()


async def test_rename_emits_and_updates(tmp_path: Path) -> None:
    mgr, _factory, rec = _build(scope_roots=[tmp_path])
    try:
        session = await mgr.create_session(CONV)
        assert await mgr.rename(CONV, session.id, "Build") is True
        assert session.title == "Build"
        assert rec.of("terminal.renamed")[-1]["title"] == "Build"
        assert await mgr.rename(CONV, "missing", "x") is False
    finally:
        await mgr.shutdown()


async def test_cleanup_conversation_kills_all(tmp_path: Path) -> None:
    mgr, factory, rec = _build(scope_roots=[tmp_path])
    a = await mgr.create_session(CONV)
    b = await mgr.create_session(CONV)
    await mgr.cleanup_conversation(CONV)
    assert mgr.list_sessions(CONV) == []
    assert all(f.terminated for f in factory.created)
    assert {e["session_id"] for e in rec.of("terminal.closed")} == {a.id, b.id}


# ---------------------------------------------------------------------------
# Real-process integration (Windows ConPTY) — the full reader-thread bridge
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ConPTY backend")
async def test_real_pty_output_bridges_to_events(tmp_path: Path) -> None:
    """A real shell's typed-command output reaches a terminal.output event.

    Exercises the production path end-to-end: real spawn → real reader thread →
    ``call_soon_threadsafe`` bridge → async event emit → write routing → kill.
    """
    pytest.importorskip("winpty")
    rec = _Recorder()

    def scope_provider(_cid: str) -> list[Path]:
        return [tmp_path]

    mgr = TerminalSessionManager(
        scope_provider=scope_provider,
        scope_config=WorkspaceScopeConfig(),
        event_callback=rec,
        pty_factory=spawn_pty,  # the real platform backend
        job_factory=lambda _pid: None,
    )
    try:
        session = await mgr.create_session(CONV)
        await asyncio.sleep(0.7)  # prompt initialises
        await mgr.write_input(CONV, session.id, "echo ALICE_MGR_OK\r\n")
        marker_seen = False
        for _ in range(25):  # up to ~5s
            await asyncio.sleep(0.2)
            joined = "".join(e["data"] for e in rec.of("terminal.output"))
            if "ALICE_MGR_OK" in joined:
                marker_seen = True
                break
        assert marker_seen, "typed command output never bridged to an event"
    finally:
        await mgr.shutdown()
