"""AL\\CE — Tool registry (aggregation, validation, dispatch).

Collects tool definitions from all active plugins, validates and
namespaces them, and provides O(1) lookup plus timeout-enforced
execution with result sanitisation.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

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

    async def get_available_tools(self) -> list[dict[str, Any]]:
        """Return tools whose owning plugin is CONNECTED or DEGRADED.

        Plugins with ``ConnectionStatus.DISCONNECTED`` or ``ERROR``
        are filtered out so the LLM is not offered tools that would
        certainly fail at execution time.

        Returns:
            Filtered list of OpenAI-format tool dicts.
        """
        async with self._lock:
            cache_snapshot = list(self._openai_cache)
            plugin_map_snapshot = dict(self._tool_to_plugin)

        available: list[dict[str, Any]] = []
        for entry in cache_snapshot:
            ns_name: str = entry["function"]["name"]
            plugin_name = plugin_map_snapshot.get(ns_name)
            if plugin_name is None:
                continue
            plugin = self._plugin_manager.get_plugin(plugin_name)
            if plugin is None:
                continue
            try:
                status = await plugin.get_connection_status()
            except Exception:
                continue
            if status in (ConnectionStatus.CONNECTED, ConnectionStatus.DEGRADED, ConnectionStatus.UNKNOWN):
                available.append(entry)
        return available

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
                self._logger.warning(
                    "Tool '{}' args validation failed: {}",
                    tool_name, ve.message,
                )
                await self._event_bus.emit(
                    AliceEvent.TOOL_EXECUTION_FAILED,
                    tool_name=tool_name,
                    execution_id=execution_id,
                    error=f"Invalid arguments: {ve.message}",
                )
                return ToolResult.error(
                    f"Tool '{tool_name}' argument validation failed: {ve.message}"
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

        # --- sanitise (conditional) ---
        if tool_def.sanitise_output:
            if isinstance(result.content, str):
                result.content = _sanitise_content(result.content)
            elif isinstance(result.content, dict):
                result.content = _sanitise_dict(result.content)

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
