"""O.M.N.I.A. — Application context (lightweight DI container).

The ``AppContext`` holds references to every shared service so they can be
injected where needed without relying on module-level globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.core.config import OmniaConfig
from backend.core.event_bus import EventBus
from backend.core.protocols import (
    ConversationFileManagerProtocol,
    LLMServiceProtocol,
    LMStudioManagerProtocol,
    MemoryServiceProtocol,
    PluginManagerProtocol,
    PreferencesServiceProtocol,
    STTServiceProtocol,
    TTSServiceProtocol,
    ToolRegistryProtocol,
    VRAMMonitorProtocol,
)


@dataclass
class AppContext:
    """Typed container for all shared runtime services.

    Created once during application startup via :func:`create_context` and
    stored on ``app.state.context``.
    """

    config: OmniaConfig
    event_bus: EventBus
    db: async_sessionmaker | None = None
    engine: AsyncEngine | None = None

    plugin_manager: PluginManagerProtocol | None = None
    tool_registry: ToolRegistryProtocol | None = None
    llm_service: LLMServiceProtocol | None = None
    stt_service: STTServiceProtocol | None = None
    tts_service: TTSServiceProtocol | None = None
    conversation_file_manager: ConversationFileManagerProtocol | None = None
    lmstudio_manager: LMStudioManagerProtocol | None = None
    vram_monitor: VRAMMonitorProtocol | None = None

    preferences_service: PreferencesServiceProtocol | None = None
    """User preferences persistence service."""

    memory_service: MemoryServiceProtocol | None = None
    """Persistent semantic memory service."""

    plugin_local_state: dict[str, dict] = field(default_factory=dict)
    """Per-plugin local state, keyed by plugin name."""

    # ------------------------------------------------------------------
    # Plugin state helpers
    # ------------------------------------------------------------------

    def get_plugin_state(self, name: str) -> MappingProxyType:
        """Return a read-only view of a plugin's local state.

        Args:
            name: The plugin name.

        Returns:
            A ``MappingProxyType`` wrapping the plugin's state dict.
            Returns an empty read-only mapping if no state exists.
        """
        return MappingProxyType(self.plugin_local_state.get(name, {}))

    async def set_plugin_state(
        self, plugin_name: str, key: str, value: Any,
    ) -> None:
        """Update a single key in a plugin's local state.

        Creates the plugin's state dict if it doesn't exist yet.

        Args:
            plugin_name: The plugin whose state to update.
            key: The state key to set.
            value: The new value.
        """
        if plugin_name not in self.plugin_local_state:
            self.plugin_local_state[plugin_name] = {}
        self.plugin_local_state[plugin_name][key] = value


def create_context(config: OmniaConfig) -> AppContext:
    """Create a fresh application context.

    Args:
        config: The validated OMNIA configuration.

    Returns:
        An ``AppContext`` wired with the config and a new ``EventBus``.
    """
    return AppContext(
        config=config,
        event_bus=EventBus(),
    )
