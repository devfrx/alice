"""Tests for the tier → behaviour mapping (Fase 7 extension).

Covers the three pieces that make the permission tier actually shape the agent
rather than only gate calls:

* :func:`backend.services.permission_mode_policy.policy_for` — the tier →
  ``ModePolicy`` mapping;
* :meth:`backend.core.tool_registry.ToolRegistry.apply_mode_policy` — the
  capability-/plugin-driven toolset reshape;
* :func:`backend.api.routes.chat._helpers._build_permission_context` — the
  workspace-scope + tier system-prompt block.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.api.routes.chat._helpers import _build_permission_context
from backend.core.plugin_models import ToolDefinition
from backend.core.tool_registry import ToolRegistry
from backend.services.permission_mode_policy import policy_for
from backend.services.permission_mode_service import PermissionMode


def _entry(ns_name: str) -> dict:
    """A minimal OpenAI-format tool dict keyed by namespaced name."""
    return {"type": "function", "function": {"name": ns_name, "parameters": {}}}


def _registry(
    tools: dict[str, ToolDefinition], plugins: dict[str, str],
) -> ToolRegistry:
    """A ToolRegistry with its lookup tables injected (no plugins needed)."""
    reg = ToolRegistry(MagicMock(), MagicMock())
    reg._tools = tools
    reg._tool_to_plugin = plugins
    return reg


# ---------------------------------------------------------------------------
# policy_for
# ---------------------------------------------------------------------------


class TestPolicyFor:
    def test_plan_is_read_only_and_leads_with_planning(self) -> None:
        policy = policy_for(PermissionMode.PLAN)
        assert policy.blocked_capabilities == frozenset({"fs_write", "process_exec"})
        assert policy.priority_plugins == ("agent",)
        assert "plan" in policy.guidance.lower()

    def test_non_plan_tiers_keep_full_toolset_but_still_steer(self) -> None:
        for mode in (
            PermissionMode.STRICT,
            PermissionMode.AUTO_EDITS,
            PermissionMode.AUTOPILOT,
        ):
            policy = policy_for(mode)
            assert policy.blocked_capabilities == frozenset()
            assert policy.priority_plugins == ()
            assert policy.guidance  # every tier contributes guidance


# ---------------------------------------------------------------------------
# ToolRegistry.apply_mode_policy
# ---------------------------------------------------------------------------


class TestApplyModePolicy:
    def _fixtures(self) -> tuple[dict[str, ToolDefinition], dict[str, str]]:
        tools = {
            "pc_automation_write_file": ToolDefinition(
                name="write_file", description="w", capabilities=("fs_write",),
            ),
            "terminal_run": ToolDefinition(
                name="run", description="r", capabilities=("process_exec",),
            ),
            "file_search_find": ToolDefinition(
                name="find", description="f", capabilities=("fs_read",),
            ),
            "agent_update_tasks": ToolDefinition(
                name="update_tasks", description="p",
            ),
            "web_search_search": ToolDefinition(
                name="search", description="s",
            ),
        }
        plugins = {
            "pc_automation_write_file": "pc_automation",
            "terminal_run": "terminal",
            "file_search_find": "file_search",
            "agent_update_tasks": "agent",
            "web_search_search": "web_search",
        }
        return tools, plugins

    def test_plan_drops_write_exec_and_floats_planning(self) -> None:
        reg = _registry(*self._fixtures())
        tools = [
            _entry(n)
            for n in (
                "pc_automation_write_file",
                "terminal_run",
                "file_search_find",
                "agent_update_tasks",
                "web_search_search",
            )
        ]
        policy = policy_for(PermissionMode.PLAN)
        out = reg.apply_mode_policy(
            tools,
            drop_capabilities=policy.blocked_capabilities,
            priority_plugins=policy.priority_plugins,
        )
        names = [t["function"]["name"] for t in out]

        # write/exec withheld (gate would deny them in plan anyway).
        assert "pc_automation_write_file" not in names
        assert "terminal_run" not in names
        # planning floated to the very front.
        assert names[0] == "agent_update_tasks"
        # reads and other safe tools survive.
        assert "file_search_find" in names
        assert "web_search_search" in names
        # the input list is not mutated.
        assert len(tools) == 5

    def test_defaults_are_identity(self) -> None:
        reg = _registry(*self._fixtures())
        tools = [_entry("web_search_search"), _entry("file_search_find")]
        out = reg.apply_mode_policy(tools)
        assert [t["function"]["name"] for t in out] == [
            "web_search_search",
            "file_search_find",
        ]

    def test_unknown_tool_is_never_dropped(self) -> None:
        reg = _registry(*self._fixtures())
        tools = [_entry("mystery_tool")]  # no definition registered
        out = reg.apply_mode_policy(
            tools, drop_capabilities=frozenset({"fs_write"}),
        )
        assert [t["function"]["name"] for t in out] == ["mystery_tool"]


# ---------------------------------------------------------------------------
# _build_permission_context
# ---------------------------------------------------------------------------


class TestBuildPermissionContext:
    def _ctx(self, roots: list[Path] | None) -> SimpleNamespace:
        scope = MagicMock()
        scope.scope_roots.return_value = roots
        return SimpleNamespace(scope_service=scope)

    def test_lists_scope_folders_when_set(self) -> None:
        ctx = self._ctx([Path("C:/Users/Jays/Desktop")])
        block = _build_permission_context(
            ctx, "conv-1", PermissionMode.STRICT, policy_for(PermissionMode.STRICT),
        )
        assert block is not None
        assert "[AMBITO DI LAVORO]" in block
        assert "Desktop" in block
        assert "[MODALITÀ OPERATIVA]" in block

    def test_prompts_for_a_scope_when_unset(self) -> None:
        ctx = self._ctx(None)
        block = _build_permission_context(
            ctx, "conv-1", PermissionMode.PLAN, policy_for(PermissionMode.PLAN),
        )
        assert block is not None
        assert "Nessuna cartella" in block
        # plan guidance still present even with no scope.
        assert "plan" in block.lower()

    def test_returns_none_without_scope_service_or_policy(self) -> None:
        ctx = SimpleNamespace(scope_service=None)
        assert _build_permission_context(ctx, "conv-1", None, None) is None
