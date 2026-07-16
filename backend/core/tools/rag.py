"""AL\\CE — Tool RAG: semantic tool retrieval.

Embeds registered tools into Qdrant and retrieves the most relevant
subset for a query, falling back to the full available toolset when
the vector backend is unavailable or returns nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from backend.core.config import LLMConfig
from backend.core.protocols import EmbeddingClientProtocol, QdrantServiceProtocol
from backend.core.tools.availability import (
    USABLE_STATUSES,
    AvailabilityProbe,
    compose_available_tools,
)
from backend.core.tools.catalog import ToolCatalog
from backend.core.vector_collections import COLLECTION_TOOLS, PROJECT_NS


class ToolRag:
    """Embeds and semantically retrieves tools for a turn.

    Args:
        catalog: The tool catalog (definitions + owning-plugin lookup).
        availability: The availability probe (per-plugin connection status).
        llm_config: LLM configuration supplying ``priority_plugins``.
    """

    def __init__(
        self,
        catalog: ToolCatalog,
        availability: AvailabilityProbe,
        *,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self._catalog = catalog
        self._availability = availability
        self._logger = logger.bind(component="ToolRag")

        self._qdrant: QdrantServiceProtocol | None = None
        self._embedder: EmbeddingClientProtocol | None = None
        self._llm_config = llm_config

    def set_vector_backends(
        self,
        qdrant_service: QdrantServiceProtocol | None,
        embedding_client: EmbeddingClientProtocol | None,
    ) -> None:
        """Swap the Qdrant / embedding backends at runtime.

        Used by the vector-store repair flow after Qdrant is re-initialised,
        so tool-RAG picks up the freshly-wired services without a restart.
        """
        self._qdrant = qdrant_service
        self._embedder = embedding_client

    @property
    def has_vector_backends(self) -> bool:
        """Whether both the Qdrant service and the embedding client are wired."""
        return bool(self._qdrant and self._embedder)

    # ------------------------------------------------------------------
    # Tool RAG — embed & retrieve
    # ------------------------------------------------------------------

    async def embed_tools(self) -> None:
        """Embed all registered tools into Qdrant for Tool RAG.

        Each tool is represented as:
        ``"{name}: {description}. params: {param1, param2, ...}"``
        """
        if not self._qdrant or not self._embedder:
            return

        await self._qdrant.ensure_collection(
            COLLECTION_TOOLS,
            self._embedder.dimensions,
        )

        async with self._catalog.lock:
            tools_snapshot = dict(self._catalog.tools)
            plugin_map_snapshot = dict(self._catalog.tool_to_plugin)

        # Build embedding texts
        names: list[str] = []
        texts: list[str] = []
        for ns_name, tool_def in tools_snapshot.items():
            params = ", ".join(
                tool_def.parameters.get("properties", {}).keys()
            )
            text = f"{ns_name}: {tool_def.description}. params: {params}"
            names.append(ns_name)
            texts.append(text)

        if not texts:
            return

        vectors = await self._embedder.encode_batch(texts)

        # Upsert tool points
        from qdrant_client import models as qmodels
        points: list[Any] = []
        for ns_name, vector in zip(names, vectors, strict=True):
            tool_def = tools_snapshot[ns_name]
            fmt = tool_def.to_openai_format()
            fmt["function"]["name"] = ns_name

            points.append(
                qmodels.PointStruct(
                    id=str(uuid.uuid5(PROJECT_NS, ns_name)),
                    vector=vector,
                    payload={
                        "tool_name": ns_name,
                        "plugin_name": plugin_map_snapshot.get(ns_name, ""),
                        "openai_def": fmt,
                    },
                )
            )

        await self._qdrant.upsert(COLLECTION_TOOLS, points)

        # Remove orphan points (tools that no longer exist)
        current_ids = {
            str(uuid.uuid5(PROJECT_NS, n)) for n in names
        }
        offset = None
        orphan_ids: list[str] = []
        while True:
            records, next_offset = await self._qdrant.scroll(
                COLLECTION_TOOLS, limit=100, offset=offset,
            )
            if not records:
                break
            for r in records:
                if str(r.id) not in current_ids:
                    orphan_ids.append(str(r.id))
            if next_offset is None:
                break
            offset = next_offset

        if orphan_ids:
            await self._qdrant.delete(COLLECTION_TOOLS, ids=orphan_ids)
            self._logger.info(
                "Removed {} orphan tool embeddings", len(orphan_ids),
            )

        self._logger.info(
            "Embedded {} tools into Qdrant", len(points),
        )

    async def get_relevant_tools(
        self,
        query: str,
        k: int = 15,
    ) -> list[dict[str, Any]]:
        """Retrieve the most relevant tools for a query via semantic search.

        Falls back to get_available_tools() if Qdrant is unavailable.
        Always includes tools from priority plugins and tools declaring
        ``always_offered``.

        Args:
            query: User message to match tools against.
            k: Maximum number of tools to return.

        Returns:
            OpenAI-format tool definitions.
        """
        if not self._qdrant or not self._embedder:
            return await compose_available_tools(self._catalog, self._availability)

        try:
            vector = await self._embedder.encode(query)
        except Exception as exc:
            self._logger.warning(
                "Embedding failed, falling back to full tools: {}", exc,
            )
            return await compose_available_tools(self._catalog, self._availability)

        try:
            hits = await self._qdrant.search(
                COLLECTION_TOOLS, vector, k=k,
            )
        except Exception as exc:
            self._logger.warning(
                "Qdrant search failed, falling back to full tools: {}", exc,
            )
            return await compose_available_tools(self._catalog, self._availability)

        if not hits:
            # Empty collection (e.g. embed_tools hasn't run yet)
            self._logger.debug(
                "Tool RAG returned 0 hits, falling back to full tools",
            )
            return await compose_available_tools(self._catalog, self._availability)

        # Collect tool names from hits
        hit_names: set[str] = set()
        for hit in hits:
            if hit.payload:
                name = hit.payload.get("tool_name", "")
                if name:
                    hit_names.add(name)

        # Build result from the cached OpenAI definitions
        async with self._catalog.lock:
            cache_snapshot = list(self._catalog.openai_cache)
            plugin_map = dict(self._catalog.tool_to_plugin)
            tools_snapshot = dict(self._catalog.tools)

        # Add priority plugin tools
        priority_plugins = set()
        if self._llm_config:
            priority_plugins = set(self._llm_config.priority_plugins)

        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Candidate plugins = owners of a hit tool or a priority-plugin tool.
        # Resolve their status once (deduped + bounded + cached) instead of
        # probing per tool, so a down plugin cannot stall selection.
        candidates: set[str] = set()
        for entry in cache_snapshot:
            ns_name = entry["function"]["name"]
            plugin_name = plugin_map.get(ns_name)
            if plugin_name is None:
                continue
            tool_def = tools_snapshot.get(ns_name)
            is_always = tool_def is not None and tool_def.always_offered
            if ns_name in hit_names or plugin_name in priority_plugins or is_always:
                candidates.add(plugin_name)
        statuses = await self._availability.resolve_plugin_statuses(candidates)

        # Second pass: keep hit / priority tools whose plugin is available.
        for entry in cache_snapshot:
            ns_name = entry["function"]["name"]
            plugin_name = plugin_map.get(ns_name)
            if plugin_name is None:
                continue

            is_hit = ns_name in hit_names
            is_priority = plugin_name in priority_plugins
            tool_def = tools_snapshot.get(ns_name)
            is_always = tool_def is not None and tool_def.always_offered
            if not is_hit and not is_priority and not is_always:
                continue

            if statuses.get(plugin_name) not in USABLE_STATUSES:
                continue

            if ns_name not in seen:
                result.append(entry)
                seen.add(ns_name)

        return result
