"""AL\\CE — Tool execution: dispatch, validation, sanitisation.

Executes a namespaced tool call against its owning plugin with
timeout enforcement, best-effort argument coercion, JSON-Schema
validation, result truncation, output sanitisation and event-bus
notifications.
"""

from __future__ import annotations

import asyncio
import copy
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

from backend.core.event_bus import AliceEvent, EventBus
from backend.core.plugin_manager import PluginManager
from backend.core.plugin_models import ExecutionContext, ToolResult
from backend.core.tools.catalog import ToolCatalog

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


class ToolExecutor:
    """Dispatches namespaced tool calls to their owning plugin.

    Args:
        catalog: The tool catalog (definitions + owning-plugin lookup).
        plugin_manager: The plugin manager supplying loaded plugins.
        event_bus: The event bus for emitting execution events.
    """

    def __init__(
        self,
        catalog: ToolCatalog,
        plugin_manager: PluginManager,
        event_bus: EventBus,
    ) -> None:
        self._catalog = catalog
        self._plugin_manager = plugin_manager
        self._event_bus = event_bus
        self._logger = logger.bind(component="ToolExecutor")

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
        async with self._catalog.lock:
            tool_def = self._catalog.tools.get(tool_name)
            plugin_name = self._catalog.tool_to_plugin.get(tool_name)
            kernel_handler = self._catalog.kernel_handler_of(tool_name)

            # Fallback: LLMs sometimes drop the "<plugin>_" prefix and
            # emit the bare tool name (e.g. "remember" instead of
            # "memory_remember").  Resolve by unique suffix match.
            if tool_def is None:
                suffix = f"_{tool_name}"
                candidates = [
                    ns for ns in self._catalog.tools
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
                    tool_def = self._catalog.tools.get(resolved)
                    plugin_name = self._catalog.tool_to_plugin.get(resolved)
                    kernel_handler = self._catalog.kernel_handler_of(resolved)
                elif len(candidates) > 1:
                    return ToolResult.error(
                        f"Tool '{tool_name}' is ambiguous: matches "
                        f"{candidates!r} — use the full namespaced name"
                    )

        if tool_def is None:
            return ToolResult.error(
                f"Tool '{tool_name}' not available: "
                "not found in registry"
            )

        plugin: Any = None
        if kernel_handler is None:
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
            if kernel_handler is not None:
                invocation = kernel_handler(args, context)
            else:
                invocation = plugin.execute_tool(tool_def.name, args, context)
            result: ToolResult = await asyncio.wait_for(
                invocation,
                timeout=timeout_s,
            )
        except TimeoutError:
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
