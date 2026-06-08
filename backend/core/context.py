"""AL\\CE — Application context (lightweight DI container).

The ``AppContext`` holds references to every shared service so they can be
injected where needed without relying on module-level globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from backend.core.config import AliceConfig
from backend.core.event_bus import EventBus
from backend.core.protocols import (
    ContextManagerProtocol,
    ConversationFileManagerProtocol,
    EmbeddingClientProtocol,
    EmailServiceProtocol,
    KnowledgeBackendProtocol,
    LLMServiceProtocol,
    LMStudioManagerProtocol,
    MemoryServiceProtocol,
    PluginManagerProtocol,
    PreferencesServiceProtocol,
    QdrantServiceProtocol,
    STTServiceProtocol,
    TTSServiceProtocol,
    ToolRegistryProtocol,
    VRAMMonitorProtocol,
    WSConnectionManagerProtocol,
)


@dataclass
class AppContext:
    """Typed container for all shared runtime services.

    Created once during application startup via :func:`create_context` and
    stored on ``app.state.context``.
    """

    config: AliceConfig
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

    model_registry: Any = None
    """Dynamic per-model capability registry."""

    preferences_service: PreferencesServiceProtocol | None = None
    """User preferences persistence service."""

    memory_service: MemoryServiceProtocol | None = None
    """Persistent semantic memory service."""

    knowledge_backend: KnowledgeBackendProtocol | None = None
    """Unified knowledge store (Phase 1).  Wraps the memory service behind
    a kind-dispatched protocol; ``note`` knowledge is delegated to
    Continuum via :class:`CompositeKnowledgeBackend` when enabled."""

    continuum_client: Any = None
    """Shared Continuum REST client (Phase 3).  Set when Continuum is the
    note backend so the notes backend and the ``continuum`` plugin drive
    one client instance — keeping a single, coherent folder path↔id cache
    (e.g. a folder created via the plugin is immediately resolvable when
    placing a note). ``None`` when Continuum is disabled."""

    email_service: EmailServiceProtocol | None = None
    """Async IMAP/SMTP email assistant service."""

    qdrant_service: QdrantServiceProtocol | None = None
    """Qdrant vector store service."""

    embedding_client: EmbeddingClientProtocol | None = None
    """Shared embedding client for all vector operations."""

    ws_connection_manager: WSConnectionManagerProtocol | None = None
    """Persistent event WebSocket connection manager."""

    context_manager: ContextManagerProtocol | None = None
    """Context window management and compression service."""

    plugin_state_repo: Any = None
    """Persistent plugin toggle-state repository."""

    config_service: Any = None
    """Layered configuration service (defaults/system/user/runtime).

    When non-None it is the canonical owner of the resolved
    :class:`AliceConfig`; ``ctx.config`` is updated by the service after
    every successful mutation so existing callers (``ctx.config.foo``)
    keep working unchanged.  See
    :class:`backend.services.config_service.LayeredConfigService`.
    """

    artifact_registry: Any = None
    """Unified registry for tool-generated artifacts (3D, images, audio, …)."""

    permission_service: Any = None
    """Central tool-permission authority (Fase 2, foundation D).

    Owns risk policy (forbidden), by-construction filesystem scope
    confinement and per-conversation grants for the turn engine's
    permission middleware. Typed as :class:`Any` to avoid a ``core`` →
    ``services`` import cycle (the concrete type lives in
    :mod:`backend.services.permission_service`). The workspace scope it
    confines against arrives in Fase 6; until then it imposes no new
    denials."""

    plan_service: Any = None
    """Persisted per-conversation plan store (Fase 5).

    Typed as :class:`Any` to avoid a ``core`` → ``services`` import cycle; the
    concrete type is :class:`backend.services.plan_service.PlanService`. Wired
    in the lifespan. Used by the ``agent`` plugin's ``update_plan`` and the
    turn engine's plan re-inject."""

    scope_service: Any = None
    """Per-conversation workspace folder scope (Fase 6).

    Typed as :class:`Any` to avoid a core→services import cycle; concrete type
    :class:`backend.services.scope_service.ScopeService`. Wired in the lifespan;
    its ``scope_roots`` is the ``PermissionService`` scope provider."""

    plugin_local_state: dict[str, dict] = field(default_factory=dict)
    """Per-plugin local state, keyed by plugin name."""

    orchestrator: Any = None
    """Centralized service lifecycle orchestrator (Phase 1 finalisation).

    Typed as :class:`Any` to avoid an import cycle with
    ``backend.core.service_orchestrator`` which itself imports from
    :mod:`backend.core.event_bus`.  Always a
    :class:`backend.core.service_orchestrator.ServiceOrchestrator` at
    runtime once the lifespan has initialised it.
    """

    model_downloader: Any = None
    """STT/TTS model downloader with progress events.

    Always a :class:`backend.services.model_downloader.ModelDownloader`
    at runtime; typed as :class:`Any` to avoid circular imports.
    """

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


def create_context(config: AliceConfig) -> AppContext:
    """Create a fresh application context.

    Args:
        config: The validated AL\\CE configuration.

    Returns:
        An ``AppContext`` wired with the config and a new ``EventBus``.
    """
    return AppContext(
        config=config,
        event_bus=EventBus(),
    )
