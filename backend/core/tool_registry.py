"""O.M.N.I.A. — Tool registry (aggregation, validation, dispatch).

Collects tool definitions from all active plugins, validates and
namespaces them, and provides O(1) lookup plus timeout-enforced
execution with result sanitisation.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from loguru import logger

from backend.core.event_bus import EventBus, OmniaEvent
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
    ) -> None:
        self._plugin_manager = plugin_manager
        self._event_bus = event_bus

        self._tools: dict[str, ToolDefinition] = {}
        self._tool_to_plugin: dict[str, str] = {}
        self._openai_cache: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._logger = logger.bind(component="ToolRegistry")

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
                        )

                    # --- namespacing ---
                    ns_name = f"{safe_prefix}_{tool_def.name}"

                    # --- collision detection ---
                    if ns_name in new_tools:
                        existing_plugin = new_map[ns_name]
                        raise ValueError(
                            f"Tool name collision: '{ns_name}' "
                            f"registered by both "
                            f"'{existing_plugin}' and "
                            f"'{plugin_name}'"
                        )

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
        return list(self._openai_cache)

    async def get_available_tools(self) -> list[dict[str, Any]]:
        """Return tools whose owning plugin is not in ERROR state.

        Plugins with ``ConnectionStatus.ERROR`` are filtered out so
        the LLM is not offered tools that would certainly fail.

        Returns:
            Filtered list of OpenAI-format tool dicts.
        """
        available: list[dict[str, Any]] = []
        for entry in self._openai_cache:
            ns_name: str = entry["function"]["name"]
            plugin_name = self._tool_to_plugin.get(ns_name)
            if plugin_name is None:
                continue
            plugin = self._plugin_manager.get_plugin(plugin_name)
            if plugin is None:
                continue
            try:
                status = await plugin.get_connection_status()
            except Exception:
                continue
            if status != ConnectionStatus.ERROR:
                available.append(entry)
        return available

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
        execution_id = context.execution_id

        # --- lookup ---
        tool_def = self._tools.get(tool_name)
        if tool_def is None:
            return ToolResult.error(
                f"Tool '{tool_name}' not available: "
                "not found in registry"
            )

        plugin_name = self._tool_to_plugin.get(tool_name)
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
            OmniaEvent.TOOL_EXECUTION_START,
            tool_name=tool_name,
            execution_id=execution_id,
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
                OmniaEvent.TOOL_EXECUTION_FAILED,
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
                OmniaEvent.TOOL_EXECUTION_FAILED,
                tool_name=tool_name,
                execution_id=execution_id,
                error=str(exc),
            )
            return result

        elapsed_ms = (time.perf_counter() - start) * 1000
        result.execution_time_ms = elapsed_ms

        # --- sanitise & truncate ---
        if isinstance(result.content, str):
            result.content = _sanitise_content(result.content)
            if len(result.content) > MAX_TOOL_RESULT_LENGTH:
                result.content = (
                    result.content[:MAX_TOOL_RESULT_LENGTH]
                )
                result.truncated = True

        # --- emit success / failure ---
        if result.success:
            await self._event_bus.emit(
                OmniaEvent.TOOL_EXECUTION_SUCCEEDED,
                tool_name=tool_name,
                execution_id=execution_id,
                execution_time_ms=elapsed_ms,
            )
        else:
            await self._event_bus.emit(
                OmniaEvent.TOOL_EXECUTION_FAILED,
                tool_name=tool_name,
                execution_id=execution_id,
                error=result.error_message,
            )

        return result
