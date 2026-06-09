"""AL\\CE — Tool registry (aggregation, validation, dispatch).

Collects tool definitions from all active plugins, validates and
namespaces them, and provides O(1) lookup plus timeout-enforced
execution with result sanitisation.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import time
import uuid
from typing import Any

from backend.core.config import LLMConfig
from backend.core.protocols import EmbeddingClientProtocol, QdrantServiceProtocol
from backend.services.qdrant_service import COLLECTION_TOOLS, PROJECT_NS

from loguru import logger

try:
    import jsonschema as _jsonschema
except ImportError:
    _jsonschema = None  # type: ignore[assignment]
    logger.warning("jsonschema not installed — tool argument validation disabled")

from backend.core.event_bus import EventBus, AliceEvent
from backend.core.plugin_manager import PluginManager
from backend.core.plugin_models import (
    MAX_TOOL_DESCRIPTION_LENGTH,
    MAX_TOOL_RESULT_LENGTH,
    TOOL_NAME_PATTERN,
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)

# ---------------------------------------------------------------------------
# Sanitisation helpers
# ---------------------------------------------------------------------------

_TRACEBACK_RE: re.Pattern[str] = re.compile(
    r"Traceback \(most recent call last\):.*?(?=\n\S|\Z)",
    re.DOTALL,
)
_WIN_PATH_RE: re.Pattern[str] = re.compile(
    r"[A-Za-z]:\\(?:Users|Windows|Program Files)[^\s\"']*",
)
_UNIX_PATH_RE: re.Pattern[str] = re.compile(
    r"/(?:home|usr|tmp|var|etc)/[^\s\"']*",
)


def _format_schema_error(
    ve: Any,
    args: dict[str, Any],
    schema: dict[str, Any],
) -> str:
    """Render a jsonschema ValidationError into an LLM-actionable message.

    The default ``ve.message`` is too terse for small local models —
    e.g. ``'title' is a required property`` doesn't tell Gemma which
    keys it actually sent vs which are missing.  This helper enriches
    the error with the diff between provided and expected top-level
    keys whenever the failure is a missing-required at the root.

    Falls back to the bare ``ve.message`` for any non-trivial error.
    """
    try:
        message = str(ve.message)
        path = list(getattr(ve, "absolute_path", []) or [])
        validator = getattr(ve, "validator", None)
        if validator == "required" and not path and isinstance(args, dict):
            required = list(schema.get("required", []) or [])
            sent = sorted(args.keys())
            missing = [k for k in required if k not in args]
            return (
                f"{message}. Hai inviato keys={sent}, mancano: {missing}. "
                "Inserisci le chiavi mancanti come proprietà top-level "
                "dell'oggetto arguments (NON dentro echarts_option o altri "
                "oggetti annidati)."
            )
        if path:
            return f"{message} (path: {'.'.join(str(p) for p in path)})"
        return message
    except Exception:  # noqa: BLE001 — never block on formatting
        return str(getattr(ve, "message", ve))


def _sanitise_dict(obj: dict[str, Any]) -> dict[str, Any]:
    """Recursively sanitise string values in a dictionary."""
    cleaned: dict[str, Any] = {}
    for key, value in obj.items():
        if isinstance(value, str):
            cleaned[key] = _sanitise_content(value)
        elif isinstance(value, dict):
            cleaned[key] = _sanitise_dict(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _sanitise_content(v) if isinstance(v, str)
                else _sanitise_dict(v) if isinstance(v, dict)
                else v
                for v in value
            ]
        else:
            cleaned[key] = value
    return cleaned


def _deep_copy_content(
    content: str | dict | list | None,
) -> str | dict | list | None:
    """Return a deep copy of *content* preserving its original shape.

    Used to snapshot a tool's payload before sanitisation so consumers
    that need un-redacted data (e.g. the artifact registry) can keep
    operating on the real values while the LLM-facing copy is scrubbed.
    """
    if content is None or isinstance(content, str):
        return content
    return copy.deepcopy(content)


def _sanitise_content(text: str) -> str:
    """Strip tracebacks and internal filesystem paths from *text*.

    Args:
        text: Raw tool output string.

    Returns:
        Cleaned string with sensitive details removed.
    """
    text = _TRACEBACK_RE.sub("[traceback removed]", text)
    text = _WIN_PATH_RE.sub("[path removed]", text)
    text = _UNIX_PATH_RE.sub("[path removed]", text)
    return text


def _validate_json_schema(schema: Any) -> dict[str, Any]:
    """Return *schema* if it looks like a valid JSON Schema object.

    Args:
        schema: Candidate JSON Schema dict.

    Returns:
        The original schema when valid, otherwise a safe fallback.
    """
    if (
        isinstance(schema, dict)
        and isinstance(schema.get("type"), str)
    ):
        return schema
    return {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Central registry aggregating tools from all loaded plugins.

    Provides O(1) dispatch by namespaced tool name, timeout enforcement,
    result truncation / sanitisation, and event-bus notifications.

    Args:
        plugin_manager: The plugin manager supplying loaded plugins.
        event_bus: The event bus for emitting execution events.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        event_bus: EventBus,
        *,
        qdrant_service: QdrantServiceProtocol | None = None,
        embedding_client: EmbeddingClientProtocol | None = None,
        llm_config: LLMConfig | None = None,
    ) -> None:
        self._plugin_manager = plugin_manager
        self._event_bus = event_bus

        self._tools: dict[str, ToolDefinition] = {}
        self._tool_to_plugin: dict[str, str] = {}
        self._openai_cache: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._logger = logger.bind(component="ToolRegistry")

        self._qdrant = qdrant_service
        self._embedder = embedding_client
        self._llm_config = llm_config

        # Per-plugin connection-status cache: name -> (monotonic_ts, status).
        # Tool selection resolves each plugin's status ONCE per call, bounded
        # by a timeout and reused within a short TTL, so a slow/down plugin
        # (e.g. continuum probing a dead endpoint) cannot stall a turn.
        self._status_cache: dict[str, tuple[float, ConnectionStatus]] = {}
        self._status_cache_ttl: float = 30.0
        self._status_probe_timeout: float = 3.0

    # ------------------------------------------------------------------
    # Refresh / rebuild
    # ------------------------------------------------------------------

    async def refresh(self) -> None:
        """Rebuild the internal registry from all active plugins.

        Iterates every loaded plugin, validates each tool definition,
        and stores them under a namespaced key.  Duplicate namespaced
        names across plugins raise ``ValueError``.
        """
        async with self._lock:
            new_tools: dict[str, ToolDefinition] = {}
            new_map: dict[str, str] = {}

            plugins = self._plugin_manager.get_all_plugins()

            for plugin_name, plugin in plugins.items():
                safe_prefix = plugin_name.replace(".", "_")

                try:
                    definitions = plugin.get_tools()
                except Exception as exc:
                    self._logger.error(
                        "Plugin '{}' get_tools() failed: {}",
                        plugin_name,
                        exc,
                    )
                    continue

                for tool_def in definitions:
                    # --- name validation ---
                    if not TOOL_NAME_PATTERN.match(tool_def.name):
                        self._logger.error(
                            "Plugin '{}': tool '{}' has invalid name"
                            " — skipping",
                            plugin_name,
                            tool_def.name,
                        )
                        continue

                    # --- description validation ---
                    if len(tool_def.description) > MAX_TOOL_DESCRIPTION_LENGTH:
                        self._logger.error(
                            "Plugin '{}': tool '{}' description "
                            "exceeds {} chars — skipping",
                            plugin_name,
                            tool_def.name,
                            MAX_TOOL_DESCRIPTION_LENGTH,
                        )
                        continue
                    if len(tool_def.description) > 512:
                        self._logger.warning(
                            "Plugin '{}': tool '{}' description is "
                            "{} chars (recommended ≤512)",
                            plugin_name,
                            tool_def.name,
                            len(tool_def.description),
                        )

                    # --- parameters validation ---
                    params = _validate_json_schema(tool_def.parameters)
                    if params is not tool_def.parameters:
                        self._logger.warning(
                            "Plugin '{}': tool '{}' has invalid "
                            "parameters schema — using fallback",
                            plugin_name,
                            tool_def.name,
                        )
                        tool_def = ToolDefinition(
                            name=tool_def.name,
                            description=tool_def.description,
                            parameters=params,
                            result_type=tool_def.result_type,
                            supports_cancellation=(
                                tool_def.supports_cancellation
                            ),
                            timeout_ms=tool_def.timeout_ms,
                            requires_confirmation=(
                                tool_def.requires_confirmation
                            ),
                            risk_level=tool_def.risk_level,
                            sanitise_output=tool_def.sanitise_output,
                            max_result_chars=tool_def.max_result_chars,
                        )

                    # --- namespacing ---
                    ns_name = f"{safe_prefix}_{tool_def.name}"

                    # --- collision detection ---
                    if ns_name in new_tools:
                        existing_plugin = new_map[ns_name]
                        self._logger.warning(
                            "Tool name collision: '{}' registered by both "
                            "'{}' and '{}' — skipping duplicate",
                            ns_name, existing_plugin, plugin_name,
                        )
                        continue

                    new_tools[ns_name] = tool_def
                    new_map[ns_name] = plugin_name

            # Build OpenAI cache with namespaced names
            cache: list[dict[str, Any]] = []
            for ns_name, tool_def in new_tools.items():
                fmt = tool_def.to_openai_format()
                fmt["function"]["name"] = ns_name
                cache.append(fmt)

            self._tools = new_tools
            self._tool_to_plugin = new_map
            self._openai_cache = cache

            self._logger.info(
                "Tool registry refreshed: {} tools from {} plugins",
                len(self._tools),
                len(plugins),
            )

        # Embed tools for Tool RAG
        if self._qdrant and self._embedder:
            try:
                await self.embed_tools()
            except Exception as exc:
                self._logger.warning("Tool embedding failed: {}", exc)

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

    def clear_status_cache(self) -> None:
        """Drop all cached plugin connection statuses (force a fresh probe).

        Called after the knowledge stack is re-wired so plugins whose backing
        service just changed (e.g. ``memory`` after a Qdrant repair) are
        re-evaluated instead of serving a stale cached status.
        """
        self._status_cache.clear()

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Return all registered tools in OpenAI function-calling format.

        Returns:
            List of tool dicts (shallow copy).
        """
        # _openai_cache is replaced atomically in refresh(); a snapshot
        # via list() is safe without the async lock in sync context.
        return list(self._openai_cache)

    async def _resolve_plugin_statuses(
        self, plugin_names: set[str],
    ) -> dict[str, ConnectionStatus]:
        """Resolve each plugin's connection status once — bounded and cached.

        Within a call each plugin is probed at most once (deduped across its
        many tools); probes for distinct plugins run concurrently and are each
        capped by :attr:`_status_probe_timeout`, so a hanging health check
        (e.g. an HTTP probe to a service that is down) cannot stall the turn.
        Results are cached for :attr:`_status_cache_ttl` seconds so
        back-to-back turns reuse them instead of re-probing.

        Args:
            plugin_names: Owning-plugin names to resolve a status for.

        Returns:
            Mapping of plugin name to its (possibly cached) status.
        """
        now = time.monotonic()
        statuses: dict[str, ConnectionStatus] = {}
        stale: list[str] = []
        for name in plugin_names:
            cached = self._status_cache.get(name)
            if cached is not None and (now - cached[0]) < self._status_cache_ttl:
                statuses[name] = cached[1]
            else:
                stale.append(name)

        if stale:
            probed = await asyncio.gather(
                *(self._probe_plugin_status(name) for name in stale)
            )
            probe_ts = time.monotonic()
            for name, status in zip(stale, probed, strict=True):
                self._status_cache[name] = (probe_ts, status)
                statuses[name] = status

        return statuses

    async def _probe_plugin_status(self, plugin_name: str) -> ConnectionStatus:
        """Probe one plugin's status, bounded by :attr:`_status_probe_timeout`.

        Returns ``DISCONNECTED`` on a missing plugin, a timeout, or any error
        so callers treat the plugin as unavailable instead of blocking.
        """
        plugin = self._plugin_manager.get_plugin(plugin_name)
        if plugin is None:
            return ConnectionStatus.DISCONNECTED
        try:
            return await asyncio.wait_for(
                plugin.get_connection_status(),
                timeout=self._status_probe_timeout,
            )
        except TimeoutError:
            self._logger.warning(
                "Connection-status probe for plugin '{}' timed out after "
                "{:.1f}s — treating it as disconnected",
                plugin_name, self._status_probe_timeout,
            )
            return ConnectionStatus.DISCONNECTED
        except Exception as exc:  # noqa: BLE001 — never block selection
            self._logger.debug(
                "Connection-status probe for plugin '{}' failed: {}",
                plugin_name, exc,
            )
            return ConnectionStatus.DISCONNECTED

    async def get_available_tools(self) -> list[dict[str, Any]]:
        """Return tools whose owning plugin is CONNECTED, DEGRADED or UNKNOWN.

        Plugins reporting ``DISCONNECTED`` / ``ERROR`` (or whose status probe
        times out) are filtered out so the LLM is not offered tools that would
        certainly fail at execution time.  Status is resolved once per plugin
        via :meth:`_resolve_plugin_statuses` (bounded + cached), never once per
        tool.

        Returns:
            Filtered list of OpenAI-format tool dicts.
        """
        async with self._lock:
            cache_snapshot = list(self._openai_cache)
            plugin_map_snapshot = dict(self._tool_to_plugin)

        plugin_names = {p for p in plugin_map_snapshot.values() if p}
        statuses = await self._resolve_plugin_statuses(plugin_names)

        available: list[dict[str, Any]] = []
        for entry in cache_snapshot:
            ns_name: str = entry["function"]["name"]
            plugin_name = plugin_map_snapshot.get(ns_name)
            if plugin_name is None:
                continue
            if statuses.get(plugin_name) in (
                ConnectionStatus.CONNECTED,
                ConnectionStatus.DEGRADED,
                ConnectionStatus.UNKNOWN,
            ):
                available.append(entry)
        return available

    async def get_tools_for_plugins(
        self, plugin_names: set[str],
    ) -> list[dict[str, Any]]:
        """Return all available tools owned by the given plugins.

        Unlike tool RAG, this returns the *complete* tool set for the
        requested plugins with no relevance filtering, so callers that
        need a fixed, always-injected toolset (e.g. a scoped agent) get
        reliable, deterministic results. Connection-status filtering from
        :meth:`get_available_tools` still applies.

        Args:
            plugin_names: Plugin names whose tools should be returned.

        Returns:
            Filtered list of OpenAI-format tool dicts.
        """
        if not plugin_names:
            return []
        async with self._lock:
            plugin_map_snapshot = dict(self._tool_to_plugin)
        available = await self.get_available_tools()
        return [
            entry
            for entry in available
            if plugin_map_snapshot.get(entry["function"]["name"])
            in plugin_names
        ]

    def limit_tools(
        self,
        tools: list[dict[str, Any]],
        max_tools: int,
        priority_plugins: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Cap *tools* to *max_tools*, prioritising certain plugins.

        Tools from *priority_plugins* are always included first.
        Remaining slots are filled in the order the other tools appear.

        Args:
            tools: Full list of available tools (OpenAI format).
            max_tools: Maximum number to return.  ``0`` disables limiting.
            priority_plugins: Plugin names whose tools have priority.

        Returns:
            A (possibly shorter) list of tool dicts.
        """
        if max_tools <= 0 or len(tools) <= max_tools:
            return tools

        prio = set(priority_plugins or [])
        priority: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []

        for entry in tools:
            ns_name: str = entry["function"]["name"]
            plugin_name = self._tool_to_plugin.get(ns_name)
            if plugin_name in prio:
                priority.append(entry)
            else:
                rest.append(entry)

        # Priority tools always included; fill remainder from rest.
        remaining_slots = max(0, max_tools - len(priority))
        limited = priority + rest[:remaining_slots]

        if len(limited) < len(tools):
            self._logger.info(
                "Tool limit applied: {} → {} tools (priority plugins: {})",
                len(tools),
                len(limited),
                ", ".join(sorted(prio)) if prio else "none",
            )

        return limited

    def get_tool_plugin(self, tool_name: str) -> str | None:
        """Return the plugin name that owns *tool_name*.

        Args:
            tool_name: Namespaced tool name.

        Returns:
            Plugin name string or ``None`` if not found.
        """
        return self._tool_to_plugin.get(tool_name)

    def get_tool_definition(self, tool_name: str) -> ToolDefinition | None:
        """Return the ``ToolDefinition`` for *tool_name*.

        Args:
            tool_name: Namespaced tool name.

        Returns:
            The tool definition or ``None`` if not registered.
        """
        return self._tools.get(tool_name)

    def get_tool_catalog(self) -> list[dict[str, Any]]:
        """Return every registered tool grouped-ready for the chat UI.

        Produces a flat list of lightweight descriptors so the frontend
        can render a plugin → tools picker without pulling the full
        OpenAI schemas. Each entry contains:

        * ``plugin``: owning plugin name.
        * ``name``: namespaced tool name (the value stored in
          :attr:`LLMConfig.disabled_tools`).
        * ``label``: bare tool name for display.
        * ``description``: human-readable tool description.

        Returns:
            One descriptor dict per registered tool.
        """
        catalog: list[dict[str, Any]] = []
        for ns_name, tool_def in self._tools.items():
            catalog.append(
                {
                    "plugin": self._tool_to_plugin.get(ns_name, ""),
                    "name": ns_name,
                    "label": tool_def.name,
                    "description": tool_def.description,
                }
            )
        return catalog

    def exclude_disabled(
        self,
        tools: list[dict[str, Any]],
        disabled_names: set[str],
    ) -> list[dict[str, Any]]:
        """Drop tools whose namespaced name is in *disabled_names*.

        Used to apply the user's per-chat tool selection (opt-out) on
        top of the available toolset. A no-op when *disabled_names* is
        empty so default behaviour is preserved.

        Args:
            tools: OpenAI-format tool dicts (e.g. from
                :meth:`get_available_tools`).
            disabled_names: Namespaced tool names to remove.

        Returns:
            The filtered list (a new list; the input is not mutated).
        """
        if not disabled_names:
            return tools
        return [
            entry
            for entry in tools
            if entry["function"]["name"] not in disabled_names
        ]

    def apply_mode_policy(
        self,
        tools: list[dict[str, Any]],
        *,
        drop_capabilities: frozenset[str] | set[str] = frozenset(),
        always_allow_tools: frozenset[str] = frozenset(),
        priority_plugins: tuple[str, ...] | list[str] = (),
    ) -> list[dict[str, Any]]:
        """Reshape *tools* to match the active permission tier.

        Two capability-/plugin-driven transforms, applied in order:

        * **drop** — remove every tool whose definition declares any capability
          in *drop_capabilities* (e.g. ``fs_write`` / ``process_exec`` in the
          read-only ``plan`` tier).  Withholding the tools the gate would deny
          anyway keeps the model from leading with an action it cannot take.  A
          tool whose namespaced name is in *always_allow_tools* is exempt — it
          survives even when its capabilities intersect *drop_capabilities*, so
          the tier can guarantee its own meta-tools.
        * **prioritise** — float tools owned by *priority_plugins* to the front
          (stable within each group) so the model reaches for them first (e.g.
          the planning meta-tools in ``plan`` mode).

        The input list is never mutated; a new list is returned (or the input
        unchanged when both transforms are no-ops).  A tool whose definition
        cannot be resolved is treated as capability-less — never dropped.

        Args:
            tools: OpenAI-format tool dicts (e.g. from the selection branch).
            drop_capabilities: Capability tags whose tools are removed.
            always_allow_tools: Namespaced tool names exempt from dropping.
            priority_plugins: Owning-plugin names floated to the front.

        Returns:
            The reshaped tool list.
        """
        if not tools:
            return tools

        result = tools
        if drop_capabilities:
            drop = frozenset(drop_capabilities)
            kept: list[dict[str, Any]] = []
            for entry in result:
                ns_name = entry.get("function", {}).get("name", "")
                if ns_name in always_allow_tools:
                    kept.append(entry)
                    continue
                tool_def = self._tools.get(ns_name)
                caps = set(tool_def.capabilities) if tool_def is not None else set()
                if caps & drop:
                    continue
                kept.append(entry)
            result = kept

        prio = set(priority_plugins or ())
        if prio:
            front: list[dict[str, Any]] = []
            rest: list[dict[str, Any]] = []
            for entry in result:
                ns_name = entry.get("function", {}).get("name", "")
                if self._tool_to_plugin.get(ns_name) in prio:
                    front.append(entry)
                else:
                    rest.append(entry)
            result = front + rest

        return result

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

        async with self._lock:
            tools_snapshot = dict(self._tools)
            plugin_map_snapshot = dict(self._tool_to_plugin)

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
        points: list[Any] = []
        for ns_name, vector in zip(names, vectors):
            from qdrant_client import models as qmodels
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
        Always includes tools from priority plugins.

        Args:
            query: User message to match tools against.
            k: Maximum number of tools to return.

        Returns:
            OpenAI-format tool definitions.
        """
        if not self._qdrant or not self._embedder:
            return await self.get_available_tools()

        try:
            vector = await self._embedder.encode(query)
        except Exception as exc:
            self._logger.warning(
                "Embedding failed, falling back to full tools: {}", exc,
            )
            return await self.get_available_tools()

        try:
            hits = await self._qdrant.search(
                COLLECTION_TOOLS, vector, k=k,
            )
        except Exception as exc:
            self._logger.warning(
                "Qdrant search failed, falling back to full tools: {}", exc,
            )
            return await self.get_available_tools()

        if not hits:
            # Empty collection (e.g. embed_tools hasn't run yet)
            self._logger.debug(
                "Tool RAG returned 0 hits, falling back to full tools",
            )
            return await self.get_available_tools()

        # Collect tool names from hits
        hit_names: set[str] = set()
        for hit in hits:
            if hit.payload:
                name = hit.payload.get("tool_name", "")
                if name:
                    hit_names.add(name)

        # Build result from the cached OpenAI definitions
        async with self._lock:
            cache_snapshot = list(self._openai_cache)
            plugin_map = dict(self._tool_to_plugin)

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
            if ns_name in hit_names or plugin_name in priority_plugins:
                candidates.add(plugin_name)
        statuses = await self._resolve_plugin_statuses(candidates)

        # Second pass: keep hit / priority tools whose plugin is available.
        for entry in cache_snapshot:
            ns_name = entry["function"]["name"]
            plugin_name = plugin_map.get(ns_name)
            if plugin_name is None:
                continue

            is_hit = ns_name in hit_names
            is_priority = plugin_name in priority_plugins
            if not is_hit and not is_priority:
                continue

            if statuses.get(plugin_name) not in (
                ConnectionStatus.CONNECTED,
                ConnectionStatus.DEGRADED,
                ConnectionStatus.UNKNOWN,
            ):
                continue

            if ns_name not in seen:
                result.append(entry)
                seen.add(ns_name)

        return result

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_args(
        args: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Best-effort coercion of LLM-provided args to match the schema.

        LLMs frequently send a dict/list where a string is expected,
        or a numeric string where a number is required. This method
        patches the args dict in-place to avoid repeated validation
        failures that waste iterations.
        """
        props = schema.get("properties", {})
        for key, prop_schema in props.items():
            if key not in args:
                continue
            expected = prop_schema.get("type")
            val = args[key]

            if expected == "string" and not isinstance(val, str):
                # dict/list/int/float → JSON string
                args[key] = json.dumps(val, ensure_ascii=False)
            elif expected in ("number", "integer") and isinstance(val, str):
                try:
                    args[key] = (
                        int(val) if expected == "integer" else float(val)
                    )
                except (ValueError, TypeError):
                    pass  # leave as-is; validation will catch it
            elif expected == "boolean" and not isinstance(val, bool):
                # LLMs often send "true"/"false" strings or 0/1 ints
                if isinstance(val, str):
                    lower = val.strip().lower()
                    if lower in ("true", "1", "yes"):
                        args[key] = True
                    elif lower in ("false", "0", "no"):
                        args[key] = False
                elif isinstance(val, (int, float)):
                    args[key] = bool(val)
            elif expected == "array" and isinstance(val, str):
                # LLMs sometimes send a JSON-encoded array as a string
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        args[key] = parsed
                except (json.JSONDecodeError, ValueError):
                    pass  # leave as-is; validation will catch it
            elif expected == "object" and isinstance(val, str):
                # LLMs sometimes send a JSON-encoded object as a string
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, dict):
                        args[key] = parsed
                except (json.JSONDecodeError, ValueError):
                    pass  # leave as-is; validation will catch it
        return args

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Execute a tool by its namespaced name.

        Wraps the underlying plugin call with timeout enforcement,
        result truncation, content sanitisation, and event-bus
        notifications.

        Args:
            tool_name: Namespaced tool identifier.
            args: Arguments to pass to the tool.
            context: Execution context with session/conversation IDs.

        Returns:
            A ``ToolResult`` — never raises an exception.
        """
        execution_id = context.execution_id

        # --- snapshot under lock to avoid TOCTOU with refresh() ---
        async with self._lock:
            tool_def = self._tools.get(tool_name)
            plugin_name = self._tool_to_plugin.get(tool_name)

            # Fallback: LLMs sometimes drop the "<plugin>_" prefix and
            # emit the bare tool name (e.g. "remember" instead of
            # "memory_remember").  Resolve by unique suffix match.
            if tool_def is None:
                suffix = f"_{tool_name}"
                candidates = [
                    ns for ns in self._tools
                    if ns == tool_name or ns.endswith(suffix)
                ]
                if len(candidates) == 1:
                    resolved = candidates[0]
                    self._logger.info(
                        "Tool '{}' resolved to namespaced '{}' "
                        "(bare-name fallback)",
                        tool_name, resolved,
                    )
                    tool_name = resolved
                    tool_def = self._tools.get(resolved)
                    plugin_name = self._tool_to_plugin.get(resolved)
                elif len(candidates) > 1:
                    return ToolResult.error(
                        f"Tool '{tool_name}' is ambiguous: matches "
                        f"{candidates!r} \u2014 use the full namespaced name"
                    )

        if tool_def is None:
            return ToolResult.error(
                f"Tool '{tool_name}' not available: "
                "not found in registry"
            )

        if plugin_name is None:
            return ToolResult.error(
                f"Tool '{tool_name}' not available: "
                "no owning plugin"
            )

        plugin = self._plugin_manager.get_plugin(plugin_name)
        if plugin is None:
            return ToolResult.error(
                f"Tool '{tool_name}' not available: "
                f"plugin '{plugin_name}' is not loaded"
            )

        # --- emit start event ---
        await self._event_bus.emit(
            AliceEvent.TOOL_EXECUTION_START,
            tool_name=tool_name,
            execution_id=execution_id,
        )

        # --- auto-coerce LLM args to match expected types ---
        args = self._coerce_args(args, tool_def.parameters)

        # --- validate args against JSON Schema ---
        if _jsonschema is not None:
            try:
                _jsonschema.validate(instance=args, schema=tool_def.parameters)
            except _jsonschema.ValidationError as ve:
                detail = _format_schema_error(ve, args, tool_def.parameters)
                self._logger.warning(
                    "Tool '{}' args validation failed: {}",
                    tool_name, detail,
                )
                await self._event_bus.emit(
                    AliceEvent.TOOL_EXECUTION_FAILED,
                    tool_name=tool_name,
                    execution_id=execution_id,
                    error=f"Invalid arguments: {detail}",
                )
                return ToolResult.error(
                    f"Tool '{tool_name}' argument validation failed: {detail}"
                )
            except _jsonschema.SchemaError:
                # Schema itself is malformed — log but don't block execution
                self._logger.warning(
                    "Tool '{}' has invalid JSON schema — skipping validation",
                    tool_name,
                )

        start = time.perf_counter()
        timeout_s = tool_def.timeout_ms / 1000.0

        try:
            result: ToolResult = await asyncio.wait_for(
                plugin.execute_tool(
                    tool_def.name, args, context,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            elapsed_ms = (time.perf_counter() - start) * 1000
            result = ToolResult.error(
                f"Tool '{tool_name}' timed out after "
                f"{tool_def.timeout_ms}ms",
                execution_time_ms=elapsed_ms,
            )
            await self._event_bus.emit(
                AliceEvent.TOOL_EXECUTION_FAILED,
                tool_name=tool_name,
                execution_id=execution_id,
                error=result.error_message,
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            result = ToolResult.error(
                f"Tool '{tool_name}' raised an unexpected error",
                execution_time_ms=elapsed_ms,
            )
            self._logger.error(
                "Tool '{}' execution error: {}", tool_name, exc,
            )
            await self._event_bus.emit(
                AliceEvent.TOOL_EXECUTION_FAILED,
                tool_name=tool_name,
                execution_id=execution_id,
                error=str(exc),
            )
            return result

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.execution_time_ms = elapsed_ms

        # Snapshot the un-sanitised payload so downstream consumers (e.g.
        # the artifact registry) can still see the real file paths even
        # when ``sanitise_output`` is enabled for LLM-facing content.
        result.raw_content = _deep_copy_content(result.content)

        # --- sanitise (conditional) ---
        if tool_def.sanitise_output:
            if isinstance(result.content, str):
                result.content = _sanitise_content(result.content)
            elif isinstance(result.content, dict):
                result.content = _sanitise_dict(result.content)
            elif isinstance(result.content, list):
                result.content = [
                    _sanitise_content(v) if isinstance(v, str)
                    else _sanitise_dict(v) if isinstance(v, dict)
                    else v
                    for v in result.content
                ]

        # --- truncate (always active, except binary content) ---
        is_binary = (
            result.content_type is not None
            and result.content_type.startswith("image/")
        )
        limit = tool_def.max_result_chars
        if isinstance(result.content, str) and not is_binary:
            if len(result.content) > limit:
                result.content = (
                    result.content[:max(0, limit - 30)]
                    + "\n...[output truncated]"
                )
                result.truncated = True
        elif isinstance(result.content, list) and not is_binary:
            serialized = json.dumps(result.content, ensure_ascii=False)
            if len(serialized) > limit:
                result.content = serialized[:max(0, limit - 30)] + (
                    "\n...[output truncated]"
                )
                result.truncated = True

        # --- emit success / failure ---
        if result.success:
            await self._event_bus.emit(
                AliceEvent.TOOL_EXECUTION_SUCCEEDED,
                tool_name=tool_name,
                execution_id=execution_id,
                execution_time_ms=elapsed_ms,
            )
        else:
            await self._event_bus.emit(
                AliceEvent.TOOL_EXECUTION_FAILED,
                tool_name=tool_name,
                execution_id=execution_id,
                error=result.error_message,
            )

        return result
