"""AL\\CE — Tests for the scoped terminal plugin (Fase 6d-4).

The plugin is the *orchestrator* over the already-reviewed security primitives,
so these tests pin its decision tree rather than re-testing the primitives:

* **gating** — the tool is hidden unless ``config.terminal.enabled``;
* **guards** — unknown tool, disabled execute, screenshot lockout, missing
  command all short-circuit to errors;
* **cwd resolution** — explicit scope, ephemeral sandbox fallback, and the
  ``disabled`` fallback each route correctly, and an explicit out-of-scope
  ``cwd`` is rejected;
* **wiring** — a real subprocess actually runs in the resolved directory, and a
  bad command / unknown program become tool errors while a non-zero exit and a
  timeout stay *successful* results.

The real-subprocess cases run ``sys.executable`` with no shell.  ``build_argv``
uses ``shlex.split(posix=False)``, which **retains** quote characters in tokens,
so the command string must use an *unquoted* (space-free) interpreter path and a
*space-free* ``-c`` body — single quotes survive ``posix=False`` and reach
Python as valid string delimiters.  (Wrapping the path in double quotes would
leave literal quotes in ``argv[0]`` and break ``create_subprocess_exec``.)
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.core.config import TerminalConfig, WorkspaceScopeConfig
from backend.core.plugin_models import ExecutionContext
from backend.core.screenshot_lockout import get_lockout
from backend.plugins.terminal.plugin import TerminalPlugin

# A real-UUID-shaped id (a single safe path component, so ``ensure_sandbox``
# accepts it) — keys the per-conversation scope/sandbox.
CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"

# Space-free ``-c`` bodies (see the module docstring on the quoting contract).
PRINT_CWD = "print('scoped-ok');print(__import__('os').getcwd())"
EXIT2 = "__import__('sys').exit(2)"

# The real-subprocess cases need a space-free interpreter path because
# ``build_argv`` (shlex ``posix=False``) cannot round-trip a quoted path.
_needs_spacefree_py = pytest.mark.skipif(
    " " in sys.executable,
    reason="terminal round-trip needs a space-free interpreter path",
)


def _cmd(script: str) -> str:
    """Build a shell-free command string: unquoted interpreter + space-free body."""
    return f"{sys.executable} -c {script}"


def _make_ctx(
    tmp_path: Path,
    *,
    enabled: bool = True,
    fallback_mode: str = "sandbox",
    scope_roots: list[Path] | None = None,
) -> SimpleNamespace:
    """Build a fake ``AppContext`` exposing only what the plugin reads.

    Args:
        tmp_path: The test's temp dir (the sandbox root lives under it).
        enabled: Value for ``config.terminal.enabled``.
        fallback_mode: ``"sandbox"`` or ``"disabled"`` for the no-scope path.
        scope_roots: What ``scope_service.scope_roots`` returns (``None`` ⇒ no
            explicit scope).

    Returns:
        A ``SimpleNamespace`` with ``.config.terminal``, ``.config.scope`` and
        ``.scope_service``.
    """
    terminal_cfg = TerminalConfig(enabled=enabled)
    scope_cfg = WorkspaceScopeConfig(
        forbidden_paths=[],
        fallback_mode=fallback_mode,  # type: ignore[arg-type]
        sandbox_root=str(tmp_path / "sb"),
    )
    config = SimpleNamespace(terminal=terminal_cfg, scope=scope_cfg)
    scope_service = SimpleNamespace(scope_roots=lambda _cid: scope_roots)
    return SimpleNamespace(config=config, scope_service=scope_service)


async def _make_plugin(tmp_path: Path, **kwargs: Any) -> TerminalPlugin:
    """Return an initialised ``TerminalPlugin`` wired to a fake context."""
    plugin = TerminalPlugin()
    await plugin.initialize(_make_ctx(tmp_path, **kwargs))
    return plugin


def _ctx() -> ExecutionContext:
    """Return a real ``ExecutionContext`` keyed to ``CONVERSATION_ID``."""
    return ExecutionContext(
        session_id="s", conversation_id=CONVERSATION_ID, execution_id="e"
    )


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------


async def test_get_tools_empty_when_disabled(tmp_path: Path) -> None:
    plugin = await _make_plugin(tmp_path, enabled=False)
    assert plugin.get_tools() == []


async def test_get_tools_one_tool_when_enabled(tmp_path: Path) -> None:
    plugin = await _make_plugin(tmp_path, enabled=True)
    tools = plugin.get_tools()

    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "run_terminal_command"
    assert tool.risk_level == "dangerous"
    assert tool.requires_confirmation is True
    assert tool.result_type == "string"
    assert tool.capabilities == ("process_exec", "fs_write")
    assert tool.path_args == ("cwd",)
    assert tool.supports_cancellation is True


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


async def test_unknown_tool_returns_error(tmp_path: Path) -> None:
    plugin = await _make_plugin(tmp_path, enabled=True)
    res = await plugin.execute_tool("not_a_tool", {}, _ctx())
    assert res.success is False
    assert "Unknown tool" in (res.error_message or "")


async def test_execute_when_disabled_returns_error(tmp_path: Path) -> None:
    plugin = await _make_plugin(tmp_path, enabled=False)
    res = await plugin.execute_tool(
        "run_terminal_command", {"command": "whoami"}, _ctx()
    )
    assert res.success is False
    assert "disabled" in (res.error_message or "").lower()


async def test_lockout_blocks_execution(tmp_path: Path) -> None:
    plugin = await _make_plugin(tmp_path, enabled=True, scope_roots=None)
    get_lockout().record_screenshot()
    try:
        res = await plugin.execute_tool(
            "run_terminal_command", {"command": _cmd(PRINT_CWD)}, _ctx()
        )
        assert res.success is False
        assert "lock" in (res.error_message or "").lower()
    finally:
        # Reset the process-wide singleton so it never poisons other tests.
        get_lockout()._last_screenshot = 0.0


async def test_missing_command_returns_error(tmp_path: Path) -> None:
    plugin = await _make_plugin(tmp_path, enabled=True)
    res = await plugin.execute_tool("run_terminal_command", {}, _ctx())
    assert res.success is False
    assert "command" in (res.error_message or "").lower()


# ---------------------------------------------------------------------------
# cwd resolution + real subprocess
# ---------------------------------------------------------------------------


@_needs_spacefree_py
async def test_scope_happy_path_runs_in_scope_dir(tmp_path: Path) -> None:
    ws = (tmp_path / "ws").resolve()
    ws.mkdir()
    plugin = await _make_plugin(tmp_path, enabled=True, scope_roots=[ws])

    res = await plugin.execute_tool(
        "run_terminal_command", {"command": _cmd(PRINT_CWD)}, _ctx()
    )

    assert res.success is True
    content = res.content
    assert isinstance(content, str)
    assert "scoped-ok" in content
    # The child's os.getcwd() (printed) is the resolved scope dir.
    assert str(ws) in content


async def test_explicit_out_of_scope_cwd_errors(tmp_path: Path) -> None:
    ws = (tmp_path / "ws").resolve()
    ws.mkdir()
    other = (tmp_path / "other").resolve()
    other.mkdir()
    plugin = await _make_plugin(tmp_path, enabled=True, scope_roots=[ws])

    res = await plugin.execute_tool(
        "run_terminal_command",
        {"command": "whoami", "cwd": str(other)},
        _ctx(),
    )

    assert res.success is False
    assert "scope" in (res.error_message or "").lower()


@_needs_spacefree_py
async def test_no_scope_sandbox_fallback(tmp_path: Path) -> None:
    plugin = await _make_plugin(
        tmp_path, enabled=True, fallback_mode="sandbox", scope_roots=None
    )

    res = await plugin.execute_tool(
        "run_terminal_command", {"command": _cmd(PRINT_CWD)}, _ctx()
    )

    assert res.success is True
    content = res.content
    assert isinstance(content, str)
    sandbox_root = (tmp_path / "sb").resolve()
    # The child ran under <sandbox_root>/<conversation_id>.
    assert str(sandbox_root) in content
    assert CONVERSATION_ID in content


async def test_no_scope_disabled_fallback_errors(tmp_path: Path) -> None:
    plugin = await _make_plugin(
        tmp_path, enabled=True, fallback_mode="disabled", scope_roots=None
    )

    res = await plugin.execute_tool(
        "run_terminal_command", {"command": _cmd(PRINT_CWD)}, _ctx()
    )

    assert res.success is False
    assert "scope" in (res.error_message or "").lower()


# ---------------------------------------------------------------------------
# Command validation + exit semantics
# ---------------------------------------------------------------------------


async def test_bad_command_unbalanced_quotes_errors(tmp_path: Path) -> None:
    plugin = await _make_plugin(tmp_path, enabled=True, scope_roots=None)
    res = await plugin.execute_tool(
        "run_terminal_command", {"command": '"unbalanced'}, _ctx()
    )
    assert res.success is False
    assert "quot" in (res.error_message or "").lower()


async def test_program_not_found_errors(tmp_path: Path) -> None:
    plugin = await _make_plugin(tmp_path, enabled=True, scope_roots=None)
    res = await plugin.execute_tool(
        "run_terminal_command",
        {"command": "definitely_not_real_xyz.exe"},
        _ctx(),
    )
    assert res.success is False
    assert "not found" in (res.error_message or "").lower()


@_needs_spacefree_py
async def test_nonzero_exit_is_ok_result(tmp_path: Path) -> None:
    plugin = await _make_plugin(tmp_path, enabled=True, scope_roots=None)
    res = await plugin.execute_tool(
        "run_terminal_command", {"command": _cmd(EXIT2)}, _ctx()
    )

    # The command ran — a non-zero exit is a *successful* tool result.
    assert res.success is True
    content = res.content
    assert isinstance(content, str)
    assert "code 2" in content
