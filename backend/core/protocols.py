"""AL\\CE — Service protocols (structural typing for DI).

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
    from backend.core.config import AliceConfig


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMServiceProtocol(Protocol):
    """Protocol for language-model services."""

    @property
    def supports_vision(self) -> bool:
        """Whether the active model supports multimodal (vision) input."""
        ...

    def get_system_prompt(
        self, memory_context: str | None = None,
    ) -> str:
        """Build the full system prompt with optional memory context."""
        ...

    def build_messages(
        self,
        user_content: str,
        history: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, str]] | None = None,
        memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build the full message list for a chat completion request."""
        ...

    def build_continuation_messages(
        self,
        history: list[dict[str, Any]],
        memory_context: str | None = None,
        system_prompt: str | None = None,
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
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion, yielding event dicts."""
        ...

    async def complete_nonstreaming(
        self, messages: list[dict[str, Any]], max_tokens: int = 512,
    ) -> str:
        """Complete a chat request without streaming."""
        ...

    async def get_active_context_window(
        self, lmstudio_manager: Any = None,
    ) -> int:
        """Return the active model's context window size in tokens."""
        ...

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        ...


# ---------------------------------------------------------------------------
# Context Manager
# ---------------------------------------------------------------------------


@runtime_checkable
class ContextManagerProtocol(Protocol):
    """Protocol for the context window management service."""

    def estimate_tokens(self, text: str) -> int: ...

    def estimate_message_tokens(self, msg: dict[str, Any]) -> int: ...

    def count_messages_tokens(
        self, messages: list[dict[str, Any]],
    ) -> int: ...

    def get_usage_estimated(
        self, messages: list[dict[str, Any]], context_window: int,
    ) -> Any: ...

    def get_usage_real(
        self, input_tokens: int, context_window: int,
    ) -> Any: ...

    def should_compress(self, usage: Any) -> bool: ...

    async def compress(
        self, messages: list[dict[str, Any]], llm: LLMServiceProtocol,
        context_window: int, reserve: int,
        tool_tokens: int = 0,
    ) -> Any: ...


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
# Qdrant service
# ---------------------------------------------------------------------------


@runtime_checkable
class QdrantServiceProtocol(Protocol):
    """Protocol for the Qdrant vector store service."""

    async def initialize(self) -> None: ...
    async def close(self) -> None: ...

    async def ensure_collection(
        self, name: str, vector_size: int, distance: Any = ...,
    ) -> None: ...

    async def upsert(
        self, collection: str, points: list[Any],
    ) -> None: ...

    async def search(
        self, collection: str, vector: list[float],
        k: int = 5, query_filter: Any | None = None,
    ) -> list[Any]: ...

    async def delete(
        self, collection: str, *,
        ids: list[str] | None = None,
        query_filter: Any | None = None,
    ) -> None: ...

    async def scroll(
        self, collection: str, query_filter: Any | None = None,
        limit: int = 50, offset: str | int | None = None,
    ) -> tuple[list[Any], str | int | None]: ...

    async def count(
        self, collection: str, query_filter: Any | None = None,
    ) -> int: ...

    async def get_collection_dim(self, name: str) -> int: ...


# ---------------------------------------------------------------------------
# Embedding client
# ---------------------------------------------------------------------------


@runtime_checkable
class EmbeddingClientProtocol(Protocol):
    """Protocol for the embedding client facade."""

    @property
    def dimensions(self) -> int: ...

    async def encode(self, text: str) -> list[float]: ...

    async def encode_batch(
        self, texts: list[str],
    ) -> list[list[float]]: ...

    async def close(self) -> None: ...


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
    async def embed_tools(self) -> None: ...
    async def get_relevant_tools(
        self, query: str, k: int,
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

    async def check_health(self) -> bool:
        """Return True if LM Studio is reachable."""
        ...

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        ...


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
        self, config: AliceConfig, prefs: dict[str, Any],
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

    async def delete_all(self) -> int:
        """Delete every stored memory. Returns count deleted."""
        ...

    async def delete_by_scope(self, scope: str) -> int:
        """Delete all memories of a given scope. Returns count deleted."""
        ...

    async def close(self) -> None:
        """Shut down the memory service."""
        ...


# ---------------------------------------------------------------------------
# Note service
# ---------------------------------------------------------------------------


@runtime_checkable
class NoteServiceProtocol(Protocol):
    """Protocol for the Note Service (Obsidian-like note vault)."""

    async def initialize(self) -> None: ...

    async def create(
        self,
        title: str,
        content: str,
        folder_path: str = "",
        tags: list[str] | None = None,
    ) -> Any: ...

    async def get(self, note_id: str) -> Any: ...

    async def update(
        self,
        note_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        folder_path: str | None = None,
        tags: list[str] | None = None,
        pinned: bool | None = None,
    ) -> Any: ...

    async def delete(self, note_id: str) -> bool: ...

    async def search(
        self,
        query: str,
        folder: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[Any]: ...

    async def list(
        self,
        folder: str | None = None,
        tags: list[str] | None = None,
        pinned_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]: ...

    async def get_folders(self) -> list[dict[str, Any]]: ...

    async def delete_folder(
        self, folder_path: str, *, mode: str = "move",
    ) -> int:
        """Delete a folder, moving or removing its notes."""
        ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Email service
# ---------------------------------------------------------------------------


@runtime_checkable
class EmailServiceProtocol(Protocol):
    """Protocol for the async IMAP/SMTP email assistant service."""

    async def initialize(self) -> None: ...

    async def fetch_inbox(
        self,
        *,
        folder: str = "INBOX",
        limit: int = 20,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]: ...

    async def fetch_email(
        self, uid: str, *, folder: str = "INBOX",
    ) -> dict[str, Any] | None: ...

    async def search(
        self,
        query: str,
        *,
        folder: str = "INBOX",
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...

    async def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        *,
        reply_to_uid: str | None = None,
        folder: str = "INBOX",
    ) -> dict[str, Any]: ...

    async def mark_read(
        self, uid: str, *, folder: str = "INBOX", read: bool = True,
    ) -> bool: ...

    async def archive(
        self, uid: str, *, from_folder: str = "INBOX",
    ) -> bool: ...

    async def list_folders(self) -> list[str]: ...

    async def close(self) -> None: ...


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

    @property
    def connection_count(self) -> int:
        """Number of active WebSocket connections."""
        ...


# ---------------------------------------------------------------------------
# Turn execution (Agent Loop v2 — see alice/agent_loop_plan.md §4.4)
# ---------------------------------------------------------------------------


@runtime_checkable
class WSEventSinkProtocol(Protocol):
    """Structural type for outbound event sinks used by turn executors.

    Concrete implementations live in
    :mod:`backend.services.turn.sink` (``WebSocketEventSink``,
    ``RecordingEventSink``).  Defined here so other modules can type
    against the contract without importing the ``turn`` package.
    """

    async def send(self, event: dict[str, Any]) -> None:
        """Deliver ``event`` to the underlying transport."""
        ...

    @property
    def is_connected(self) -> bool:
        """Whether the underlying transport is still usable."""
        ...


@runtime_checkable
class TurnExecutorProtocol(Protocol):
    """Structural type for turn execution strategies.

    Concrete implementations live in :mod:`backend.services.turn`
    (``DirectTurnExecutor``, ``AgentTurnExecutor``).  ``turn`` and
    ``result`` are intentionally typed as :class:`Any` to avoid pulling
    the DTO definitions into this protocol layer (they would create an
    import cycle through the executors).
    """

    async def execute(
        self,
        turn: Any,
        sink: WSEventSinkProtocol,
        cancel_event: asyncio.Event,
        session: Any,
    ) -> Any:
        """Run a single turn and return a ``TurnResult``."""
        ...
