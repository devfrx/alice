"""AL\\CE — Tool catalog: what exists.

Aggregates tool definitions from all active plugins, validates and
namespaces them, and exposes O(1) lookups plus the OpenAI-format cache
consumed by the LLM client. Owns no availability/offer/execution logic —
see :mod:`backend.core.tools` for the full component breakdown.
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from loguru import logger

from backend.core.plugin_manager import PluginManager
from backend.core.plugin_models import (
    MAX_TOOL_DESCRIPTION_LENGTH,
    TOOL_NAME_PATTERN,
    ToolDefinition,
)


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


class ToolCatalog:
    """Aggregated, namespaced tool definitions from every loaded plugin.

    Holds the canonical ``_tools`` / ``_tool_to_plugin`` / ``_openai_cache``
    state and the lock that serialises rebuilds against readers. Other
    components (availability, policy, execution, rag) never mutate this
    state directly — they read it through :attr:`lock`, :attr:`tools`,
    :attr:`tool_to_plugin`, :attr:`openai_cache`, :meth:`definition` and
    :meth:`plugin_of`.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._tool_to_plugin: dict[str, str] = {}
        self._openai_cache: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._logger = logger.bind(component="ToolCatalog")

    # ------------------------------------------------------------------
    # Shared state accessors (used by sibling components)
    # ------------------------------------------------------------------

    @property
    def lock(self) -> asyncio.Lock:
        """The lock guarding catalog rebuilds — shared with sibling components."""
        return self._lock

    @property
    def tools(self) -> dict[str, ToolDefinition]:
        """Live namespaced-name → definition map (not a copy)."""
        return self._tools

    @property
    def tool_to_plugin(self) -> dict[str, str]:
        """Live namespaced-name → owning-plugin-name map (not a copy)."""
        return self._tool_to_plugin

    @property
    def openai_cache(self) -> list[dict[str, Any]]:
        """Live OpenAI-format tool cache (not a copy)."""
        return self._openai_cache

    def definition(self, ns_name: str) -> ToolDefinition | None:
        """Return the ``ToolDefinition`` for a namespaced tool name."""
        return self._tools.get(ns_name)

    def plugin_of(self, ns_name: str) -> str | None:
        """Return the owning plugin name for a namespaced tool name."""
        return self._tool_to_plugin.get(ns_name)

    # ------------------------------------------------------------------
    # Refresh / rebuild
    # ------------------------------------------------------------------

    async def refresh(self, plugin_manager: PluginManager) -> None:
        """Rebuild the internal registry from all active plugins.

        Iterates every loaded plugin, validates each tool definition,
        and stores them under a namespaced key.  Duplicate namespaced
        names across plugins raise ``ValueError``.
        """
        async with self._lock:
            new_tools: dict[str, ToolDefinition] = {}
            new_map: dict[str, str] = {}

            plugins = plugin_manager.get_all_plugins()

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
                        tool_def = dataclasses.replace(
                            tool_def, parameters=params,
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
        * ``capabilities``: the tool's capability tags (e.g. ``fs_write``,
          ``process_exec``) so the UI can reflect what a permission tier
          withholds.

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
                    "capabilities": list(tool_def.capabilities),
                }
            )
        return catalog
