"""AL\\CE — Cohesive service groups of the application context (Fase 5).

Spec §5.1: the flat 35-field ``AppContext`` is decomposed into five
cohesive, protocol-typed groups.  The groups are the CANONICAL storage;
:class:`backend.core.context.AppContext` stays as a thin root that
aggregates them and exposes flat delegating properties for
not-yet-migrated consumers.

Group membership models OWNERSHIP; the bootstrap stage a field is
created in models INIT ORDER — the two intentionally differ for a few
fields (e.g. ``context_manager`` is conversation-owned but built in the
inference stage).

Fields typed ``Any`` mirror the pre-existing flat fields: the concrete
class lives in ``backend.services`` and typing it here would create a
``core`` → ``services`` import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

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
    SecretStoreProtocol,
    STTServiceProtocol,
    ToolRegistryProtocol,
    TTSServiceProtocol,
    VRAMMonitorProtocol,
    WSConnectionManagerProtocol,
)

if TYPE_CHECKING:
    from backend.services.rag_readiness import RagReadiness


@dataclass
class InferenceServices:
    """Model inference: LLM, voice models, embeddings, model management."""

    llm_service: LLMServiceProtocol | None = None
    stt_service: STTServiceProtocol | None = None
    tts_service: TTSServiceProtocol | None = None
    lmstudio_manager: LMStudioManagerProtocol | None = None
    vram_monitor: VRAMMonitorProtocol | None = None
    model_registry: Any = None
    """Dynamic per-model capability registry."""
    model_downloader: Any = None
    """STT/TTS model downloader with progress events."""
    openrouter_service: Any = None
    """OpenRouter catalog/credits service (always constructed, cheap)."""
    embedding_client: EmbeddingClientProtocol | None = None
    """Shared embedding client for all vector operations."""


@dataclass
class KnowledgeServices:
    """Knowledge domain: single-entry service + its wiring internals.

    ``knowledge_service`` is the ONLY consumer-facing entry point (Fase 4);
    the other fields are wiring/readiness/shutdown internals.  The runtime
    repair path (:func:`backend.services.knowledge_init.repair_vector_store`)
    replaces this WHOLE group atomically (Fase 5, Task 3)."""

    knowledge_service: KnowledgeServiceProtocol | None = None
    memory_service: MemoryServiceProtocol | None = None
    qdrant_service: QdrantServiceProtocol | None = None
    continuum_client: Any = None
    """The ONE shared Continuum REST client (``None`` when disabled)."""
    rag_readiness: RagReadiness | None = None
    """All-or-nothing RAG readiness verdict (``None`` until computed)."""


@dataclass
class WorkspaceServices:
    """Workspace confinement: scope, permission tiers/rules, terminal."""

    scope_service: Any = None
    permission_service: Any = None
    """Central tool-permission authority consulted by the turn engine."""
    permission_mode_service: Any = None
    permission_rule_service: Any = None
    terminal_session_manager: Any = None
    command_bridge_service: Any = None
    """Command Bridge (spec §7): manifest + events-WS RPC for app_command."""


@dataclass
class ConversationServices:
    """Conversation persistence and per-conversation artefacts."""

    db: async_sessionmaker[SQLModelAsyncSession] | None = None
    """Session factory — SQLModel-aware sessions (``db/database.py``)."""
    engine: AsyncEngine | None = None
    context_manager: ContextManagerProtocol | None = None
    plan_service: Any = None
    plan_document_service: PlanDocumentServiceProtocol | None = None
    artifact_registry: Any = None


@dataclass
class PlatformServices:
    """Cross-cutting platform machinery: events, config, plugins, WS."""

    event_bus: EventBus = field(default_factory=EventBus)
    config_service: Any = None
    """Layered configuration service — canonical owner of the resolved
    ``AliceConfig`` (``ctx.config`` is updated after every mutation)."""
    ws_connection_manager: WSConnectionManagerProtocol | None = None
    plugin_manager: PluginManagerProtocol | None = None
    tool_registry: ToolRegistryProtocol | None = None
    orchestrator: Any = None
    plugin_state_repo: Any = None
    preferences_service: PreferencesServiceProtocol | None = None
    email_service: EmailServiceProtocol | None = None
    plugin_local_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Per-plugin local state, keyed by plugin name."""
    background_task_service: Any = None
    """Observable background-task registry (Fase 8, spec §8)."""
    attention_service: Any = None
    """Single decision point for agent-initiated user attention (Fase 8)."""
    trigger_service: Any = None
    """Autonomous-turn trigger sources: schedule/event/manual (Fase 8)."""
    secret_store: SecretStoreProtocol | None = None
    """OS-keyring-backed secret storage (synchronous cache for config
    hydration; see :class:`backend.services.config_service.LayeredConfigService`)."""
