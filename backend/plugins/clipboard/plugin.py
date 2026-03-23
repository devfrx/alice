"""AL\\CE — Clipboard plugin.

Exposes ``get_clipboard`` and ``set_clipboard`` tools for reading and
writing system clipboard text content via *pyperclip*.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext

# -- Lazy import of pyperclip ---------------------------------------------

try:
    import pyperclip

    _PYPERCLIP_AVAILABLE = True
except ImportError:
    pyperclip = None  # type: ignore[assignment]
    _PYPERCLIP_AVAILABLE = False

# -- Constants -------------------------------------------------------------

_MAX_SET_LENGTH = 1_000_000


# -- Plugin ----------------------------------------------------------------


class ClipboardPlugin(BasePlugin):
    """Read and write system clipboard text content."""

    plugin_name: str = "clipboard"
    plugin_version: str = "1.0.0"
    plugin_description: str = "Read and write system clipboard text content."
    plugin_dependencies: list[str] = []
    plugin_priority: int = 20

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Initialize the plugin and warn if pyperclip is missing.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)
        if not _PYPERCLIP_AVAILABLE:
            logger.warning(
                "clipboard plugin: pyperclip is not installed"
                " — tools will be unavailable"
            )

    # -- Tools -------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return tool definitions for clipboard read/write.

        Returns:
            A list of two ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="get_clipboard",
                description=(
                    "Read the current system clipboard text content. "
                    "Returns the text, its length and whether it was truncated."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="json",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="set_clipboard",
                description=(
                    "Write text to the system clipboard, replacing "
                    "its current content."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The text to copy to the clipboard.",
                        },
                    },
                    "required": ["text"],
                },
                risk_level="medium",
                requires_confirmation=True,
                timeout_ms=3000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested clipboard tool.

        Args:
            tool_name: ``"get_clipboard"`` or ``"set_clipboard"``.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the payload or an error.
        """
        if not _PYPERCLIP_AVAILABLE:
            return ToolResult.error("pyperclip not installed")

        try:
            if tool_name == "get_clipboard":
                return await self._get_clipboard()
            if tool_name == "set_clipboard":
                return await self._set_clipboard(args)
            return ToolResult.error(f"Unknown tool: {tool_name}")
        except Exception as exc:
            self.logger.error("Tool {} failed: {}", tool_name, exc)
            return ToolResult.error(str(exc))

    # -- Dependency / health -----------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Report missing optional dependencies.

        Returns:
            A list with ``"pyperclip"`` if the package is not installed,
            otherwise an empty list.
        """
        if not _PYPERCLIP_AVAILABLE:
            return ["pyperclip"]
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED if pyperclip is available, ERROR otherwise.

        Returns:
            ``ConnectionStatus.CONNECTED`` or ``ConnectionStatus.ERROR``.
        """
        if _PYPERCLIP_AVAILABLE:
            return ConnectionStatus.CONNECTED
        return ConnectionStatus.ERROR

    # -- Private helpers ---------------------------------------------------

    async def _get_clipboard(self) -> ToolResult:
        """Read clipboard text content."""
        start = time.perf_counter()
        try:
            raw: str = await asyncio.to_thread(pyperclip.paste)
        except pyperclip.PyperclipException:
            return ToolResult.error("Clipboard contains non-text content")

        max_chars: int = self.ctx.config.clipboard.max_content_chars
        truncated = len(raw) > max_chars
        content = raw[:max_chars] if truncated else raw

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content={
                "content": content,
                "truncated": truncated,
                "length": len(raw),
            },
            content_type="application/json",
            execution_time_ms=elapsed_ms,
        )

    async def _set_clipboard(self, args: dict[str, Any]) -> ToolResult:
        """Write text to the clipboard."""
        text: str | None = args.get("text")
        if text is None:
            return ToolResult.error("Missing required parameter: text")

        if len(text) > _MAX_SET_LENGTH:
            return ToolResult.error(
                f"Text exceeds maximum length ({_MAX_SET_LENGTH:,} chars)"
            )

        start = time.perf_counter()
        try:
            await asyncio.to_thread(pyperclip.copy, text)
        except pyperclip.PyperclipException as exc:
            return ToolResult.error(f"Clipboard write failed: {exc}")

        elapsed_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(
            content="Clipboard updated",
            execution_time_ms=elapsed_ms,
        )
