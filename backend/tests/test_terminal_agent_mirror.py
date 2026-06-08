"""AL\\CE — Tests for agent-command terminal mirroring (Fase 7 E2).

When an interactive terminal manager is wired, the agent's bounded
``run_terminal_command`` resolves its cwd from the conversation's *assigned*
terminal session (auto-creating one) and mirrors the ``$ cmd`` + result block
into that session's stream so the user watches what the agent ran.

The assigned session's PTY is a :class:`FakePtyProcess` (no real shell), but the
agent's command itself runs in a **real** subprocess via the bounded executor —
exactly as in production — so the round-trip (cwd resolution + output mirror) is
verified end-to-end.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.core.config import TerminalConfig, WorkspaceScopeConfig
from backend.core.plugin_models import ExecutionContext
from backend.plugins.terminal.plugin import TerminalPlugin
from backend.services.terminal.manager import TerminalSessionManager
from backend.services.terminal.pty_backend import FakePtyProcess

CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"
PRINT_CWD = "print('scoped-ok');print(__import__('os').getcwd())"

_needs_spacefree_py = pytest.mark.skipif(
    " " in sys.executable,
    reason="terminal round-trip needs a space-free interpreter path",
)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def of(self, event_type: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] == event_type]


def _cmd(script: str) -> str:
    return f"{sys.executable} -c {script}"


async def _make_plugin_with_manager(
    tmp_path: Path,
) -> tuple[TerminalPlugin, TerminalSessionManager, _Recorder]:
    scope = tmp_path / "scope"
    scope.mkdir()
    rec = _Recorder()

    def scope_provider(_cid: str) -> list[Path]:
        return [scope]

    manager = TerminalSessionManager(
        scope_provider=scope_provider,
        scope_config=WorkspaceScopeConfig(sandbox_root=str(tmp_path / "sb")),
        event_callback=rec,
        pty_factory=lambda argv, *, cwd, rows=24, cols=80, env=None: FakePtyProcess(),
        job_factory=lambda _pid: None,
    )
    ctx = SimpleNamespace(
        config=SimpleNamespace(
            terminal=TerminalConfig(enabled=True),
            scope=WorkspaceScopeConfig(sandbox_root=str(tmp_path / "sb")),
        ),
        scope_service=SimpleNamespace(scope_roots=scope_provider),
        terminal_session_manager=manager,
    )
    plugin = TerminalPlugin()
    await plugin.initialize(ctx)
    return plugin, manager, rec


def _exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="s", conversation_id=CONVERSATION_ID, execution_id="e",
    )


@_needs_spacefree_py
async def test_agent_command_autocreates_assigns_and_mirrors(tmp_path: Path) -> None:
    plugin, manager, rec = await _make_plugin_with_manager(tmp_path)
    try:
        result = await plugin.execute_tool(
            "run_terminal_command", {"command": _cmd(PRINT_CWD)}, _exec_ctx(),
        )
        content = str(result.content)
        assert result.success is True
        assert "scoped-ok" in content

        # An agent session was auto-created and assigned.
        assigned = manager.assigned_session(CONVERSATION_ID)
        assert assigned is not None
        # The command ran in the assigned session's (in-scope) cwd.
        assert str(assigned.cwd) in content

        # The command + result block was mirrored into that session's stream.
        outputs = rec.of("terminal.output")
        assert outputs, "no terminal.output event mirrored"
        mirrored = "".join(e["data"] for e in outputs if e["session_id"] == assigned.id)
        assert "scoped-ok" in mirrored
    finally:
        await manager.shutdown()


@_needs_spacefree_py
async def test_agent_command_runs_without_manager(tmp_path: Path) -> None:
    """With no manager wired, execution falls back to plain scoped behaviour."""
    scope = tmp_path / "scope"
    scope.mkdir()
    ctx = SimpleNamespace(
        config=SimpleNamespace(
            terminal=TerminalConfig(enabled=True),
            scope=WorkspaceScopeConfig(sandbox_root=str(tmp_path / "sb")),
        ),
        scope_service=SimpleNamespace(scope_roots=lambda _cid: [scope]),
        terminal_session_manager=None,
    )
    plugin = TerminalPlugin()
    await plugin.initialize(ctx)
    result = await plugin.execute_tool(
        "run_terminal_command", {"command": _cmd(PRINT_CWD)}, _exec_ctx(),
    )
    assert result.success is True
    assert "scoped-ok" in str(result.content)
