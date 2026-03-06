"""O.M.N.I.A. — Service protocols (structural typing for DI).

Defines :class:`~typing.Protocol` classes that describe the public API
expected from each pluggable service.  ``AppContext`` references these
protocols instead of ``Any``, giving static type-checkers something
useful to verify without creating hard import cycles.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Base lifecycle
# ---------------------------------------------------------------------------


@runtime_checkable
class BaseService(Protocol):
    """Minimal lifecycle interface for managed services.

    All long-lived services should support async start/stop and a
    health-check probe.
    """

    async def start(self) -> None:
        """Perform any async initialisation (connections, warm-up, …)."""
        ...

    async def stop(self) -> None:
        """Release resources gracefully."""
        ...

    async def health_check(self) -> bool:
        """Return ``True`` when the service is operational."""
        ...


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMServiceProtocol(Protocol):
    """Protocol for language-model services."""

    def build_messages(
        self,
        user_content: str,
        history: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build the full message list for a chat completion request."""
        ...

    def build_continuation_messages(
        self,
        history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build messages for tool-loop continuation (no new user message)."""
        ...

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion, yielding event dicts."""
        ...

    async def chat_sync(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a non-streaming chat completion request."""
        ...

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        ...


# ---------------------------------------------------------------------------
# STT / TTS
# ---------------------------------------------------------------------------


@runtime_checkable
class STTServiceProtocol(Protocol):
    """Protocol for speech-to-text services."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health_check(self) -> bool: ...


@runtime_checkable
class TTSServiceProtocol(Protocol):
    """Protocol for text-to-speech services."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health_check(self) -> bool: ...


# ---------------------------------------------------------------------------
# Plugin manager
# ---------------------------------------------------------------------------


@runtime_checkable
class PluginManagerProtocol(Protocol):
    """Protocol for the plugin manager."""

    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def health_check(self) -> bool: ...
    async def check_health(self) -> dict[str, Any]: ...
    def get_plugin(self, name: str) -> Any: ...
    def get_all_plugins(self) -> dict[str, Any]: ...
    def get_loaded_plugin_names(self) -> list[str]: ...


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolRegistryProtocol(Protocol):
    """Protocol for the tool registry."""

    def get_all_tools(self) -> list[dict[str, Any]]: ...
    async def get_available_tools(self) -> list[dict[str, Any]]: ...
    async def execute_tool(
        self, tool_name: str, args: dict, context: Any,
    ) -> Any: ...
    async def refresh(self) -> None: ...
    def get_tool_plugin(self, tool_name: str) -> str | None: ...
    def get_tool_definition(self, tool_name: str) -> Any: ...


# ---------------------------------------------------------------------------
# Conversation file manager
# ---------------------------------------------------------------------------


@runtime_checkable
class ConversationFileManagerProtocol(Protocol):
    """Protocol for file-based conversation persistence."""

    async def save(self, conversation_data: dict[str, Any]) -> None:
        """Persist a conversation dict to its JSON file."""
        ...

    async def delete(self, conversation_id: str) -> None:
        """Remove the JSON file for a conversation."""
        ...

    async def load(self, conversation_id: str) -> dict[str, Any] | None:
        """Read a single conversation from its JSON file."""
        ...

    async def load_all(self) -> list[dict[str, Any]]:
        """Read all conversation JSON files."""
        ...

    async def rebuild_from_files(self, session_factory: Any) -> int:
        """Rebuild the database from saved JSON files."""
        ...
