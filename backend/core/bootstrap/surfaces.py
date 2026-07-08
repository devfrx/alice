"""AL\\CE — Bootstrap stage: WebSocket surfaces (Fase 5).

The events WebSocket connection manager plus every event-bus → WS
broadcast bridge (MCP, email, notes, orchestrator service status,
knowledge/RAG readiness).
"""

from __future__ import annotations

from backend.core.context import AppContext
from backend.core.event_bus import AliceEvent


async def stage_surfaces(ctx: AppContext) -> None:
    """Wire the WS connection manager and every event → WS broadcast bridge.

    Args:
        ctx: The application context being bootstrapped.
    """
    # -- WebSocket connection manager (Phase 10) ----------------------------
    from backend.services.ws_connection_manager import WSConnectionManager

    ws_connection_manager = WSConnectionManager()
    ctx.ws_connection_manager = ws_connection_manager
    from backend.api.ws_schema.guard import events_frame_validator

    ws_connection_manager.set_frame_validator(events_frame_validator)

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
