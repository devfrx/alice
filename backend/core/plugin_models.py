"""Plugin system data models and enums.

Foundation types for the AL\\CE plugin architecture (Phase 3.1).
Imported by BasePlugin, PluginManager, and protocol definitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MAX_TOOL_DESCRIPTION_LENGTH: int = 1024
MAX_TOOL_RESULT_LENGTH: int = 15_000
PLUGIN_API_VERSION: str = "1.0.0"

#: Pseudo owner recorded in the catalog's tool→plugin map for kernel-owned
#: tools (spec §7: ``app_command`` belongs to the kernel, not a plugin). The
#: availability probe treats this owner as always connected.
KERNEL_TOOL_OWNER = "kernel"

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConnectionStatus(StrEnum):
    """Health/connectivity state of a plugin's external dependency."""

    UNKNOWN = "unknown"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    DEGRADED = "degraded"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Immutable descriptor for a single tool exposed by a plugin.

    Attributes:
        name: Tool identifier (must match ``TOOL_NAME_PATTERN``).
        description: Human-readable summary (max 1024 chars).
        parameters: JSON Schema describing the tool's arguments.
        result_type: Kind of payload returned by the tool.
        supports_cancellation: Whether the tool honours cancellation.
        timeout_ms: Execution timeout in milliseconds.
        requires_confirmation: Whether user approval is needed (Phase 5).
        risk_level: Safety classification for the tool.
        max_result_chars: Maximum characters in the tool result before truncation.
            Defaults to ``MAX_TOOL_RESULT_LENGTH``. Override for tools that
            return large payloads (e.g. web scraping).
        client_execution: When ``True`` the tool is *not* executed on the
            server. Instead the chat WebSocket delegates execution to the
            connected client (which runs it against live UI state, e.g. the
            open Continuum editor) and feeds the client-supplied result back
            into the LLM loop. The owning plugin's :meth:`execute_tool` is a
            defensive no-op for these tools — they only ever run client-side.
        user_interaction: When ``True`` the tool does not execute on the
            server or client; instead it **suspends the loop to ask the human
            a question** over the InteractionChannel (the ``ask_user``
            meta-tool). The answer becomes the tool result. Handled by
            ``InteractionMiddleware`` (never ``execute_tool``). Mutually
            exclusive with ``client_execution`` in practice.
        capabilities: Coarse capability tags consumed by the central
            ``PermissionService`` / ``PermissionMiddleware`` to confine a tool
            **by construction** (e.g. ``"fs_read"``, ``"fs_write"``,
            ``"process_exec"``). Any ``fs_*`` capability marks the tool as
            path-confined: a new tool that forgets a manual check still cannot
            escape the conversation scope (deny-by-default outside it). Empty
            ⇒ no special policy. Inert until Fase 6 wires a workspace scope.
        path_args: Names of the ``parameters`` keys that carry filesystem
            paths (e.g. ``("path",)``, ``("cwd",)``). The permission layer
            resolves these against the active scope to decide allow/deny — so
            confinement is generic, not per-plugin.
        always_offered: When ``True`` the tool survives every toolset
            *selection* pass — it is included alongside tool-RAG hits,
            never cut by ``limit_tools`` and exempt from the capability
            drop of ``apply_mode_policy``. It is still subject to
            connection-status filtering and to the user's explicit
            per-chat opt-out (``exclude_disabled``). Meant for the agent
            meta-tools, whose presence is part of the protocol surface
            rather than a relevance question.
        usage_guidance: Optional system-prompt fragment (markdown,
            imperative, a few lines) teaching the model WHEN and HOW to
            use this tool. Collected for the tools actually offered in a
            turn and composed into the ``[ORCHESTRAZIONE]`` block — never
            serialised into the OpenAI schema.
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}},
    )
    result_type: Literal["string", "json", "binary_base64"] = "string"
    supports_cancellation: bool = False
    timeout_ms: int = 30_000
    requires_confirmation: bool = False
    risk_level: Literal["safe", "medium", "dangerous", "forbidden"] = "safe"
    sanitise_output: bool = True
    max_result_chars: int = MAX_TOOL_RESULT_LENGTH
    client_execution: bool = False
    user_interaction: bool = False
    capabilities: tuple[str, ...] = ()
    path_args: tuple[str, ...] = ()
    always_offered: bool = False
    usage_guidance: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.parameters, dict):
            object.__setattr__(
                self,
                "parameters",
                {"type": "object", "properties": {}},
            )
        self.validate()

    # -- validation ---------------------------------------------------------

    def validate(self) -> None:
        """Validate name format and description length.

        Raises:
            ValueError: If the name doesn't match the allowed pattern or
                the description exceeds the maximum length.
        """
        if not TOOL_NAME_PATTERN.match(self.name):
            raise ValueError(
                f"Tool name '{self.name}' does not match "
                f"pattern {TOOL_NAME_PATTERN.pattern}"
            )
        if len(self.description) > MAX_TOOL_DESCRIPTION_LENGTH:
            raise ValueError(
                f"Tool description exceeds {MAX_TOOL_DESCRIPTION_LENGTH} "
                f"chars ({len(self.description)})"
            )

    # -- serialisation ------------------------------------------------------

    def to_openai_format(self) -> dict[str, Any]:
        """Return the tool in OpenAI function-calling format.

        Returns:
            Dict compatible with the OpenAI ``tools`` parameter.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(slots=True)
class ToolResult:
    """Mutable result envelope returned after tool execution.

    Attributes:
        success: Whether the tool executed without errors.
        content: Main payload (string for OpenAI compatibility).
        content_type: MIME type of the content.
        execution_time_ms: Wall-clock time spent executing.
        truncated: True if the result was trimmed for size.
        error_message: Human-readable error detail on failure.
        raw_content: Pre-sanitisation snapshot of ``content`` (set by
            :class:`backend.core.tool_registry.ToolRegistry`).  Consumers
            that need un-redacted data (e.g. the artifact registry,
            which has to keep the real ``file_path``) should prefer
            this field over :attr:`content`.
    """

    success: bool
    content: str | dict | list | None = None
    content_type: str = "text/plain"
    execution_time_ms: float = 0.0
    truncated: bool = False
    error_message: str | None = None
    raw_content: str | dict | list | None = None

    # -- convenience constructors -------------------------------------------

    @classmethod
    def ok(
        cls,
        content: str | dict | list | None,
        content_type: str = "text/plain",
        execution_time_ms: float = 0.0,
    ) -> ToolResult:
        """Create a successful result."""
        return cls(
            success=True,
            content=content,
            content_type=content_type,
            execution_time_ms=execution_time_ms,
        )

    @classmethod
    def error(
        cls,
        message: str,
        execution_time_ms: float = 0.0,
    ) -> ToolResult:
        """Create a failure result."""
        return cls(
            success=False,
            error_message=message,
            execution_time_ms=execution_time_ms,
        )


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Immutable context passed to every tool invocation.

    Attributes:
        session_id: Active WebSocket session identifier.
        conversation_id: Current conversation identifier.
        execution_id: Unique UUID for tracking and audit.
        user_id: Reserved for Phase 8 JWT multi-user support.
        workspace_root: Absolute path the tool MUST use as its working
            directory (hard sandbox). Resolved from the conversation's explicit
            scope, or the per-conversation ephemeral sandbox when no scope is
            set. ``None`` when no scope service is wired.
    """

    session_id: str
    conversation_id: str
    execution_id: str
    user_id: str | None = None
    workspace_root: str | None = None
    """Absolute path the tool MUST use as its working directory (hard sandbox).

    Resolved from the conversation's explicit scope, or the per-conversation
    ephemeral sandbox when no scope is set. Never the OS home or a system root.
    """


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    """Descriptor for a future ``/``-command (pre-parsing UX → resolves to a
    tool-call / prompt / UI action). Contract only — no registry or palette
    exists yet (see PLAN.md "Predisposizione comandi /").

    Attributes:
        name: Command name without the leading slash (e.g. ``"plan"``).
        description: Human-readable summary.
        params_schema: JSON Schema for the command's arguments.
        kind: How the command resolves — ``"tool"`` (a tool-call),
            ``"prompt"`` (injected prompt text) or ``"ui"`` (a frontend action).
    """

    name: str
    description: str
    params_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}},
    )
    kind: Literal["tool", "prompt", "ui"] = "tool"
