"""All-or-nothing RAG readiness gate (functionality-fixes #3).

Truly probes the vector + embedding stack and, on failure, attempts a bounded
auto-repair (clear a stale embedded lock and reinitialize). If the stack still
is not 100% healthy, the caller disables memory + tool-RAG entirely rather than
running degraded. Never raises.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from backend.services.qdrant_service import COLLECTION_MEMORY


@dataclass(frozen=True, slots=True)
class RagReadiness:
    """Verdict of :func:`check_rag_readiness`."""

    ready: bool
    reason: str
    memory_enabled: bool
    tool_rag_enabled: bool


async def _probe(ctx: Any) -> tuple[bool, str]:
    """Probe the vector + embedding stack once. Returns ``(ok, reason)``."""
    qd = getattr(ctx, "qdrant_service", None)
    emb = getattr(ctx, "embedding_client", None)
    if qd is None or emb is None:
        return False, "qdrant or embedding client missing"
    if getattr(qd, "in_memory", False):
        return False, "Qdrant running in volatile in-memory fallback"
    try:
        vec = await emb.encode("readiness probe")
    except Exception as exc:
        return False, f"embedding round-trip failed: {exc}"
    if not vec or len(vec) != int(emb.dimensions):
        return False, "embedding round-trip returned wrong/empty vector"
    if getattr(ctx, "memory_service", None) is not None:
        try:
            dim = await qd.get_collection_dim(COLLECTION_MEMORY)
        except Exception as exc:
            return False, f"memory collection probe failed: {exc}"
        if dim is not None and dim != int(emb.dimensions):
            return False, f"memory collection dim {dim} != {emb.dimensions}"
    return True, "ok"


async def check_rag_readiness(ctx: Any) -> RagReadiness:
    """Probe → bounded auto-repair → re-probe. Returns the final verdict.

    Never raises. On an unrecoverable failure returns a verdict with
    ``ready=False`` and both ``memory_enabled``/``tool_rag_enabled`` False, so the
    caller disables the RAG stack entirely instead of running half-broken.

    Args:
        ctx: The :class:`~backend.core.context.AppContext` (or any object
            exposing ``qdrant_service``, ``embedding_client``, ``memory_service``
            and ``config.llm.tool_rag_enabled``).

    Returns:
        The final :class:`RagReadiness` verdict.
    """
    ok, reason = await _probe(ctx)
    if not ok:
        qd = getattr(ctx, "qdrant_service", None)
        repaired = False
        if qd is not None and getattr(qd, "in_memory", False) and qd.try_clear_stale_lock():
            try:
                await qd.reinitialize()
                repaired = True
            except Exception as exc:
                logger.warning("Qdrant reinitialize after lock-clear failed: {}", exc)
        if repaired:
            ok, reason = await _probe(ctx)
    try:
        tool_rag = bool(getattr(ctx.config.llm, "tool_rag_enabled", False))
    except Exception:
        tool_rag = False
    if not ok:
        logger.warning("RAG readiness FAILED — memory + tool-RAG disabled: {}", reason)
        return RagReadiness(False, reason, memory_enabled=False, tool_rag_enabled=False)
    return RagReadiness(True, "ok", memory_enabled=True, tool_rag_enabled=tool_rag)
