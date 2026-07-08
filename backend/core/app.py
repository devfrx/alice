"""AL\\CE — FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.api.middleware.exception_handler import UnhandledExceptionMiddleware
from backend.api.middleware.origin_guard import OriginGuardMiddleware
from backend.api.middleware.rate_limit import setup_rate_limiting
from backend.core.bootstrap import (
    shutdown_services,
    stage_conversation,
    stage_database,
    stage_inference,
    stage_knowledge,
    stage_platform,
    stage_plugins,
    stage_senses,
    stage_surfaces,
    stage_workspace,
)
from backend.core.config import PROJECT_ROOT, AliceConfig, load_config
from backend.core.context import AppContext, create_context

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup / shutdown of the AL\\CE backend."""
    config: AliceConfig = app.state._config  # set by create_app
    testing: bool = app.state._testing

    ctx: AppContext | None = None
    try:
        ctx = create_context(config)

        # Declarative bootstrap (Fase 5, spec §5.1): explicit stage order.
        await stage_database(ctx, testing=testing)
        await stage_platform(ctx, testing=testing)
        await stage_inference(ctx)
        await stage_knowledge(ctx)
        await stage_senses(ctx)
        await stage_plugins(ctx, app)
        await stage_surfaces(ctx)
        await stage_conversation(ctx)
        await stage_workspace(ctx)

        app.state.context = ctx
        app.state.engine = ctx.engine

        logger.info("AL\\CE backend started (v{})", __version__)
        yield
    finally:
        # -- Shutdown -------------------------------------------------------
        await shutdown_services(ctx)
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
