"""AL\\CE — Bootstrap stage: conversation services (Fase 5).

Artifact registry (unified tool-output store), plan service, and plan
document service — all persisted per-conversation and broadcasting on
the events WebSocket.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession as SQLModelAsyncSession

from backend.core.context import AppContext


async def stage_conversation(ctx: AppContext) -> None:
    """Wire the conversation group: artifacts, plan, plan document services.

    Args:
        ctx: The application context being bootstrapped.
    """
    assert ctx.db is not None, "stage_database must run before stage_conversation"
    session_factory = ctx.db

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

    # PlanDocumentService declares the SQLModel-aware session type (the
    # actual runtime factory, per db/database.py); ``ctx.db`` is typed with
    # SQLAlchemy's plain ``AsyncSession`` — cast reflects the real type.
    plan_document_service = PlanDocumentService(
        session_factory=cast(
            "async_sessionmaker[SQLModelAsyncSession]", session_factory,
        ),
    )

    async def _broadcast_plan_document_event(event: dict) -> None:
        if ctx.ws_connection_manager:
            await ctx.ws_connection_manager.broadcast(event)

    plan_document_service.set_event_callback(_broadcast_plan_document_event)
    await plan_document_service.load_all()
    ctx.plan_document_service = plan_document_service
