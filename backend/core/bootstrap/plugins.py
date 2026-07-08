"""AL\\CE — Bootstrap stage: plugin system + tool registry (Fase 5).

Plugin manager startup, tool registry construction + refresh, and the
all-or-nothing RAG readiness gate.
"""

from __future__ import annotations

from contextlib import suppress

from fastapi import FastAPI
from loguru import logger

from backend.core.context import AppContext
from backend.core.plugin_manager import PluginManager
from backend.core.tool_registry import ToolRegistry


async def stage_plugins(ctx: AppContext, app: FastAPI) -> None:
    """Start the plugin system, build the tool registry, gate RAG readiness.

    Args:
        ctx: The application context being bootstrapped.
        app: The FastAPI app (``app.state.healthy`` is set here).
    """
    config = ctx.config

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
