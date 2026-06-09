"""AL\\CE — FastAPI application factory."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.core.config import AliceConfig, PROJECT_ROOT, load_config
from backend.core.context import AppContext, create_context
from backend.core.event_bus import AliceEvent
from backend.core.service_orchestrator import ServiceOrchestrator
from backend.core.managed_services import (
    LMStudioManagedService,
    STTManagedService,
    TTSManagedService,
    TrellisManagedService,
    VRAMManagedService,
    resolve_trellis_launcher,
)
from backend.db.database import create_engine_and_session, init_db
from backend.services.conversation_file_manager import ConversationFileManager
from backend.services.llm_service import LLMService
from backend.services.lmstudio_service import LMStudioManager
from backend.services.model_capability_registry import ModelCapabilityRegistry
from backend.services.stt_service import STTService
from backend.services.tts_service import TTSService
from backend.services.vram_monitor import VRAMMonitor
from backend.core.plugin_manager import PluginManager
from backend.core.tool_registry import ToolRegistry
from backend.api.middleware.exception_handler import UnhandledExceptionMiddleware
from backend.api.middleware.origin_guard import OriginGuardMiddleware
from backend.api.middleware.rate_limit import setup_rate_limiting

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup / shutdown of the AL\\CE backend."""
    # -- Startup ------------------------------------------------------------
    config: AliceConfig = app.state._config  # set by create_app
    testing: bool = app.state._testing

    # Pre-bind every resource referenced from the ``finally`` block so a
    # startup failure before they are constructed cannot raise
    # ``UnboundLocalError`` and mask the original exception.
    engine = None
    plugin_manager = None
    lmstudio_manager = None
    llm_service = None
    ctx: AppContext | None = None

    if testing:
        db_url = "sqlite+aiosqlite://"  # in-memory
    else:
        db_url = config.database.url
        # Ensure the directory for the SQLite file exists.
        if "sqlite" in db_url and ":///" in db_url:
            db_path = db_url.split(":///", 1)[-1]
            if db_path:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine, session_factory = create_engine_and_session(db_url)
    await init_db(engine)

    ctx = create_context(config)
    ctx.db = session_factory  # type: ignore[assignment]
    ctx.engine = engine

    # -- Service orchestrator ----------------------------------------------
    # Created early so concrete service constructors below can attach
    # themselves as they are instantiated.  Concrete services are still
    # started inline (legacy path); the orchestrator only owns health
    # polling, restarts, and the WS ``service.status`` event stream.
    orchestrator = ServiceOrchestrator(ctx.event_bus)
    ctx.orchestrator = orchestrator

    # -- Layered configuration service (defaults/system/user/runtime) -------
    # Built early so any subsequent service can read merged config through
    # ``ctx.config`` exactly as before.  The service rebuilds ``ctx.config``
    # whenever a layer mutation succeeds.
    from backend.services.config_service import LayeredConfigService

    config_service = LayeredConfigService(event_bus=ctx.event_bus)
    ctx.config_service = config_service
    ctx.config = config_service.get_resolved()
    config = ctx.config  # keep local alias in sync for the rest of lifespan

    async def _refresh_ctx_config(**_kwargs: object) -> None:
        ctx.config = config_service.get_resolved()
        # A config change may switch the active model, which changes the
        # context window; drop the cached value so the next probe refreshes it.
        if getattr(ctx, "llm_service", None) is not None:
            ctx.llm_service.invalidate_context_window_cache()

    ctx.event_bus.subscribe("config.changed", _refresh_ctx_config)

    # -- Model downloader (STT/TTS) ----------------------------------------
    # Provides idempotent + resumable downloads of Whisper / Piper models
    # with progress events forwarded to the events WebSocket.
    from backend.services.model_downloader import ModelDownloader, PROGRESS_EVENT

    # In a PyInstaller --onedir bundle ``__file__`` lives inside ``_internal/``
    # which is read-only on Windows by user expectation; we keep models next to
    # ``backend.exe`` so the in-app downloader can write to them and bundled
    # defaults staged by ``build-installer.ps1`` are picked up automatically.
    if getattr(sys, "frozen", False):
        models_root = Path(sys.executable).resolve().parent / "models"
    else:
        models_root = PROJECT_ROOT / "models"
    models_root.mkdir(parents=True, exist_ok=True)
    ctx.model_downloader = ModelDownloader(models_root, ctx.event_bus)

    async def _forward_download_progress(**kwargs: object) -> None:
        if ctx.ws_connection_manager is None:
            return
        await ctx.ws_connection_manager.broadcast({
            "type": PROGRESS_EVENT,
            **kwargs,
        })

    ctx.event_bus.subscribe(PROGRESS_EVENT, _forward_download_progress)

    # -- Load persisted user preferences ------------------------------------
    from backend.services.preferences_service import PreferencesService

    preferences_service = PreferencesService(session_factory)
    ctx.preferences_service = preferences_service

    if not testing:
        try:
            prefs = await preferences_service.load_all()
            preferences_service.apply_to_config(config, prefs)
        except Exception as exc:
            logger.warning("Failed to load persisted preferences: {}", exc)

    # -- Restore persisted plugin toggle states -----------------------------
    from backend.db.plugin_state import PluginStateRepository

    plugin_state_repo = PluginStateRepository(session_factory)
    ctx.plugin_state_repo = plugin_state_repo

    if not testing:
        try:
            # On first run: seed DB from default.yaml list.
            await plugin_state_repo.initialize_defaults(
                config.plugins.enabled
            )
            # Replace in-memory list with the persisted user choices.
            persisted = await plugin_state_repo.get_all()
            config.plugins.enabled = [
                name for name, enabled in persisted.items() if enabled
            ]
            logger.debug(
                "Plugin states restored from DB: enabled={}",
                config.plugins.enabled,
            )
        except Exception as exc:
            logger.warning("Failed to restore plugin states: {}", exc)

    # -- Model capability registry ------------------------------------------
    model_registry = ModelCapabilityRegistry()
    ctx.model_registry = model_registry

    llm_service = LLMService(config.llm, model_registry=model_registry)
    ctx.llm_service = llm_service

    from backend.services.context_manager import ContextManager
    ctx.context_manager = ContextManager(config.llm)

    # Validate system prompt file exists at startup.
    prompt_path = Path(config.llm.system_prompt_file)
    if not prompt_path.exists():
        logger.warning(
            "System prompt file not found: {} — LLM will use no system prompt",
            prompt_path,
        )

    lmstudio_manager = LMStudioManager(
        base_url=config.llm.base_url,
        api_token=config.llm.api_token,
    )
    ctx.lmstudio_manager = lmstudio_manager

    # Drop the cached LLM context window whenever the loaded-model set changes
    # (load/unload paths call invalidate_models_cache), so the next probe
    # re-reads the window for the now-active model.
    lmstudio_manager.add_models_changed_listener(
        llm_service.invalidate_context_window_cache
    )

    # Register LM Studio with the orchestrator (health-only, never auto-start).
    try:
        await orchestrator.attach_started(
            LMStudioManagedService(lmstudio_manager),
        )
    except Exception as exc:
        logger.warning("Orchestrator: failed to attach LM Studio: {}", exc)

    conversations_dir = PROJECT_ROOT / "data" / "conversations"
    ctx.conversation_file_manager = ConversationFileManager(conversations_dir)

    # Restore conversations from JSON files that are missing from the DB.
    if not testing:
        try:
            restored = await ctx.conversation_file_manager.rebuild_from_files(
                session_factory,
            )
            if restored:
                logger.info("Restored {} conversations from JSON files", restored)
        except Exception as exc:
            logger.error("Failed to rebuild conversations from files: {}", exc)

    # -- Embedding client + Qdrant service (shared) -------------------------
    from backend.services.embedding_client import EmbeddingClient
    from backend.services.qdrant_service import QdrantService

    embedding_client = EmbeddingClient(
        base_url=config.llm.base_url,
        model=config.qdrant.embedding_model,
        dimensions=config.qdrant.embedding_dim,
        fallback_enabled=config.qdrant.embedding_fallback,
    )
    # Probe actual dims so ensure_collection uses the real vector size,
    # not the potentially stale config value.
    try:
        actual_dim = await embedding_client.probe_dimensions()
        logger.info("Embedding dimensions probed: {}", actual_dim)
    except Exception as exc:
        logger.warning(
            "Embedding dimension probe failed: {} — using configured dim ({})",
            exc,
            config.qdrant.embedding_dim,
        )
    ctx.embedding_client = embedding_client

    qdrant_service = QdrantService(config.qdrant)
    try:
        await qdrant_service.initialize()
        ctx.qdrant_service = qdrant_service
        logger.info("Qdrant service started (mode={})", config.qdrant.mode)
    except Exception as exc:
        logger.warning("Qdrant service failed to start: {}", exc)
        try:
            await qdrant_service.close()
        except Exception:
            pass
        qdrant_service = None

    # -- Memory service (Phase 9) ------------------------------------------
    if config.memory.enabled and qdrant_service:
        from backend.services.memory_service import MemoryService

        memory_service = MemoryService(
            config.memory, qdrant_service, embedding_client,
            embedding_model=config.qdrant.embedding_model,
        )
        try:
            await memory_service.initialize()
            ctx.memory_service = memory_service
            logger.info("Memory service started")
        except Exception as exc:
            logger.warning("Memory service failed to start: {}", exc)
            await memory_service.close()

    # -- Knowledge backend (Phase 1, Stream A) -----------------------------
    # Thin :class:`KnowledgeBackend` adapter wrapping the existing memory
    # service.  Plugins (memory) consume this backend instead of the
    # underlying service directly. ``note`` knowledge is served by
    # Continuum (below); Qdrant only handles ``memory``/``fact``.
    from backend.services.knowledge import QdrantBackend

    qdrant_backend = QdrantBackend(
        memory_service=ctx.memory_service,
    )

    # -- Continuum knowledge backend (Phase 3) -----------------------------
    # When Continuum is enabled, ``note`` knowledge is delegated to the
    # external Continuum server while ``memory``/``fact`` stay on Qdrant.
    # The two are composed behind the single KnowledgeBackend interface so
    # plugin code is unaffected.
    if config.continuum.enabled:
        from backend.services.knowledge import (
            CompositeKnowledgeBackend,
            ContinuumBackend,
            ContinuumClient,
        )

        continuum_client = ContinuumClient(
            base_url=config.continuum.base_url,
            api_token=config.continuum.api_token,
            timeout_s=config.continuum.timeout_s,
            folder_cache_ttl_s=config.continuum.folder_cache_ttl_s,
        )
        ctx.knowledge_backend = CompositeKnowledgeBackend(
            note_backend=ContinuumBackend(client=continuum_client),
            memory_backend=qdrant_backend,
        )
        # Expose the same client so the ``continuum`` plugin reuses it
        # instead of building a second one — a single instance keeps the
        # folder path↔id cache coherent across note placement and plugin
        # folder mutations.
        ctx.continuum_client = continuum_client
        logger.info(
            "Knowledge backend wired (notes=continuum @ {}, memory=qdrant)",
            config.continuum.base_url,
        )
    else:
        ctx.knowledge_backend = qdrant_backend
        logger.info(
            "Knowledge backend wired (memory={}, notes=disabled)",
            ctx.memory_service is not None,
        )

    # -- Email service (Phase 15) ------------------------------------------
    if config.email.enabled:
        from backend.services.email_service import EmailService

        email_service = EmailService(config.email, ctx.event_bus)
        try:
            await email_service.initialize()
            ctx.email_service = email_service
            logger.info("Email service started ({})", config.email.username)
        except Exception as exc:
            logger.warning("Email service failed to start: {}", exc)
            await email_service.close()

    # -- Voice services (Phase 4) ------------------------------------------
    if config.stt.enabled:
        try:
            stt_service = STTService(config.stt)
            try:
                await asyncio.wait_for(stt_service.start(), timeout=120)
            except asyncio.TimeoutError:
                logger.warning(
                    "STT model pre-load timed out — will lazy-load on first use",
                )
            ctx.stt_service = stt_service
            logger.info("STT service started (engine={})", config.stt.engine)
        except Exception as exc:
            logger.warning("STT service failed to start: {}", exc)

    if ctx.stt_service is not None:
        try:
            await orchestrator.attach_started(
                STTManagedService(ctx.stt_service),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach STT: {}", exc)

    if config.tts.enabled:
        try:
            tts_service = TTSService(config.tts)
            await tts_service.start()
            ctx.tts_service = tts_service
            logger.info("TTS service started (engine={})", config.tts.engine)
        except Exception as exc:
            logger.warning("TTS service failed to start: {}", exc)

    if ctx.tts_service is not None:
        try:
            await orchestrator.attach_started(
                TTSManagedService(ctx.tts_service),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach TTS: {}", exc)

    if config.vram.monitoring_enabled:
        try:
            vram_monitor = VRAMMonitor(
                ctx.event_bus,
                poll_interval=config.vram.poll_interval_s,
                warning_mb=config.vram.warning_threshold_mb,
                critical_mb=config.vram.critical_threshold_mb,
            )
            await vram_monitor.start()
            ctx.vram_monitor = vram_monitor
            logger.info("VRAM monitor started")
        except Exception as exc:
            logger.warning("VRAM monitor failed to start: {}", exc)

    if ctx.vram_monitor is not None:
        try:
            await orchestrator.attach_started(
                VRAMManagedService(ctx.vram_monitor),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach VRAM monitor: {}", exc)

    # -- TRELLIS external process (health-only, user-managed) --------------
    if getattr(config, "trellis", None) and config.trellis.enabled:
        try:
            launcher, cwd = resolve_trellis_launcher("trellis")
            await orchestrator.attach_started(
                TrellisManagedService(
                    name="trellis",
                    service_url=config.trellis.service_url,
                    launcher=launcher,
                    cwd=cwd,
                    model=config.trellis.trellis_model,
                    trellis_dir=config.trellis.trellis_dir,
                ),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach TRELLIS: {}", exc)
    if getattr(config, "trellis2", None) and config.trellis2.enabled:
        try:
            launcher, cwd = resolve_trellis_launcher("trellis2")
            await orchestrator.attach_started(
                TrellisManagedService(
                    name="trellis2",
                    service_url=config.trellis2.service_url,
                    launcher=launcher,
                    cwd=cwd,
                    model=config.trellis2.trellis2_model,
                    trellis_dir=config.trellis2.trellis2_dir,
                ),
            )
        except Exception as exc:
            logger.warning("Orchestrator: failed to attach TRELLIS.2: {}", exc)
    if (
        getattr(config, "trellis2multiview", None)
        and config.trellis2multiview.enabled
    ):
        try:
            launcher, cwd = resolve_trellis_launcher("trellis2multiview")
            await orchestrator.attach_started(
                TrellisManagedService(
                    name="trellis2multiview",
                    service_url=config.trellis2multiview.service_url,
                    launcher=launcher,
                    cwd=cwd,
                    model=config.trellis2multiview.trellis2multiview_model,
                    trellis_dir=config.trellis2multiview.trellis2multiview_dir,
                ),
            )
        except Exception as exc:
            logger.warning(
                "Orchestrator: failed to attach TRELLIS.2 multi-view: {}", exc,
            )

    # -- VRAM event handlers ------------------------------------------------
    # These handlers ONLY log VRAM pressure.  Mutating ``stt_cfg`` /
    # ``tts_cfg`` here would not actually downgrade the running services
    # (they cache their own config snapshot at start()), so we deliberately
    # avoid touching live config to prevent misleading "we mitigated"
    # signals.  Real mitigation (restart STT/TTS with new settings) lives
    # in the settings/config REST handlers and must be triggered explicitly
    # by the user or a future orchestrator.
    if ctx.vram_monitor:
        async def _handle_vram_warning(**kwargs):
            usage = kwargs.get("usage")
            if usage:
                logger.warning(
                    "VRAM warning: {}MB used / {}MB total",
                    usage.used_mb, usage.total_mb,
                )

        async def _handle_vram_critical(**kwargs):
            usage = kwargs.get("usage")
            if usage:
                logger.error(
                    "VRAM critical: {}MB used / {}MB total",
                    usage.used_mb, usage.total_mb,
                )

        ctx.event_bus.subscribe(AliceEvent.VRAM_WARNING, _handle_vram_warning)
        ctx.event_bus.subscribe(AliceEvent.VRAM_CRITICAL, _handle_vram_critical)

    # -- Plugin system ------------------------------------------------------
    plugin_manager = PluginManager(ctx)
    ctx.plugin_manager = plugin_manager
    app.state.healthy = True
    try:
        await plugin_manager.startup()
    except Exception as exc:
        logger.error("Plugin system startup failed: {}", exc)
        app.state.healthy = False

    # -- Tool registry ------------------------------------------------------
    tool_registry = ToolRegistry(
        plugin_manager=plugin_manager,
        event_bus=ctx.event_bus,
        qdrant_service=ctx.qdrant_service,
        embedding_client=ctx.embedding_client,
        llm_config=config.llm,
    )
    try:
        await tool_registry.refresh()
    except Exception as exc:
        logger.error("Tool registry refresh failed: {}", exc)
    ctx.tool_registry = tool_registry

    # -- All-or-nothing RAG readiness gate (functionality-fixes #3) ---------
    # Runs after memory/qdrant/tool-registry init AND tool-embedding refresh,
    # so the verdict reflects the fully-wired stack. Disables memory + tool-RAG
    # entirely (in chat assembly) rather than running degraded. Never raises.
    from backend.services.rag_readiness import check_rag_readiness

    ctx.rag_readiness = await check_rag_readiness(ctx)
    if not ctx.rag_readiness.ready:
        logger.warning("Knowledge/RAG disabled: {}", ctx.rag_readiness.reason)
    with suppress(Exception):
        await ctx.event_bus.emit(
            "knowledge.status",
            ready=ctx.rag_readiness.ready,
            reason=ctx.rag_readiness.reason,
            memory_enabled=ctx.rag_readiness.memory_enabled,
            tool_rag_enabled=ctx.rag_readiness.tool_rag_enabled,
        )

    # -- WebSocket connection manager (Phase 10) ----------------------------
    from backend.services.ws_connection_manager import WSConnectionManager

    ws_connection_manager = WSConnectionManager()
    ctx.ws_connection_manager = ws_connection_manager

    # -- Bridge MCP events to the events WebSocket ----------------------
    async def _forward_mcp_connected(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "mcp.server.connected",
                "server": kwargs.get("server"),
            })

    async def _forward_mcp_disconnected(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "mcp.server.disconnected",
                "server": kwargs.get("server"),
                "reason": kwargs.get("reason"),
            })

    ctx.event_bus.subscribe(
        AliceEvent.MCP_SERVER_CONNECTED, _forward_mcp_connected,
    )
    ctx.event_bus.subscribe(
        AliceEvent.MCP_SERVER_DISCONNECTED, _forward_mcp_disconnected,
    )

    # -- Bridge Email events to the events WebSocket --------------------
    async def _forward_email_received(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "email.received",
                "folder": kwargs.get("folder", "INBOX"),
            })

    async def _forward_email_sent(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "email.sent",
                "message_id": kwargs.get("message_id"),
            })

    ctx.event_bus.subscribe(
        AliceEvent.EMAIL_RECEIVED, _forward_email_received,
    )
    ctx.event_bus.subscribe(
        AliceEvent.EMAIL_SENT, _forward_email_sent,
    )

    # -- Bridge Note events to the events WebSocket ---------------------
    async def _forward_note_created(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "note.created",
                "note_id": kwargs.get("note_id"),
                "title": kwargs.get("title"),
            })

    async def _forward_note_updated(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "note.updated",
                "note_id": kwargs.get("note_id"),
            })

    async def _forward_note_deleted(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "note.deleted",
                "note_id": kwargs.get("note_id"),
            })

    ctx.event_bus.subscribe(
        AliceEvent.NOTE_CREATED, _forward_note_created,
    )
    ctx.event_bus.subscribe(
        AliceEvent.NOTE_UPDATED, _forward_note_updated,
    )
    ctx.event_bus.subscribe(
        AliceEvent.NOTE_DELETED, _forward_note_deleted,
    )

    # -- Bridge orchestrator service.status events to the events WS ------
    async def _forward_service_status(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "service.status",
                "service": kwargs.get("service"),
                "status": kwargs.get("status"),
                "detail": kwargs.get("detail"),
                "timestamp": kwargs.get("timestamp"),
            })

    ctx.event_bus.subscribe(
        AliceEvent.SERVICE_STATUS, _forward_service_status,
    )

    # -- Bridge knowledge/RAG readiness changes to the events WS --------
    # Lets the UI reflect, live, when memory + tool-RAG are (re)enabled —
    # e.g. after the user triggers the vector-store "repair" CTA.
    async def _forward_knowledge_status(**kwargs):
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast({
                "type": "knowledge.status",
                "ready": kwargs.get("ready"),
                "reason": kwargs.get("reason"),
                "memory_enabled": kwargs.get("memory_enabled"),
                "tool_rag_enabled": kwargs.get("tool_rag_enabled"),
            })

    ctx.event_bus.subscribe("knowledge.status", _forward_knowledge_status)

    # -- Artifact registry (unified tool-output store) ------------------
    from backend.services.artifacts import ArtifactRegistry

    artifact_registry = ArtifactRegistry(session_factory=session_factory)

    async def _broadcast_artifact_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    artifact_registry.set_event_callback(_broadcast_artifact_event)
    ctx.artifact_registry = artifact_registry

    # -- Plan service (persisted per-conversation task list) ------------
    from backend.services.plan_service import PlanService

    plan_service = PlanService(session_factory=session_factory)

    async def _broadcast_tasks_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    plan_service.set_event_callback(_broadcast_tasks_event)
    ctx.plan_service = plan_service

    # -- Plan document service (persisted per-conversation strategy doc) -
    from backend.services.plan_document_service import PlanDocumentService

    plan_document_service = PlanDocumentService(session_factory=session_factory)

    async def _broadcast_plan_document_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    plan_document_service.set_event_callback(_broadcast_plan_document_event)
    await plan_document_service.load_all()
    ctx.plan_document_service = plan_document_service

    # -- Scope service (per-conversation workspace folder scope) --------
    from backend.services.scope_service import ScopeService

    scope_service = ScopeService(
        session_factory=session_factory,
        config=ctx.config.scope,
    )

    async def _broadcast_scope_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    scope_service.set_event_callback(_broadcast_scope_event)
    await scope_service.load_all()
    ctx.scope_service = scope_service

    # -- Permission mode service (per-conversation tier, Fase 7) --------
    from backend.services.permission_mode_service import (
        PermissionMode,
        PermissionModeService,
    )

    mode_service = PermissionModeService(
        session_factory=session_factory,
        default_mode=PermissionMode(ctx.config.permissions.default_mode),
    )

    async def _broadcast_permission_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    mode_service.set_event_callback(_broadcast_permission_event)
    await mode_service.load_all()
    ctx.permission_mode_service = mode_service

    # -- Permission rule service (persistent allow/ask/deny, Fase 7) ----
    from backend.services.permission_rules import PermissionRuleService

    rule_service = PermissionRuleService(session_factory=session_factory)
    await rule_service.load_all()
    ctx.permission_rule_service = rule_service

    # -- Permission service (central tool risk / scope / tier authority) -
    # Fase 6: ScopeService supplies the per-conversation scope provider, so a
    # tool tagged fs_read/fs_write is confined by construction. Fase 7:
    # PermissionRuleService supplies persistent allow/ask/deny rules. Hard
    # sandbox: ``effective_roots`` returns the explicit scope when set, else the
    # per-conversation ephemeral sandbox dir — so no scope set ⇒ filesystem
    # tools are confined to that sandbox (never the OS home/system root), not
    # denied outright.
    from backend.services.permission_service import PermissionService

    ctx.permission_service = PermissionService(
        scope_provider=scope_service.effective_roots,
        rule_provider=rule_service.match,
        forbidden_paths=ctx.config.scope.forbidden_paths,
    )

    # -- Interactive terminal session manager (Fase 7 E1) ---------------
    # Live PTY shells, scope-confined via ScopeService.scope_roots; output is
    # broadcast on the events WS, input/resize arrive over its receive loop.
    from backend.services.terminal import TerminalSessionManager

    terminal_manager = TerminalSessionManager(
        scope_provider=scope_service.scope_roots,
        scope_config=ctx.config.scope,
        shell=ctx.config.terminal.interactive_shell,
        max_sessions=ctx.config.terminal.max_sessions,
    )

    async def _broadcast_terminal_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    terminal_manager.set_event_callback(_broadcast_terminal_event)
    ctx.terminal_session_manager = terminal_manager

    app.state.context = ctx
    app.state.engine = engine

    logger.info("AL\\CE backend started (v{})", __version__)

    try:
        yield
    finally:
        # -- Shutdown -----------------------------------------------------------
        # Stop orchestrator polling first so health probes don't race with
        # the legacy per-service shutdown calls below.
        if ctx is not None and ctx.orchestrator is not None:
            try:
                await ctx.orchestrator.shutdown_polling()
            except Exception as exc:
                logger.error("Orchestrator shutdown error: {}", exc)
        if ctx is not None and ctx.terminal_session_manager is not None:
            try:
                await ctx.terminal_session_manager.shutdown()
            except Exception as exc:
                logger.error("Terminal manager shutdown error: {}", exc)
        if plugin_manager is not None:
            try:
                await plugin_manager.shutdown()
            except Exception as exc:
                logger.error("Plugin system shutdown error: {}", exc)
        if lmstudio_manager is not None:
            try:
                await lmstudio_manager.close()
            except Exception as exc:
                logger.error("LMStudio manager shutdown error: {}", exc)
        if llm_service is not None:
            try:
                await llm_service.close()
            except Exception as exc:
                logger.error("LLM service shutdown error: {}", exc)
        if ctx is not None and ctx.stt_service:
            try:
                await ctx.stt_service.stop()
            except Exception as exc:
                logger.error("STT shutdown error: {}", exc)
        if ctx is not None and ctx.tts_service:
            try:
                await ctx.tts_service.stop()
            except Exception as exc:
                logger.error("TTS shutdown error: {}", exc)
        if ctx is not None and ctx.vram_monitor:
            try:
                await ctx.vram_monitor.stop()
            except Exception as exc:
                logger.error("VRAM monitor shutdown error: {}", exc)
        if ctx is not None and ctx.memory_service:
            try:
                await ctx.memory_service.close()
            except Exception as exc:
                logger.error("Memory service shutdown error: {}", exc)
        if ctx is not None and ctx.email_service:
            try:
                await ctx.email_service.close()
            except Exception as exc:
                logger.error("Email service shutdown error: {}", exc)
        if ctx is not None and ctx.qdrant_service:
            try:
                await ctx.qdrant_service.close()
            except Exception as exc:
                logger.error("Qdrant service shutdown error: {}", exc)
        if ctx is not None and ctx.embedding_client:
            try:
                await ctx.embedding_client.close()
            except Exception as exc:
                logger.error("Embedding client shutdown error: {}", exc)
        if engine is not None:
            try:
                await engine.dispose()
            except Exception as exc:
                logger.error("Engine disposal error: {}", exc)
        logger.info("AL\\CE backend stopped")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_app(testing: bool = False) -> FastAPI:
    """Build and return the FastAPI application.

    Args:
        testing: When ``True`` an in-memory SQLite database is used.

    Returns:
        A fully configured ``FastAPI`` instance.
    """
    config = load_config()

    app = FastAPI(
        title="AL\\CE",
        version=__version__,
        lifespan=_lifespan,
    )

    # Stash config so the lifespan can retrieve it before context exists.
    app.state._config = config
    app.state._testing = testing

    # -- Middleware ----------------------------------------------------------
    # Starlette uses LIFO ordering: the last middleware added is the
    # outermost layer.  We add UnhandledExceptionMiddleware first (inner),
    # then CORSMiddleware (outer) so error responses carry CORS headers.
    app.add_middleware(UnhandledExceptionMiddleware)

    # Rate limiting (slowapi).
    setup_rate_limiting(app, config.server.rate_limit)

    app.add_middleware(
        OriginGuardMiddleware,
        trusted_origins=config.server.cors_origins,
    )

    # CORSMiddleware added LAST so it is outermost in the ASGI stack
    # and every response (including errors) carries CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )

    # -- Global exception handler -------------------------------------------
    # Catches unhandled exceptions so they return a JSON 500 response
    # that goes through CORSMiddleware (instead of a bare uvicorn 500).
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception,
    ) -> JSONResponse:
        logger.opt(exception=exc).error(
            "Unhandled exception on {} {}", request.method, request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )

    # -- Routes -------------------------------------------------------------
    from backend.api.routes import router as api_router  # noqa: E402

    app.include_router(api_router)

    # -- Static files (uploaded images) ------------------------------------
    uploads_dir = PROJECT_ROOT / "data" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/uploads",
        StaticFiles(directory=str(uploads_dir)),
        name="uploads",
    )

    return app
