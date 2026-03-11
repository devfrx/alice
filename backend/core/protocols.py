"""O.M.N.I.A. — Service protocols (structural typing for DI).

Defines :class:`~typing.Protocol` classes that describe the public API
expected from each pluggable service.  ``AppContext`` references these
protocols instead of ``Any``, giving static type-checkers something
useful to verify without creating hard import cycles.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)

if TYPE_CHECKING:
    from backend.core.config import OmniaConfig


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
        memory_context: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build the full message list for a chat completion request."""
        ...

    def build_continuation_messages(
        self,
        history: list[dict[str, Any]],
        memory_context: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages for tool-loop continuation (no new user message)."""
        ...

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        cancel_event: asyncio.Event | None = None,
        *,
        user_content: str | None = None,
        conversation_id: str | None = None,
        attachments: list[dict[str, str]] | None = None,
        memory_context: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion, yielding event dicts."""
        ...

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        ...


# ---------------------------------------------------------------------------
# STT / TTS
# ---------------------------------------------------------------------------


class TranscriptResult(Protocol):
    """Result returned by STT transcription."""

    text: str
    language: str
    confidence: float
    duration_s: float


@runtime_checkable
class STTServiceProtocol(Protocol):
    """Protocol for speech-to-text services."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health_check(self) -> bool: ...

    @property
    def engine(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def transcribe(
        self, audio_data: bytes, sample_rate: int = 16000,
    ) -> TranscriptResult:
        """Transcribe audio bytes, returning a TranscriptResult."""
        ...


@runtime_checkable
class TTSServiceProtocol(Protocol):
    """Protocol for text-to-speech services."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health_check(self) -> bool: ...

    @property
    def engine(self) -> str: ...

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to audio bytes (WAV)."""
        ...

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield audio chunks as they are synthesized."""
        ...

    @property
    def sample_rate(self) -> int: ...


# ---------------------------------------------------------------------------
# VRAM Monitor
# ---------------------------------------------------------------------------


@runtime_checkable
class VRAMMonitorProtocol(Protocol):
    """Protocol for GPU VRAM monitoring."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health_check(self) -> bool: ...
    async def get_usage(self) -> Any:
        """Return current VRAM usage information."""
        ...
    def register_component(self, name: str, estimated_mb: int) -> None: ...
    def unregister_component(self, name: str) -> None: ...

    @property
    def last_usage(self) -> Any:
        """Most recent cached VRAM usage (None before first poll)."""
        ...


# ---------------------------------------------------------------------------
# Plugin manager
# ---------------------------------------------------------------------------


@runtime_checkable
class PluginManagerProtocol(Protocol):
    """Protocol for the plugin manager."""

    async def startup(self) -> None: ...
    async def shutdown(self) -> None: ...
    async def health_check(self) -> bool: ...
    async def check_health(self) -> dict[str, ConnectionStatus]: ...
    async def load_plugin(self, name: str) -> bool: ...
    async def unload_plugin(self, name: str) -> bool: ...
    async def reload_plugin(self, name: str) -> bool: ...
    def get_plugin(self, name: str) -> Any: ...
    def get_all_plugins(self) -> dict[str, Any]: ...
    def get_loaded_plugin_names(self) -> list[str]: ...
    def discover_available_plugins(self) -> dict[str, Any]: ...
    async def get_all_status(self) -> dict[str, ConnectionStatus]: ...


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolRegistryProtocol(Protocol):
    """Protocol for the tool registry."""

    def get_all_tools(self) -> list[dict[str, Any]]: ...
    async def get_available_tools(self) -> list[dict[str, Any]]: ...
    async def execute_tool(
        self, tool_name: str, args: dict[str, Any], context: ExecutionContext,
    ) -> ToolResult: ...
    async def refresh(self) -> None: ...
    def get_tool_plugin(self, tool_name: str) -> str | None: ...
    def get_tool_definition(self, tool_name: str) -> ToolDefinition | None: ...
    def limit_tools(
        self,
        tools: list[dict[str, Any]],
        max_tools: int,
        priority_plugins: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# LM Studio manager
# ---------------------------------------------------------------------------


@runtime_checkable
class LMStudioManagerProtocol(Protocol):
    """Protocol for the LM Studio v1 REST API manager."""

    @property
    def current_operation(self) -> dict | None: ...

    @property
    def is_busy(self) -> bool: ...

    async def list_models(self) -> dict: ...

    async def load_model(
        self,
        model: str,
        *,
        context_length: int | None = None,
        flash_attention: bool | None = None,
        eval_batch_size: int | None = None,
        num_experts: int | None = None,
        offload_kv_cache_to_gpu: bool | None = None,
    ) -> dict: ...

    async def unload_model(self, instance_id: str) -> dict: ...

    async def download_model(
        self, model: str, *, quantization: str | None = None,
    ) -> dict: ...

    async def get_download_status(self, job_id: str) -> dict: ...

    async def check_health(self) -> bool: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Conversation file manager
# ---------------------------------------------------------------------------


@runtime_checkable
class ConversationFileManagerProtocol(Protocol):
    """Protocol for file-based conversation persistence."""

    @property
    def base_dir(self) -> Path:
        """The directory where conversation JSON files are stored."""
        ...

    async def save(
        self, conversation_data: dict[str, Any], user_id: str | None = None,
    ) -> None:
        """Persist a conversation dict to its JSON file."""
        ...

    async def delete(
        self, conversation_id: str, user_id: str | None = None,
    ) -> None:
        """Remove the JSON file for a conversation."""
        ...

    async def delete_all(self, user_id: str | None = None) -> int:
        """Remove all JSON conversation files."""
        ...

    async def load(
        self, conversation_id: str, user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Read a single conversation from its JSON file."""
        ...

    async def load_all(
        self, user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read all conversation JSON files."""
        ...

    async def rebuild_from_files(
        self, session_factory: Any,
    ) -> int:
        """Rebuild DB from saved JSON files."""
        ...


# ---------------------------------------------------------------------------
# Preferences service
# ---------------------------------------------------------------------------


@runtime_checkable
class PreferencesServiceProtocol(Protocol):
    """Protocol for user preferences persistence."""

    async def load_all(self) -> dict[str, Any]:
        """Load all stored preferences."""
        ...

    def apply_to_config(
        self, config: OmniaConfig, prefs: dict[str, Any],
    ) -> None:
        """Overlay persisted preferences onto config."""
        ...

    async def save_preference(
        self, key: str, value: Any,
    ) -> None:
        """Save a single preference."""
        ...

    async def save_section(
        self, section: str, data: dict[str, Any],
    ) -> None:
        """Persist all keys in a section."""
        ...

    async def persist_from_update(
        self, body: dict[str, Any],
    ) -> None:
        """Extract and persist preferences from update."""
        ...

    async def delete_all(self) -> int:
        """Delete all persisted preferences."""
        ...


# ---------------------------------------------------------------------------
# Memory service
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryServiceProtocol(Protocol):
    """Protocol for the persistent semantic memory service."""

    async def initialize(self) -> None:
        """Open DB, load extensions, create tables, start cleanup."""
        ...

    async def add(
        self,
        content: str,
        *,
        scope: str = "long_term",
        category: str | None = None,
        source: str = "llm",
        conversation_id: str | None = None,
        expires_at: datetime | None = None,
    ) -> Any:
        """Store a new memory entry with its embedding."""
        ...

    async def search(
        self,
        query: str,
        *,
        k: int = 5,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search memories by semantic similarity."""
        ...

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        ...

    async def list(
        self,
        *,
        filter: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        """List memories with optional filters. Returns (entries, total)."""
        ...

    async def stats(self) -> dict[str, Any]:
        """Return memory statistics."""
        ...

    async def delete_by_scope(self, scope: str) -> int:
        """Delete all memories of a given scope. Returns count deleted."""
        ...

    async def close(self) -> None:
        """Shut down the memory service."""
        ...


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------


@runtime_checkable
class WSConnectionManagerProtocol(Protocol):
    """Protocol for the persistent event WebSocket connection manager."""

    async def connect(self, session_id: str, ws: Any) -> None:
        """Accept and register a WebSocket connection."""
        ...

    async def disconnect(self, session_id: str) -> None:
        """Remove a WebSocket connection."""
        ...

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Send an event to all connected clients."""
        ...

    async def send_to(self, session_id: str, event: dict[str, Any]) -> None:
        """Send an event to a specific session."""
        ...
