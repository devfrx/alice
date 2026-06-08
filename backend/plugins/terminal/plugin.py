"""AL\\CE — Scoped terminal plugin (Fase 6d).

Ties the already-built, separately-reviewed security primitives
(:mod:`backend.plugins.terminal.security`) and the bounded subprocess executor
(:mod:`backend.plugins.terminal.executor`) into a native :class:`BasePlugin`
that exposes a single tool, ``run_terminal_command``.

The plugin is the *orchestrator*, not the security boundary — it never
re-implements validation.  Its job is the decision tree around the primitives:

1. honour the post-screenshot lockout (anti-exfiltration);
2. resolve the working directory — an explicit conversation **scope**, else an
   ephemeral per-conversation **sandbox**, else refuse (``fallback_mode`` =
   ``"disabled"``);
3. validate an optional caller-supplied ``cwd`` is *inside* that scope
   (:func:`validate_cwd_within_scope`);
4. tokenise the command with no shell (:func:`build_argv`);
5. run it boundedly (:func:`run_command`) and format the outcome.

Confirmation and audit are *not* this plugin's concern: ``run_terminal_command``
declares ``requires_confirmation=True`` and the ``"process_exec"`` /
``"fs_write"`` capabilities, so the central confirmation gate and the
``PermissionService`` cwd-confinement both apply by construction.  The tool is
**off by default** (``terminal.enabled = False``) and :meth:`get_tools` hides it
entirely until the user opts in.
"""

from __future__ import annotations

import contextlib
from typing import Any

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.core.screenshot_lockout import get_lockout
from backend.plugins.terminal.executor import TerminalResult, run_command
from backend.plugins.terminal.security import (
    build_argv,
    ensure_sandbox,
    validate_cwd_within_scope,
)


