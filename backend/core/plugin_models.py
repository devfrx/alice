"""Plugin system data models and enums.

Foundation types for the OMNIA plugin architecture (Phase 3.1).
Imported by BasePlugin, PluginManager, and protocol definitions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MAX_TOOL_DESCRIPTION_LENGTH: int = 1024
MAX_TOOL_RESULT_LENGTH: int = 4096
PLUGIN_API_VERSION: str = "1.0.0"

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
    """

    name: str
    description: str
    parameters: dict[str, Any] | None = None
    result_type: Literal["string", "json", "binary_base64"] = "string"
    supports_cancellation: bool = False
    timeout_ms: int = 30_000
    requires_confirmation: bool = False
    risk_level: Literal["safe", "medium", "dangerous", "forbidden"] = "safe"
    sanitise_output: bool = True
    max_result_chars: int = MAX_TOOL_RESULT_LENGTH

    def __post_init__(self) -> None:
        if self.parameters is None:
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
    """

    success: bool
    content: str | dict | list | None = None
    content_type: str = "text/plain"
    execution_time_ms: float = 0.0
    truncated: bool = False
    error_message: str | None = None

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
    """

    session_id: str
    conversation_id: str
    execution_id: str
    user_id: str | None = None
