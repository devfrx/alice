"""AL\\CE — Tool registry (facade over ``backend.core.tools``).

``ToolRegistry`` is the single object every consumer (turn executor, chat
assembly, plugins) depends on for tool aggregation, selection and
dispatch. Internally it composes five focused components under
``backend.core.tools``:

- :class:`~backend.core.tools.catalog.ToolCatalog` — what exists.
- :class:`~backend.core.tools.availability.AvailabilityProbe` — what is
  reachable.
- :mod:`backend.core.tools.policy` — what is offered (pure functions).
- :class:`~backend.core.tools.execution.ToolExecutor` — dispatch.
- :class:`~backend.core.tools.rag.ToolRag` — semantic tool retrieval.

This module keeps the historical public API (constructor signature and
every method) unchanged so existing consumers and tests need no update.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from backend.core.config import LLMConfig
from backend.core.event_bus import EventBus
from backend.core.plugin_manager import PluginManager
from backend.core.plugin_models import (
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.core.protocols import EmbeddingClientProtocol, QdrantServiceProtocol
from backend.core.tools import AvailabilityProbe, ToolCatalog, ToolExecutor, ToolRag
from backend.core.tools import policy as _policy
from backend.core.tools.availability import compose_available_tools
from backend.core.tools.catalog import KernelToolHandler

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
        self._logger = logger.bind(component="ToolRegistry")

        self._catalog = ToolCatalog()
        self._availability = AvailabilityProbe(plugin_manager)
        self._executor = ToolExecutor(self._catalog, plugin_manager, event_bus)
        self._rag = ToolRag(self._catalog, self._availability, llm_config=llm_config)
        self._rag.set_vector_backends(qdrant_service, embedding_client)

    # ------------------------------------------------------------------
    # Test-compat aliases for private state (backlog: migrate tests off
    # these and drop the aliases — see tests/test_tool_registry.py,
    # tests/test_tool_status_caching.py, tests/test_permission_mode_policy.py).
    # ------------------------------------------------------------------

    @property
    def _tools(self) -> dict[str, ToolDefinition]:
        return self._catalog.tools

    @_tools.setter
    def _tools(self, value: dict[str, ToolDefinition]) -> None:
        self._catalog._tools = value

    @property
    def _tool_to_plugin(self) -> dict[str, str]:
        return self._catalog.tool_to_plugin

    @_tool_to_plugin.setter
    def _tool_to_plugin(self, value: dict[str, str]) -> None:
        self._catalog._tool_to_plugin = value

    @property
    def _status_probe_timeout(self) -> float:
        return self._availability._status_probe_timeout

    @_status_probe_timeout.setter
    def _status_probe_timeout(self, value: float) -> None:
        self._availability._status_probe_timeout = value

    # ------------------------------------------------------------------
    # Refresh / rebuild
    # ------------------------------------------------------------------

    async def refresh(self) -> None:
        """Rebuild the internal registry from all active plugins.

        Iterates every loaded plugin, validates each tool definition,
        and stores them under a namespaced key.  Duplicate namespaced
        names across plugins are skipped with a warning (first
        registration wins).
        """
        await self._catalog.refresh(self._plugin_manager)

        # Embed tools for Tool RAG
        if self._rag.has_vector_backends:
            try:
                await self._rag.embed_tools()
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
        self._rag.set_vector_backends(qdrant_service, embedding_client)

    def clear_status_cache(self) -> None:
        """Drop all cached plugin connection statuses (force a fresh probe).

        Called after the knowledge stack is re-wired so plugins whose backing
        service just changed (e.g. ``memory`` after a Qdrant repair) are
        re-evaluated instead of serving a stale cached status.
        """
        self._availability.clear_status_cache()

    async def register_kernel_tool(
        self, tool_def: ToolDefinition, handler: KernelToolHandler,
    ) -> None:
        """Register (or replace) a kernel-owned tool (spec §7: app_command)."""
        await self._catalog.register_kernel_tool(tool_def, handler)

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Return all registered tools in OpenAI function-calling format.

        Returns:
            List of tool dicts (shallow copy).
        """
        return self._catalog.get_all_tools()

    async def get_available_tools(self) -> list[dict[str, Any]]:
        """Return tools whose owning plugin is CONNECTED, DEGRADED or UNKNOWN.

        Plugins reporting ``DISCONNECTED`` / ``ERROR`` (or whose status probe
        times out) are filtered out so the LLM is not offered tools that would
        certainly fail at execution time.  Status is resolved once per plugin
        via :meth:`AvailabilityProbe.resolve_plugin_statuses` (bounded +
        cached), never once per tool.

        Returns:
            Filtered list of OpenAI-format tool dicts.
        """
        return await compose_available_tools(self._catalog, self._availability)

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
        async with self._catalog.lock:
            plugin_map_snapshot = dict(self._catalog.tool_to_plugin)
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

        Tools from *priority_plugins* are always included first. Tools
        whose definition declares ``always_offered`` are treated as
        priority and never cut. Remaining slots are filled in the order
        the other tools appear.

        Args:
            tools: Full list of available tools (OpenAI format).
            max_tools: Maximum number to return.  ``0`` disables limiting.
            priority_plugins: Plugin names whose tools have priority.

        Returns:
            A (possibly shorter) list of tool dicts.
        """
        return _policy.limit_tools(
            tools, max_tools, catalog=self._catalog, priority_plugins=priority_plugins,
        )

    def get_tool_plugin(self, tool_name: str) -> str | None:
        """Return the plugin name that owns *tool_name*.

        Args:
            tool_name: Namespaced tool name.

        Returns:
            Plugin name string or ``None`` if not found.
        """
        return self._catalog.get_tool_plugin(tool_name)

    def get_tool_definition(self, tool_name: str) -> ToolDefinition | None:
        """Return the ``ToolDefinition`` for *tool_name*.

        Args:
            tool_name: Namespaced tool name.

        Returns:
            The tool definition or ``None`` if not registered.
        """
        return self._catalog.get_tool_definition(tool_name)

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
        * ``capabilities``: the tool's capability tags (e.g. ``fs_write``,
          ``process_exec``) so the UI can reflect what a permission tier
          withholds.

        Returns:
            One descriptor dict per registered tool.
        """
        return self._catalog.get_tool_catalog()

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
        return _policy.exclude_disabled(tools, disabled_names)

    def usage_guidance_for(self, tools: list[dict[str, Any]]) -> list[str]:
        """Collect usage-guidance fragments for an offered toolset.

        Given the FINAL OpenAI-format toolset of a turn (after tool RAG,
        limiting, mode policy and the user's opt-out), return the
        non-empty ``usage_guidance`` fragments of those tools, in toolset
        order, de-duplicated. The prompt composer renders these into the
        ``[ORCHESTRAZIONE]`` system-prompt block — so the prompt only
        ever teaches tools the model can actually call this turn.

        Args:
            tools: OpenAI-format tool dicts offered to the LLM.

        Returns:
            Ordered, de-duplicated guidance fragments (possibly empty).
        """
        fragments: list[str] = []
        seen: set[str] = set()
        for entry in tools:
            ns_name = entry.get("function", {}).get("name", "")
            tool_def = self._catalog.definition(ns_name)
            if tool_def is None or not tool_def.usage_guidance:
                continue
            text = tool_def.usage_guidance.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            fragments.append(text)
        return fragments

    def apply_mode_policy(
        self,
        tools: list[dict[str, Any]],
        *,
        drop_capabilities: frozenset[str] | set[str] = frozenset(),
        priority_plugins: tuple[str, ...] | list[str] = (),
    ) -> list[dict[str, Any]]:
        """Reshape *tools* to match the active permission tier.

        Two capability-/plugin-driven transforms, applied in order:

        * **drop** — remove every tool whose definition declares any capability
          in *drop_capabilities* (e.g. ``fs_write`` / ``process_exec`` in the
          read-only ``plan`` tier).  Withholding the tools the gate would deny
          anyway keeps the model from leading with an action it cannot take.  A
          tool whose definition declares ``always_offered`` is exempt: it
          survives even when its capabilities intersect *drop_capabilities*,
          so the meta-tools can never be withheld.
        * **prioritise** — float tools owned by *priority_plugins* to the front
          (stable within each group) so the model reaches for them first (e.g.
          the planning meta-tools in ``plan`` mode).

        The input list is never mutated; a new list is returned (or the input
        unchanged when both transforms are no-ops).  A tool whose definition
        cannot be resolved is treated as capability-less — never dropped.

        Args:
            tools: OpenAI-format tool dicts (e.g. from the selection branch).
            drop_capabilities: Capability tags whose tools are removed.
            priority_plugins: Owning-plugin names floated to the front.

        Returns:
            The reshaped tool list.
        """
        return _policy.apply_mode_policy(
            tools,
            catalog=self._catalog,
            drop_capabilities=drop_capabilities,
            priority_plugins=priority_plugins,
        )

    # ------------------------------------------------------------------
    # Tool RAG — embed & retrieve
    # ------------------------------------------------------------------

    async def embed_tools(self) -> None:
        """Embed all registered tools into Qdrant for Tool RAG.

        Each tool is represented as:
        ``"{name}: {description}. params: {param1, param2, ...}"``
        """
        await self._rag.embed_tools()

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
        return await self._rag.get_relevant_tools(query, k)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

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
        return await self._executor.execute_tool(tool_name, args, context)
