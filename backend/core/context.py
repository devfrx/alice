"""AL\\CE — Application context (thin root over cohesive service groups).

Fase 5 (spec §5.1): the canonical storage is the five service groups in
:mod:`backend.core.service_groups`; ``AppContext`` aggregates them and
keeps every legacy flat field name alive as a typed delegating property
(read AND write), so not-yet-migrated consumers — and the ~20 test
fixtures that construct ``AppContext(...)`` with flat kwargs — keep
working unchanged.  New code should prefer the group access
(``ctx.inference.llm_service``); the flat names are the transition API.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backend.core.config import AliceConfig
from backend.core.event_bus import EventBus
from backend.core.protocols import (
    ContextManagerProtocol,
    EmailServiceProtocol,
    EmbeddingClientProtocol,
    KnowledgeServiceProtocol,
    LLMServiceProtocol,
    LMStudioManagerProtocol,
    MemoryServiceProtocol,
    PlanDocumentServiceProtocol,
    PluginManagerProtocol,
    PreferencesServiceProtocol,
    QdrantServiceProtocol,
    STTServiceProtocol,
    ToolRegistryProtocol,
    TTSServiceProtocol,
    VRAMMonitorProtocol,
    WSConnectionManagerProtocol,
)
from backend.core.service_groups import (
    ConversationServices,
    InferenceServices,
    KnowledgeServices,
    PlatformServices,
    WorkspaceServices,
)

if TYPE_CHECKING:
    from backend.services.rag_readiness import RagReadiness


class AppContext:
    """Thin root aggregating the five cohesive service groups.

    Created once during application startup via :func:`create_context`
    and stored on ``app.state.context``.  Legacy flat field names are
    delegating properties over the groups (see module docstring).
    """

    #: Every legacy flat field name (delegating property) — used by the
    #: constructor kwargs guard and by tests.
    FLAT_FIELDS: tuple[str, ...] = (
        "db", "engine",
        "plugin_manager", "tool_registry", "llm_service", "stt_service",
        "tts_service", "lmstudio_manager", "vram_monitor", "model_registry",
        "preferences_service", "memory_service", "knowledge_service",
        "continuum_client", "email_service", "qdrant_service",
        "embedding_client", "rag_readiness", "ws_connection_manager",
        "context_manager", "plugin_state_repo", "config_service",
        "artifact_registry", "permission_service", "plan_service",
        "plan_document_service", "scope_service", "permission_mode_service",
        "permission_rule_service", "terminal_session_manager",
        "plugin_local_state", "orchestrator", "model_downloader",
        "event_bus",
    )

    def __init__(
        self,
        config: AliceConfig,
        event_bus: EventBus | None = None,
        **services: Any,
    ) -> None:
        self.config = config
        self.inference = InferenceServices()
        self.knowledge = KnowledgeServices()
        self.workspace = WorkspaceServices()
        self.conversation = ConversationServices()
        self.platform = PlatformServices(event_bus=event_bus or EventBus())
        for name, value in services.items():
            if name not in self.FLAT_FIELDS:
                raise TypeError(
                    f"AppContext got an unexpected field {name!r}"
                )
            setattr(self, name, value)

    # ------------------------------------------------------------------
    # Inference group
    # ------------------------------------------------------------------

    @property
    def llm_service(self) -> LLMServiceProtocol | None:
        return self.inference.llm_service

    @llm_service.setter
    def llm_service(self, value: LLMServiceProtocol | None) -> None:
        self.inference.llm_service = value

    @property
    def stt_service(self) -> STTServiceProtocol | None:
        return self.inference.stt_service

    @stt_service.setter
    def stt_service(self, value: STTServiceProtocol | None) -> None:
        self.inference.stt_service = value

    @property
    def tts_service(self) -> TTSServiceProtocol | None:
        return self.inference.tts_service

    @tts_service.setter
    def tts_service(self, value: TTSServiceProtocol | None) -> None:
        self.inference.tts_service = value

    @property
    def lmstudio_manager(self) -> LMStudioManagerProtocol | None:
        return self.inference.lmstudio_manager

    @lmstudio_manager.setter
    def lmstudio_manager(self, value: LMStudioManagerProtocol | None) -> None:
        self.inference.lmstudio_manager = value

    @property
    def vram_monitor(self) -> VRAMMonitorProtocol | None:
        return self.inference.vram_monitor

    @vram_monitor.setter
    def vram_monitor(self, value: VRAMMonitorProtocol | None) -> None:
        self.inference.vram_monitor = value

    @property
    def model_registry(self) -> Any:
        return self.inference.model_registry

    @model_registry.setter
    def model_registry(self, value: Any) -> None:
        self.inference.model_registry = value

    @property
    def model_downloader(self) -> Any:
        return self.inference.model_downloader

    @model_downloader.setter
    def model_downloader(self, value: Any) -> None:
        self.inference.model_downloader = value

    @property
    def embedding_client(self) -> EmbeddingClientProtocol | None:
        return self.inference.embedding_client

    @embedding_client.setter
    def embedding_client(self, value: EmbeddingClientProtocol | None) -> None:
        self.inference.embedding_client = value

    # ------------------------------------------------------------------
    # Knowledge group
    # ------------------------------------------------------------------

    @property
    def knowledge_service(self) -> KnowledgeServiceProtocol | None:
        return self.knowledge.knowledge_service

    @knowledge_service.setter
    def knowledge_service(self, value: KnowledgeServiceProtocol | None) -> None:
        self.knowledge.knowledge_service = value

    @property
    def memory_service(self) -> MemoryServiceProtocol | None:
        return self.knowledge.memory_service

    @memory_service.setter
    def memory_service(self, value: MemoryServiceProtocol | None) -> None:
        self.knowledge.memory_service = value

    @property
    def qdrant_service(self) -> QdrantServiceProtocol | None:
        return self.knowledge.qdrant_service

    @qdrant_service.setter
    def qdrant_service(self, value: QdrantServiceProtocol | None) -> None:
        self.knowledge.qdrant_service = value

    @property
    def continuum_client(self) -> Any:
        return self.knowledge.continuum_client

    @continuum_client.setter
    def continuum_client(self, value: Any) -> None:
        self.knowledge.continuum_client = value

    @property
    def rag_readiness(self) -> RagReadiness | None:
        return self.knowledge.rag_readiness

    @rag_readiness.setter
    def rag_readiness(self, value: RagReadiness | None) -> None:
        self.knowledge.rag_readiness = value

    # ------------------------------------------------------------------
    # Workspace group
    # ------------------------------------------------------------------

    @property
    def scope_service(self) -> Any:
        return self.workspace.scope_service

    @scope_service.setter
    def scope_service(self, value: Any) -> None:
        self.workspace.scope_service = value

    @property
    def permission_service(self) -> Any:
        return self.workspace.permission_service

    @permission_service.setter
    def permission_service(self, value: Any) -> None:
        self.workspace.permission_service = value

    @property
    def permission_mode_service(self) -> Any:
        return self.workspace.permission_mode_service

    @permission_mode_service.setter
    def permission_mode_service(self, value: Any) -> None:
        self.workspace.permission_mode_service = value

    @property
    def permission_rule_service(self) -> Any:
        return self.workspace.permission_rule_service

    @permission_rule_service.setter
    def permission_rule_service(self, value: Any) -> None:
        self.workspace.permission_rule_service = value

    @property
    def terminal_session_manager(self) -> Any:
        return self.workspace.terminal_session_manager

    @terminal_session_manager.setter
    def terminal_session_manager(self, value: Any) -> None:
        self.workspace.terminal_session_manager = value

    # ------------------------------------------------------------------
    # Conversation group
    # ------------------------------------------------------------------

    @property
    def db(self) -> async_sessionmaker[AsyncSession] | None:
        return self.conversation.db

    @db.setter
    def db(self, value: async_sessionmaker[AsyncSession] | None) -> None:
        self.conversation.db = value

    @property
    def engine(self) -> AsyncEngine | None:
        return self.conversation.engine

    @engine.setter
    def engine(self, value: AsyncEngine | None) -> None:
        self.conversation.engine = value

    @property
    def context_manager(self) -> ContextManagerProtocol | None:
        return self.conversation.context_manager

    @context_manager.setter
    def context_manager(self, value: ContextManagerProtocol | None) -> None:
        self.conversation.context_manager = value

    @property
    def plan_service(self) -> Any:
        return self.conversation.plan_service

    @plan_service.setter
    def plan_service(self, value: Any) -> None:
        self.conversation.plan_service = value

    @property
    def plan_document_service(self) -> PlanDocumentServiceProtocol | None:
        return self.conversation.plan_document_service

    @plan_document_service.setter
    def plan_document_service(
        self, value: PlanDocumentServiceProtocol | None,
    ) -> None:
        self.conversation.plan_document_service = value

    @property
    def artifact_registry(self) -> Any:
        return self.conversation.artifact_registry

    @artifact_registry.setter
    def artifact_registry(self, value: Any) -> None:
        self.conversation.artifact_registry = value

    # ------------------------------------------------------------------
    # Platform group
    # ------------------------------------------------------------------

    @property
    def event_bus(self) -> EventBus:
        return self.platform.event_bus

    @event_bus.setter
    def event_bus(self, value: EventBus) -> None:
        self.platform.event_bus = value

    @property
    def config_service(self) -> Any:
        return self.platform.config_service

    @config_service.setter
    def config_service(self, value: Any) -> None:
        self.platform.config_service = value

    @property
    def ws_connection_manager(self) -> WSConnectionManagerProtocol | None:
        return self.platform.ws_connection_manager

    @ws_connection_manager.setter
    def ws_connection_manager(
        self, value: WSConnectionManagerProtocol | None,
    ) -> None:
        self.platform.ws_connection_manager = value

    @property
    def plugin_manager(self) -> PluginManagerProtocol | None:
        return self.platform.plugin_manager

    @plugin_manager.setter
    def plugin_manager(self, value: PluginManagerProtocol | None) -> None:
        self.platform.plugin_manager = value

    @property
    def tool_registry(self) -> ToolRegistryProtocol | None:
        return self.platform.tool_registry

    @tool_registry.setter
    def tool_registry(self, value: ToolRegistryProtocol | None) -> None:
        self.platform.tool_registry = value

    @property
    def orchestrator(self) -> Any:
        return self.platform.orchestrator

    @orchestrator.setter
    def orchestrator(self, value: Any) -> None:
        self.platform.orchestrator = value

    @property
    def plugin_state_repo(self) -> Any:
        return self.platform.plugin_state_repo

    @plugin_state_repo.setter
    def plugin_state_repo(self, value: Any) -> None:
        self.platform.plugin_state_repo = value

    @property
    def preferences_service(self) -> PreferencesServiceProtocol | None:
        return self.platform.preferences_service

    @preferences_service.setter
    def preferences_service(
        self, value: PreferencesServiceProtocol | None,
    ) -> None:
        self.platform.preferences_service = value

    @property
    def email_service(self) -> EmailServiceProtocol | None:
        return self.platform.email_service

    @email_service.setter
    def email_service(self, value: EmailServiceProtocol | None) -> None:
        self.platform.email_service = value

    @property
    def plugin_local_state(self) -> dict[str, dict[str, Any]]:
        return self.platform.plugin_local_state

    @plugin_local_state.setter
    def plugin_local_state(self, value: dict[str, dict[str, Any]]) -> None:
        self.platform.plugin_local_state = value

    # ------------------------------------------------------------------
    # Plugin state helpers
    # ------------------------------------------------------------------

    def get_plugin_state(self, name: str) -> MappingProxyType[str, Any]:
        """Return a read-only view of a plugin's local state.

        Args:
            name: The plugin name.

        Returns:
            A ``MappingProxyType`` wrapping the plugin's state dict.
            Returns an empty read-only mapping if no state exists.
        """
        return MappingProxyType(self.platform.plugin_local_state.get(name, {}))

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
        state = self.platform.plugin_local_state
        if plugin_name not in state:
            state[plugin_name] = {}
        state[plugin_name][key] = value


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
