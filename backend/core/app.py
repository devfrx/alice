"""AL\\CE — FastAPI application factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.core.config import AliceConfig, PROJECT_ROOT, load_config
from backend.core.context import AppContext, create_context
from backend.core.event_bus import AliceEvent
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

    ctx: AppContext = create_context(config)
    ctx.db = session_factory  # type: ignore[assignment]
    ctx.engine = engine

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

    # -- Note service (Phase 13) -------------------------------------------
    if config.notes.enabled and qdrant_service:
        from backend.services.note_service import NoteService

        note_service = NoteService(
            config.notes, qdrant_service, embedding_client,
        )
        try:
            await note_service.initialize()
            ctx.note_service = note_service
            logger.info("Note service started")
        except Exception as exc:
            logger.warning("Note service failed to start: {}", exc)
            await note_service.close()

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

    if config.tts.enabled:
        try:
            tts_service = TTSService(config.tts)
            await tts_service.start()
            ctx.tts_service = tts_service
            logger.info("TTS service started (engine={})", config.tts.engine)
        except Exception as exc:
            logger.warning("TTS service failed to start: {}", exc)

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

    # -- VRAM event handlers ------------------------------------------------
    if ctx.vram_monitor:
        async def _handle_vram_warning(**kwargs):
            """React to VRAM pressure — downgrade STT compute type."""
            usage = kwargs.get("usage")
            if usage:
                logger.warning(
                    "VRAM warning: {}MB used / {}MB total",
                    usage.used_mb, usage.total_mb,
                )
            # Downgrade STT compute type if available
            if ctx.stt_service and hasattr(ctx.stt_service, '_config'):
                stt_cfg = ctx.stt_service._config
                if stt_cfg.compute_type == "float16":
                    logger.info("VRAM pressure: downgrading STT compute_type to int8")
                    stt_cfg.compute_type = "int8"

        async def _handle_vram_critical(**kwargs):
            """React to critical VRAM — switch TTS to lightweight engine."""
            usage = kwargs.get("usage")
            if usage:
                logger.error(
                    "VRAM critical: {}MB used / {}MB total",
                    usage.used_mb, usage.total_mb,
                )
            # Switch TTS engine to Piper (CPU-based, no VRAM)
            if ctx.tts_service and hasattr(ctx.tts_service, '_config'):
                tts_cfg = ctx.tts_service._config
                if tts_cfg.engine not in ("piper", "kokoro"):
                    logger.warning(
                        "VRAM critical: switching TTS from '{}' to 'piper'",
                        tts_cfg.engine,
                    )
                    tts_cfg.engine = "piper"
            # Disable VRAM-heavy STT if possible
            if ctx.stt_service and hasattr(ctx.stt_service, '_config'):
                stt_cfg = ctx.stt_service._config
                if stt_cfg.device == "cuda":
                    logger.warning("VRAM critical: switching STT device from 'cuda' to 'cpu'")
                    stt_cfg.device = "cpu"
                    if stt_cfg.compute_type == "float16":
                        stt_cfg.compute_type = "int8"

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

    # -- Artifact registry (unified tool-output store) ------------------
    from backend.services.artifacts import ArtifactRegistry

    artifact_registry = ArtifactRegistry(session_factory=session_factory)

    async def _broadcast_artifact_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    artifact_registry.set_event_callback(_broadcast_artifact_event)
    ctx.artifact_registry = artifact_registry

    # -- Agent Loop v2 components (optional) --------------------------------
    # Only instantiated if ``agent.enabled`` is True.  The actual service
    # classes live in ``backend.services.agent`` (created by a sibling
    # subagent) — we wrap the import in try/except so a missing module
    # cannot break startup.  When components cannot be built we keep the
    # legacy direct-execution path.
    if config.agent.enabled:
        try:
            from backend.services.agent import (  # type: ignore
                AgentComponents,
                ClassifierService,
                PlannerService,
                CriticService,
            )

            ctx.agent_components = AgentComponents(
                classifier=ClassifierService(llm_service, config.agent.classifier),
                planner=PlannerService(llm_service, config.agent.planner),
                critic=CriticService(llm_service, config.agent.critic),
            )
            logger.info("Agent loop enabled")
        except Exception as exc:
            logger.warning("Failed to init agent components: {}", exc)
            ctx.agent_components = None
    else:
        ctx.agent_components = None

    app.state.context = ctx
    app.state.engine = engine

    logger.info("AL\\CE backend started (v{})", __version__)

    try:
        yield
    finally:
        # -- Shutdown -----------------------------------------------------------
        try:
            await plugin_manager.shutdown()
        except Exception as exc:
            logger.error("Plugin system shutdown error: {}", exc)
        try:
            await lmstudio_manager.close()
        except Exception as exc:
            logger.error("LMStudio manager shutdown error: {}", exc)
        try:
            await llm_service.close()
        except Exception as exc:
            logger.error("LLM service shutdown error: {}", exc)
        if ctx.stt_service:
            try:
                await ctx.stt_service.stop()
            except Exception as exc:
                logger.error("STT shutdown error: {}", exc)
        if ctx.tts_service:
            try:
                await ctx.tts_service.stop()
            except Exception as exc:
                logger.error("TTS shutdown error: {}", exc)
        if ctx.vram_monitor:
            try:
                await ctx.vram_monitor.stop()
            except Exception as exc:
                logger.error("VRAM monitor shutdown error: {}", exc)
        if ctx.memory_service:
            try:
                await ctx.memory_service.close()
            except Exception as exc:
                logger.error("Memory service shutdown error: {}", exc)
        if ctx.note_service:
            try:
                await ctx.note_service.close()
            except Exception as exc:
                logger.error("Note service shutdown error: {}", exc)
        if ctx.email_service:
            try:
                await ctx.email_service.close()
            except Exception as exc:
                logger.error("Email service shutdown error: {}", exc)
        if ctx.qdrant_service:
            try:
                await ctx.qdrant_service.close()
            except Exception as exc:
                logger.error("Qdrant service shutdown error: {}", exc)
        if ctx.embedding_client:
            try:
                await ctx.embedding_client.close()
            except Exception as exc:
                logger.error("Embedding client shutdown error: {}", exc)
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
