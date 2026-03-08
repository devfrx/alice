"""O.M.N.I.A. — Service protocols (structural typing for DI).

Defines :class:`~typing.Protocol` classes that describe the public API
expected from each pluggable service.  ``AppContext`` references these
protocols instead of ``Any``, giving static type-checkers something
useful to verify without creating hard import cycles.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


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
        cancel_event: asyncio.Event | None = None,
        *,
        user_content: str | None = None,
        conversation_id: str | None = None,
        attachments: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion, yielding event dicts."""
        ...

    async def close(self) -> None:
        """Release the underlying HTTP client."""
        ...


# ---------------------------------------------------------------------------
# STT / TTS
# ---------------------------------------------------------------------------


class TranscriptionResult(Protocol):
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
    ) -> TranscriptionResult:
        """Transcribe audio bytes, returning a TranscriptionResult."""
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
    async def check_health(self) -> dict[str, Any]: ...
    async def load_plugin(self, name: str) -> bool: ...
    async def unload_plugin(self, name: str) -> bool: ...
    async def reload_plugin(self, name: str) -> bool: ...
    def get_plugin(self, name: str) -> Any: ...
    def get_all_plugins(self) -> dict[str, Any]: ...
    def get_loaded_plugin_names(self) -> list[str]: ...
    def discover_available_plugins(self) -> dict[str, Any]: ...
    async def get_all_status(self) -> dict[str, Any]: ...


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

    async def load_all(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Read all conversation JSON files."""
        ...


# ---------------------------------------------------------------------------
# Conversation DB sync
# ---------------------------------------------------------------------------


@runtime_checkable
class ConversationDBSyncProtocol(Protocol):
    """Protocol for rebuilding database from conversation files."""

    async def rebuild_from_files(self, session_factory: Any) -> int:
        """Rebuild the database from saved JSON files."""
        ...