class TerminalPlugin(BasePlugin):
    """Scoped, confirmation-gated shell execution confined to the workspace.

    Exposes ``run_terminal_command`` only when ``config.terminal.enabled`` is
    ``True``.  Each invocation runs a single, shell-free command in the
    conversation's scoped folder (or an ephemeral sandbox when no explicit scope
    is set), always behind user confirmation.
    """

    plugin_name: str = "terminal"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Scoped, confirmation-gated shell command execution confined to the "
        "conversation's workspace folder."
    )
    # Uses the *core* scope service + screenshot lockout, not another plugin.
    plugin_dependencies: list[str] = []
    plugin_priority: int = 50

    # -- Tools -------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return the terminal tool, or nothing when the capability is off.

        The terminal is disabled by default; the tool is only advertised once
        the user enables it via ``config.terminal.enabled``.

        Returns:
            A single-element list with ``run_terminal_command`` when enabled, or
            an empty list otherwise.
        """
        if not self.ctx.config.terminal.enabled:
            return []
        return [self._run_terminal_tool()]

    def _run_terminal_tool(self) -> ToolDefinition:
        """Build the ``run_terminal_command`` tool definition.

        Returns:
            The :class:`ToolDefinition` describing the scoped terminal tool.
        """
        timeout_ms = (self.ctx.config.terminal.command_timeout_s + 10) * 1000
        return ToolDefinition(
            name="run_terminal_command",
            description=(
                "Run a single shell command (no shell operators; pipes/redirects "
                "are literal) in the conversation's workspace folder. The working "
                "directory is confined to the scoped folder(s); without a scope an "
                "ephemeral sandbox is used. Every command requires user "
                "confirmation. Optional 'cwd' must be inside the scope."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The command line to run (parsed without a shell).",
                    },
                    "cwd": {
                        "type": "string",
                        "description": (
                            "Optional working directory; must be inside the "
                            "workspace scope."
                        ),
                    },
                },
                "required": ["command"],
            },
            result_type="string",
            risk_level="dangerous",
            requires_confirmation=True,
            capabilities=("process_exec", "fs_write"),
            path_args=("cwd",),
            supports_cancellation=True,
            # One step above the executor's own timeout so the run self-times-out
            # gracefully (returning a partial result) before this outer budget.
            timeout_ms=timeout_ms,
        )

    # -- Execution ---------------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Run ``run_terminal_command`` through the security primitives.

        Flow: tool-name guard → enabled guard → screenshot lockout → command
        presence → working-directory resolution (scope / sandbox / disabled) →
        explicit-``cwd`` containment → shell-free tokenisation → bounded run →
        formatted result.  A non-zero exit and a timeout are **successful**
        results (the command ran); validation failures, an out-of-scope ``cwd``,
        a bad command, and an unknown program become :meth:`ToolResult.error`.
        :class:`asyncio.CancelledError` is allowed to propagate.

        Args:
            tool_name: Must be ``"run_terminal_command"``.
            args: Caller-supplied arguments (``command`` and optional ``cwd``).
            context: Execution metadata (the ``conversation_id`` keys the scope).

        Returns:
            A :class:`ToolResult` with the formatted command output, or an error.
        """
        if tool_name != "run_terminal_command":
            return ToolResult.error(f"Unknown tool: {tool_name}")

        cfg = self.ctx.config.terminal
        if not cfg.enabled:  # defensive — get_tools already hides the tool.
            return ToolResult.error("Terminal is disabled.")

        # Anti-exfiltration: block while a recent screenshot lockout is active.
        lock = get_lockout()
        if lock.is_locked("run_terminal_command"):
            return ToolResult.error(
                f"Terminal locked for {lock.get_remaining_s():.0f}s after a screenshot."
            )

        command = args.get("command")
        if not command or not str(command).strip():
            return ToolResult.error("Missing required parameter: command")

        requested_cwd = args.get("cwd")

        # Fase E2: resolve (auto-creating when absent) the agent's assigned
        # interactive terminal so the command runs in the directory the user
        # sees and its output is mirrored into that terminal tab.  Best-effort:
        # any failure (no scope, missing PTY backend) leaves ``assigned`` None
        # and falls back to plain scoped execution below.
        manager = getattr(self.ctx, "terminal_session_manager", None)
        assigned = None
        if manager is not None:
            with contextlib.suppress(Exception):
                assigned = await manager.ensure_agent_session(context.conversation_id)

        # Resolve the working directory.  Any primitive ValueError (bad sandbox
        # id, out-of-scope/forbidden/nonexistent cwd) becomes a tool error.
        scope_cfg = self.ctx.config.scope
        scope_svc = self.ctx.scope_service
        scope_roots = scope_svc.scope_roots(context.conversation_id) if scope_svc else None
        try:
            if scope_roots:
                roots = scope_roots
            elif scope_cfg.fallback_mode == "sandbox":
                roots = [ensure_sandbox(context.conversation_id, scope_cfg.sandbox_root)]
            else:  # "disabled"
                return ToolResult.error(
                    "No workspace folder scope is set for this conversation."
                )
            if requested_cwd and str(requested_cwd).strip():
                workdir = validate_cwd_within_scope(
                    str(requested_cwd), roots, scope_cfg.forbidden_paths
                )
            elif assigned is not None:
                # Run in the assigned terminal's directory (already in-scope).
                workdir = assigned.cwd
            else:
                workdir = roots[0]
        except ValueError as exc:
            return ToolResult.error(str(exc))

        # Shell-free tokenisation (metacharacters become literal argv tokens).
        try:
            argv = build_argv(str(command))
        except ValueError as exc:
            return ToolResult.error(str(exc))

        # Bounded run.  Never raises for timeout/overflow (encoded in the result);
        # CancelledError propagates (the engine owns turn cancellation).
        try:
            result = await run_command(
                argv,
                workdir,
                timeout_s=cfg.command_timeout_s,
                max_output_bytes=cfg.max_output_bytes,
                allow_network=cfg.allow_network,
            )
        except FileNotFoundError:
            return ToolResult.error(f"Program not found: {argv[0]}")
        except RuntimeError as exc:
            return ToolResult.error(str(exc))

        text = self._format_result(str(command), result, cfg.max_output_bytes)

        # Fase E2: mirror the command + result into the assigned terminal tab so
        # the user watches what the agent ran (display-only — the bounded command
        # ran in its own subprocess, not by injecting keystrokes). Audit it; the
        # confirmation gate already recorded the authorization decision upstream.
        if manager is not None and assigned is not None:
            with contextlib.suppress(Exception):
                await manager.echo_agent_output(
                    context.conversation_id, assigned.id, self._terminal_echo(text),
                )
            logger.info(
                "terminal(agent): conv={} session={} cmd={!r}",
                context.conversation_id, assigned.id, str(command),
            )

        return ToolResult.ok(text, execution_time_ms=result.duration_ms)

    @staticmethod
    def _terminal_echo(text: str) -> str:
        """Frame a result block for display in an xterm terminal (CRLF + spacing)."""
        crlf = text.replace("\r\n", "\n").replace("\n", "\r\n")
        return f"\r\n{crlf}\r\n"

    def _format_result(self, command: str, result: TerminalResult, cap: int) -> str:
        """Render a compact, model/human-readable summary of a run.

        Includes the echoed command, a status line (``exited with code N`` /
        ``timed out after Ns`` / ``terminated (output limit reached)`` when the
        child was killed at the cap), captured stdout, a labelled stderr section
        when non-empty, and a truncation note when the cap was hit.

        Args:
            command: The original command line (echoed for context).
            result: The bounded outcome from :func:`run_command`.
            cap: The per-stream output byte cap (for the truncation note).

        Returns:
            A newline-joined summary string.
        """
        if result.timed_out:
            status = f"timed out after {self.ctx.config.terminal.command_timeout_s}s"
        elif result.returncode is None:
            # Killed without a timeout — only happens at the output cap.
            status = "terminated (output limit reached)"
        else:
            status = f"exited with code {result.returncode}"

        parts: list[str] = [f"$ {command}", f"[{status}]"]

        stdout = result.stdout.rstrip()
        if stdout:
            parts.append(stdout)

        stderr = result.stderr.rstrip()
        if stderr:
            parts.append("[stderr]")
            parts.append(stderr)

        if result.truncated:
            parts.append(f"[output truncated at {cap} bytes/stream]")

        return "\n".join(parts)
