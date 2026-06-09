"""pc_automation must confine command execution to the active workspace.

The model used to write files into the OS user home because
``execute_command`` ran whitelisted shell commands with ``cwd=None`` and
honoured absolute paths embedded in the command string. These tests drive
the confinement helper that rejects absolute paths escaping the workspace,
plus the dispatcher wiring that passes ``cwd=workspace_root`` into the
executor so relative paths resolve inside the sandbox.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus
from backend.core.plugin_models import ExecutionContext
from backend.plugins.pc_automation.security import command_paths_within_workspace

# ---------------------------------------------------------------------------
# Helper: command_paths_within_workspace
# ---------------------------------------------------------------------------


def test_absolute_path_outside_workspace_is_rejected(tmp_path):
    """An absolute path outside the workspace is rejected."""
    ws = str(tmp_path / "ws")
    ok, reason = command_paths_within_workspace("mkdir C:\\Users\\zagor\\escape", ws)
    assert ok is False
    assert "workspace" in reason.lower()


def test_relative_command_is_allowed(tmp_path):
    """A purely relative command is allowed (resolves under cwd=workspace)."""
    ws = str(tmp_path / "ws")
    ok, _ = command_paths_within_workspace("mkdir subdir", ws)
    assert ok is True


def test_absolute_path_inside_workspace_is_allowed(tmp_path):
    """An absolute path that stays inside the workspace is allowed."""
    ws = tmp_path / "ws"
    ws.mkdir()
    inside = str(ws / "child")
    ok, _ = command_paths_within_workspace(f"mkdir {inside}", str(ws))
    assert ok is True


def test_no_workspace_root_does_not_confine(tmp_path):
    """When no workspace is known, confinement is skipped (allow)."""
    inside = str(tmp_path / "anywhere")
    ok, _ = command_paths_within_workspace(f"mkdir {inside}", None)
    assert ok is True


def test_relative_parent_traversal_is_rejected(tmp_path):
    """A relative ``..\\..`` token climbing above the sandbox is rejected."""
    ws = str(tmp_path / "ws")
    ok, reason = command_paths_within_workspace("mkdir ..\\..\\PWNED", ws)
    assert ok is False
    assert "workspace" in reason.lower()


def test_deep_traversal_to_user_home_is_rejected(tmp_path):
    """A weaponised deep ``..`` traversal to the user home is rejected."""
    ws = str(tmp_path / "outer" / "ws")
    ok, _ = command_paths_within_workspace(
        "copy a.txt ..\\..\\..\\..\\Users\\victim\\evil.txt", ws
    )
    assert ok is False


def test_drive_relative_other_drive_is_rejected(tmp_path):
    """A drive-relative ``D:foo`` token (no separator) is rejected."""
    ws = str(tmp_path / "ws")
    ok, _ = command_paths_within_workspace("mkdir D:foo", ws)
    assert ok is False


# ---------------------------------------------------------------------------
# Dispatcher wiring: cwd=workspace_root and escape rejection
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx() -> AppContext:
    """Minimal AppContext with real config and fresh EventBus."""
    return AppContext(config=load_config(), event_bus=EventBus())


def _exec_context(workspace_root: str | None) -> ExecutionContext:
    return ExecutionContext(
        session_id="test-session",
        conversation_id="test-conv-id",
        execution_id="test-exec-id",
        workspace_root=workspace_root,
    )


@pytest.mark.asyncio
async def test_dispatcher_passes_cwd_to_executor(ctx, tmp_path):
    """execute_command threads context.workspace_root into exec_command as cwd."""
    from backend.plugins.pc_automation.plugin import PcAutomationPlugin

    ws = str(tmp_path / "ws")
    plugin = PcAutomationPlugin()
    await plugin.initialize(ctx)

    with patch(
        "backend.plugins.pc_automation.plugin.exec_command",
        new=AsyncMock(return_value="ok"),
    ) as mock_exec:
        result = await plugin.execute_tool(
            "execute_command", {"command": "mkdir subdir"}, _exec_context(ws),
        )

    assert result.success
    mock_exec.assert_awaited_once()
    # cwd is passed (kwarg or 2nd positional) as the workspace root
    _, kwargs = mock_exec.call_args
    cwd = kwargs.get("cwd")
    if cwd is None and len(mock_exec.call_args.args) > 1:
        cwd = mock_exec.call_args.args[1]
    assert cwd == ws


@pytest.mark.asyncio
async def test_dispatcher_rejects_escaping_command(ctx, tmp_path):
    """execute_command refuses an absolute path that escapes the workspace."""
    from backend.plugins.pc_automation.plugin import PcAutomationPlugin

    ws = str(tmp_path / "ws")
    plugin = PcAutomationPlugin()
    await plugin.initialize(ctx)

    with patch(
        "backend.plugins.pc_automation.plugin.exec_command",
        new=AsyncMock(return_value="ok"),
    ) as mock_exec:
        result = await plugin.execute_tool(
            "execute_command",
            {"command": "mkdir C:\\Users\\zagor\\escape"},
            _exec_context(ws),
        )

    assert not result.success
    assert result.error_message and "workspace" in result.error_message.lower()
    mock_exec.assert_not_awaited()


def test_exec_tools_declare_process_exec_capability():
    """execute_command and open_application declare the process_exec capability."""
    from backend.plugins.pc_automation.plugin import PcAutomationPlugin

    tools = {t.name: t for t in PcAutomationPlugin().get_tools()}
    assert "process_exec" in tools["execute_command"].capabilities
    assert "process_exec" in tools["open_application"].capabilities
