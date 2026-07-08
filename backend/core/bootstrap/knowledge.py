"""AL\\CE — Bootstrap stage: knowledge services (Fase 5).

Embedding client, Qdrant service, memory service, the Continuum client,
and the single-entry-point ``KnowledgeService``.
"""

from __future__ import annotations

from loguru import logger

from backend.core.context import AppContext


async def stage_knowledge(ctx: AppContext) -> None:
    """Wire the knowledge group: embedding, Qdrant, memory, knowledge service.

    Args:
        ctx: The application context being bootstrapped.
    """
    config = ctx.config

    # -- Embedding client + Qdrant service (shared) -------------------------
    from backend.services.embedding_client import EmbeddingClient
    from backend.services.qdrant_service import QdrantService

    embedding_client = EmbeddingClient(
        base_url=config.llm.base_url,
        model=config.qdrant.embedding_model,
        dimensions=config.qdrant.embedding_dim,
        fallback_enabled=config.qdrant.embedding_fallback,
    )
    # Probe actual dims so ensure_collection uses the real vector size,
    # not the potentially stale config value.
    try:
        actual_dim = await embedding_client.probe_dimensions()
        logger.info("Embedding dimensions probed: {}", actual_dim)
    except Exception as exc:
        logger.warning(
            "Embedding dimension probe failed: {} — using configured dim ({})",
            exc,
            config.qdrant.embedding_dim,
        )
    ctx.embedding_client = embedding_client

    qdrant_service = QdrantService(config.qdrant)
    try:
        await qdrant_service.initialize()
        ctx.qdrant_service = qdrant_service
        logger.info("Qdrant service started (mode={})", config.qdrant.mode)
    except Exception as exc:
        logger.warning("Qdrant service failed to start: {}", exc)
        try:
            await qdrant_service.close()
        except Exception:
            pass
        qdrant_service = None

    # -- Memory service (Phase 9) ------------------------------------------
    if config.memory.enabled and qdrant_service:
        from backend.services.memory_service import MemoryService

        memory_service = MemoryService(
            config.memory, qdrant_service, embedding_client,
            embedding_model=config.qdrant.embedding_model,
        )
        try:
            await memory_service.initialize()
            ctx.memory_service = memory_service
            logger.info("Memory service started")
        except Exception as exc:
            logger.warning("Memory service failed to start: {}", exc)
            await memory_service.close()

    # -- Knowledge service (Fase 4) -----------------------------------------
    # ONE entry point to the knowledge domain: KnowledgeService wraps the
    # composable backend (composite with Continuum when enabled).  The
    # ContinuumClient is instantiated HERE and only here; knowledge_init
    # and the continuum plugin reuse ctx.continuum_client.
    from backend.services.knowledge.service import build_knowledge_service

    if config.continuum.enabled:
        from backend.services.knowledge import ContinuumClient

        ctx.continuum_client = ContinuumClient(
            base_url=config.continuum.base_url,
            api_token=config.continuum.api_token,
            timeout_s=config.continuum.timeout_s,
            folder_cache_ttl_s=config.continuum.folder_cache_ttl_s,
        )
    ctx.knowledge_service = build_knowledge_service(
        continuum_enabled=config.continuum.enabled,
        memory_service=ctx.memory_service,
        continuum_client=ctx.continuum_client,
    )
    if config.continuum.enabled:
        logger.info(
            "Knowledge service wired (notes=continuum @ {}, memory={})",
            config.continuum.base_url,
            ctx.memory_service is not None,
        )
    else:
        logger.info(
            "Knowledge service wired (memory={}, notes=disabled)",
            ctx.memory_service is not None,
        )
