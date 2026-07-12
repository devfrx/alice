"""Runtime (re)wiring of the vector / RAG stack.

Backs the user-triggered "Ripara/Reset vector store" CTA.  When the embedded
Qdrant store cannot be opened (e.g. data written by an incompatible
``qdrant-client`` version), the lifespan leaves ``ctx.qdrant_service`` /
``ctx.memory_service`` as ``None`` and the RAG stack disabled.  This module
clears the embedded store, re-initialises Qdrant + memory + the knowledge
service, then atomically swaps the knowledge service group, re-points
tool-RAG at the fresh services, recomputes readiness and broadcasts
``knowledge.status``.

Plugins read ``ctx.knowledge_service`` lazily on every call, so re-wiring
the context is sufficient — no plugin re-initialisation is required.
Never raises: a failed repair returns a disabled :class:`RagReadiness`
carrying the reason.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.core.service_groups import KnowledgeServices
from backend.services.qdrant_service import QdrantService
from backend.services.rag_readiness import RagReadiness, check_rag_readiness

if TYPE_CHECKING:
    from backend.services.memory_service import MemoryService


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
    """Reset the embedded vector store and atomically swap the knowledge group.

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

    # 1. Tear down the old client (if any; read BEFORE the swap below), clear
    # stale data, re-initialise. Built in a local — not assigned to ctx yet.
    old = getattr(ctx, "qdrant_service", None)
    if old is not None:
        with contextlib.suppress(Exception):
            await old.close()

    new_qdrant = QdrantService(config.qdrant)
    cleared = new_qdrant.clear_embedded_data()
    if not cleared and config.qdrant.mode == "embedded":
        # rmtree(ignore_errors=True) silently no-ops on files held open by a
        # live process (Windows). If the data dir cannot be cleared, another
        # instance owns it — re-init below will fall back to in-memory.
        logger.warning(
            "Repair: embedded data dir could not be cleared (locked by another "
            "process?) — {}", config.qdrant.path,
        )
    qdrant_service: QdrantService | None = new_qdrant
    try:
        await new_qdrant.initialize()
        actual_mode = (
            "in-memory (fallback)" if new_qdrant.in_memory else config.qdrant.mode
        )
        logger.info("Repair: Qdrant re-initialised (mode={})", actual_mode)
    except Exception as exc:
        logger.warning("Repair: Qdrant re-init failed: {}", exc)
        with contextlib.suppress(Exception):
            await new_qdrant.close()
        qdrant_service = None

    # 2. Re-create the memory service when Qdrant is healthy. Local only.
    memory_service: MemoryService | None = None
    if config.memory.enabled and qdrant_service is not None:
        from backend.services.memory_service import MemoryService

        memory_service = MemoryService(
            config.memory,
            qdrant_service,
            ctx.embedding_client,
            embedding_model=config.qdrant.embedding_model,
        )
        try:
            await memory_service.initialize()
            logger.info("Repair: memory service re-initialised")
        except Exception as exc:
            logger.warning("Repair: memory service re-init failed: {}", exc)
            with contextlib.suppress(Exception):
                await memory_service.close()
            memory_service = None

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
    knowledge_service = build_knowledge_service(
        continuum_enabled=config.continuum.enabled and client is not None,
        memory_service=memory_service,
        continuum_client=client,
    )

    # 3b. Swap the WHOLE knowledge group atomically: readers holding the
    # old group keep a coherent (stale) view — though its qdrant client is
    # already closed, so operations through it fail as they always did
    # mid-repair; readers dereferencing ctx see only the fully-wired new
    # group. This closes the partial-state window the in-place rewiring
    # had (Fase 4 review backlog).
    ctx.knowledge = KnowledgeServices(
        knowledge_service=knowledge_service,
        memory_service=memory_service,
        qdrant_service=qdrant_service,
        continuum_client=client,
        rag_readiness=None,
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

    # 5. Recompute readiness and broadcast it. This reads the group already
    # swapped in step 3b (ctx.qdrant_service/memory_service resolve through
    # the NEW group) and the tool registry refreshed in step 4, so it must
    # run after both — hence the additive write here rather than folding
    # `rag_readiness` into the KnowledgeServices literal above.
    readiness = await check_rag_readiness(ctx)
    ctx.rag_readiness = readiness
    await _emit_knowledge_status(ctx, readiness)
    logger.info(
        "Repair complete — RAG ready={} ({})",
        readiness.ready, readiness.reason,
    )
    return readiness
