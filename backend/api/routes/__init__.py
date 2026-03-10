"""O.M.N.I.A. — API route registry."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.api.routes import audit, calendar, chat, config, memory, models, plugins, settings, voice

router = APIRouter(prefix="/api")

router.include_router(audit.router)
router.include_router(calendar.router)
router.include_router(chat.router)
router.include_router(config.router)
router.include_router(memory.router)
router.include_router(models.router)
router.include_router(plugins.router)
router.include_router(settings.router)
router.include_router(voice.router)


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness / readiness probe."""
    healthy = getattr(request.app.state, "healthy", True)
    return {
        "status": "ok" if healthy else "degraded",
        "version": "0.1.0",
    }

