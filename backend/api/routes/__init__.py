"""AL\\CE — API route registry."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.api.routes import artifacts, audit, cad, calendar, charts, chat, config, email, events, mcp, mcp_memory, memory, models, notes, plugins, services, settings, vector_store, voice, whiteboards

router = APIRouter(prefix="/api")

router.include_router(audit.router)
router.include_router(calendar.router)
router.include_router(chat.router)
router.include_router(config.router)
router.include_router(memory.router)
router.include_router(models.router)
router.include_router(notes.router)
router.include_router(plugins.router)
router.include_router(services.router)
router.include_router(settings.router)
router.include_router(voice.router)
router.include_router(events.router)
router.include_router(mcp.router)
router.include_router(mcp_memory.router)
router.include_router(cad.router)
router.include_router(charts.router)
router.include_router(whiteboards.router)
router.include_router(email.router)
router.include_router(vector_store.router)
router.include_router(artifacts.router)


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness / readiness probe."""
    healthy = getattr(request.app.state, "healthy", True)
    return {
        "status": "ok" if healthy else "degraded",
        "version": "0.1.0",
    }

