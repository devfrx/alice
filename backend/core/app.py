"""O.M.N.I.A. — FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.core.config import OmniaConfig, PROJECT_ROOT, load_config
from backend.core.context import AppContext, create_context
from backend.db.database import create_engine_and_session, init_db
from backend.services.conversation_file_manager import ConversationFileManager
from backend.services.llm_service import LLMService
from backend.core.plugin_manager import PluginManager
from backend.core.tool_registry import ToolRegistry
from backend.api.middleware.rate_limit import setup_rate_limiting

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup / shutdown of the OMNIA backend."""
    # -- Startup ------------------------------------------------------------
    config: OmniaConfig = app.state._config  # set by create_app
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

    llm_service = LLMService(config.llm)
    ctx.llm_service = llm_service

    conversations_dir = PROJECT_ROOT / "data" / "conversations"
    ctx.conversation_file_manager = ConversationFileManager(conversations_dir)

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
        plugin_manager=plugin_manager, event_bus=ctx.event_bus,
    )
    try:
        await tool_registry.refresh()
    except Exception as exc:
        logger.error("Tool registry refresh failed: {}", exc)
    ctx.tool_registry = tool_registry

    app.state.context = ctx
    app.state.engine = engine

    logger.info("OMNIA backend started (v{})", __version__)

    yield

    # -- Shutdown -----------------------------------------------------------
    try:
        await plugin_manager.shutdown()
    except Exception as exc:
        logger.error("Plugin system shutdown error: {}", exc)
    await llm_service.close()
    await engine.dispose()
    logger.info("OMNIA backend stopped")


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
        title="O.M.N.I.A.",
        version=__version__,
        lifespan=_lifespan,
    )

    # Stash config so the lifespan can retrieve it before context exists.
    app.state._config = config
    app.state._testing = testing

    # -- Middleware ----------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting (slowapi).
    setup_rate_limiting(app, config.server.rate_limit)

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
