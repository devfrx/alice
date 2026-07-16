"""AL\\CE — API route registry."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.api.routes import artifacts, audit, cad, calendar, chat, config, email, events, knowledge, mcp, mcp_memory, memory, models, openrouter, permission_mode, permission_rules, plan_document, plugins, scope, services, settings, tasks, terminal, vector_store, voice

router = APIRouter(prefix="/api")

router.include_router(audit.router)
router.include_router(calendar.router)
router.include_router(chat.router)
router.include_router(config.router)
router.include_router(knowledge.router)
router.include_router(memory.router)
router.include_router(models.router)
router.include_router(openrouter.router)
router.include_router(plugins.router)
router.include_router(services.router)
router.include_router(settings.router)
router.include_router(voice.router)
router.include_router(events.router)
router.include_router(mcp.router)
router.include_router(mcp_memory.router)
router.include_router(cad.router)
router.include_router(email.router)
router.include_router(vector_store.router)
router.include_router(artifacts.router)
router.include_router(tasks.router)
router.include_router(plan_document.router)
router.include_router(scope.router)
router.include_router(permission_mode.router)
router.include_router(permission_rules.router)
router.include_router(terminal.router)


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness / readiness probe."""
    healthy = getattr(request.app.state, "healthy", True)
    return {
        "status": "ok" if healthy else "degraded",
        "version": "0.1.0",
    }

