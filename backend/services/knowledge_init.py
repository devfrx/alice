"""Runtime (re)wiring of the vector / RAG stack.

Backs the user-triggered "Ripara/Reset vector store" CTA.  When the embedded
Qdrant store cannot be opened (e.g. data written by an incompatible
``qdrant-client`` version), the lifespan leaves ``ctx.qdrant_service`` /
``ctx.memory_service`` as ``None`` and the RAG stack disabled.  This module
clears the embedded store, re-initialises Qdrant + memory + the knowledge
service, re-points tool-RAG at the fresh services, recomputes readiness and
broadcasts ``knowledge.status``.

Plugins read ``ctx.knowledge_service`` lazily on every call, so re-wiring
the context is sufficient — no plugin re-initialisation is required.
Never raises: a failed repair returns a disabled :class:`RagReadiness`
carrying the reason.
"""

from __future__ import annotations

import contextlib
from typing import Any

from loguru import logger

from backend.services.qdrant_service import QdrantService
from backend.services.rag_readiness import RagReadiness, check_rag_readiness


async def _emit_knowledge_status(ctx: Any, readiness: RagReadiness) -> None:
    """Broadcast the current readiness verdict on the event bus."""
    with contextlib.suppress(Exception):
        await ctx.event_bus.emit(
            "knowledge.status",
            ready=readiness.ready,
            reason=readiness.reason,
            memory_enabled=readiness.memory_enabled,
            tool_rag_enabled=readiness.tool_rag_enabled,
        )


async def repair_vector_store(ctx: Any) -> RagReadiness:
    """Reset the embedded vector store and re-wire the RAG stack in place.

    Destructive: clears persisted embedded vectors (memories/facts are
    regenerable).  Never raises — returns the recomputed
    :class:`RagReadiness` (disabled, with a reason, on failure) and emits
    ``knowledge.status`` so connected clients update.

    Args:
        ctx: The application context (needs ``config``, ``event_bus``,
            ``embedding_client`` and, optionally, ``tool_registry``).

    Returns:
        The recomputed readiness verdict.
    """
    config = ctx.config

    # 1. Tear down the old client (if any), clear stale data, re-initialise.
    old = getattr(ctx, "qdrant_service", None)
    if old is not None:
        with contextlib.suppress(Exception):
            await old.close()

    qdrant = QdrantService(config.qdrant)
    qdrant.clear_embedded_data()
    try:
        await qdrant.initialize()
        ctx.qdrant_service = qdrant
        logger.info(
            "Repair: Qdrant re-initialised (mode={})", config.qdrant.mode,
        )
    except Exception as exc:
        logger.warning("Repair: Qdrant re-init failed: {}", exc)
        with contextlib.suppress(Exception):
            await qdrant.close()
        ctx.qdrant_service = None

    # 2. Re-create the memory service when Qdrant is healthy.
    ctx.memory_service = None
    if config.memory.enabled and ctx.qdrant_service is not None:
        from backend.services.memory_service import MemoryService

        memory_service = MemoryService(
            config.memory,
            ctx.qdrant_service,
            ctx.embedding_client,
            embedding_model=config.qdrant.embedding_model,
        )
        try:
            await memory_service.initialize()
            ctx.memory_service = memory_service
            logger.info("Repair: memory service re-initialised")
        except Exception as exc:
            logger.warning("Repair: memory service re-init failed: {}", exc)
            with contextlib.suppress(Exception):
                await memory_service.close()
            ctx.memory_service = None

    # 3. Re-wire the knowledge service (reusing the shared Continuum client).
    from backend.services.knowledge.service import build_knowledge_service

    client = getattr(ctx, "continuum_client", None)
    if config.continuum.enabled and client is None:
        # The client is built once in the lifespan; if it is missing here
        # the wiring is broken — proceed memory-only, never build a second
        # client.
        logger.warning(
            "Repair: continuum enabled but no shared client — notes disabled",
        )
    ctx.knowledge_service = build_knowledge_service(
        continuum_enabled=config.continuum.enabled and client is not None,
        memory_service=ctx.memory_service,
        continuum_client=client,
    )
    # 4. Point tool-RAG at the new backends and re-embed (best-effort).
    if ctx.tool_registry is not None:
        ctx.tool_registry.set_vector_backends(
            ctx.qdrant_service, ctx.embedding_client,
        )
        ctx.tool_registry.clear_status_cache()
        try:
            await ctx.tool_registry.refresh()
        except Exception as exc:
            logger.warning("Repair: tool registry refresh failed: {}", exc)

    # 5. Recompute readiness and broadcast it.
    readiness = await check_rag_readiness(ctx)
    ctx.rag_readiness = readiness
    await _emit_knowledge_status(ctx, readiness)
    logger.info(
        "Repair complete — RAG ready={} ({})",
        readiness.ready, readiness.reason,
    )
    return readiness
