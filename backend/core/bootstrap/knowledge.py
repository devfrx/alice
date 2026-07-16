"""AL\\CE — Bootstrap stage: knowledge services (Fase 5).

Embedding client, Qdrant service, memory service, the Continuum client,
and the single-entry-point ``KnowledgeService``.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from loguru import logger

from backend.core.context import AppContext

if TYPE_CHECKING:
    from backend.core.config import AliceConfig
    from backend.services.embedding_client import EmbeddingClient


def build_embedding_client(config: AliceConfig) -> EmbeddingClient:
    """Construct the embedding client, warning loudly when it can't encode.

    api_enabled is decided once at bootstrap time: a runtime provider switch
    does NOT rebuild the embedding client, so memory keeps using whatever
    backend was active at startup until the process restarts.

    With a cloud provider (OpenRouter) the API backend is disabled on purpose
    to keep embeddings local; if fastembed is also inactive (embedding_dim
    incompatible with its default model, or fallback disabled) every memory
    encode would fail — surface that here instead of at each operation.

    Args:
        config: The full application config.

    Returns:
        The constructed embedding client (possibly with no usable backend).
    """
    from backend.services.embedding_client import EmbeddingClient

    client = EmbeddingClient(
        base_url=config.llm.base_url,
        model=config.qdrant.embedding_model,
        dimensions=config.qdrant.embedding_dim,
        fallback_enabled=config.qdrant.embedding_fallback,
        api_enabled=config.llm.provider != "openrouter",
    )
    if not client.has_active_backend:
        logger.warning(
            "No embedding backend available: llm.provider='{}' keeps embeddings "
            "local (embedding API disabled) but the fastembed fallback is "
            "inactive (qdrant.embedding_dim={}, embedding_fallback={}). Memory "
            "encode operations WILL fail — set qdrant.embedding_dim to 384 and "
            "enable qdrant.embedding_fallback, or switch to a local LLM provider.",
            config.llm.provider,
            config.qdrant.embedding_dim,
            config.qdrant.embedding_fallback,
        )
    return client


async def stage_knowledge(ctx: AppContext) -> None:
    """Wire the knowledge group: embedding, Qdrant, memory, knowledge service.

    Args:
        ctx: The application context being bootstrapped.
    """
    config = ctx.config

    # -- Embedding client + Qdrant service (shared) -------------------------
    from backend.services.qdrant_service import QdrantService

    embedding_client = build_embedding_client(config)
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
        with contextlib.suppress(Exception):
            await qdrant_service.close()
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
            api_token=(
                config.continuum.api_token.get_secret_value()
                if config.continuum.api_token
                else None
            ),
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
