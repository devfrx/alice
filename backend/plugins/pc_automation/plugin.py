"""O.M.N.I.A. — PC Automation plugin.

Exposes ten tools for controlling the local PC: opening/closing apps,
keyboard input, screenshots, mouse control, and shell commands.
All actions go through a hardened executor layer with whitelists,
confirmation requirements, and security lockouts.
"""

from __future__ import annotations

import base64
import time
from typing import Any, TYPE_CHECKING

from loguru import logger

from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.pc_automation.executor import (
    check_dependencies as check_executor_deps,
    exec_click,
    exec_close_app,
    exec_command,
    exec_get_active_window,
    exec_get_running_apps,
    exec_move_mouse,
    exec_open_app,
    exec_press_keys,
    exec_take_screenshot,
    exec_type_text,
    get_lockout,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext


class PcAutomationPlugin(BasePlugin):
    """Controls the local PC through safe, sandboxed executor functions."""

    plugin_name: str = "pc_automation"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Open/close apps, type text, press keys, take screenshots, "
        "move mouse, click, list windows, and execute whitelisted commands."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 50

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Initialize the plugin.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)
        missing = check_executor_deps()
        if missing:
            logger.warning(
                "pc_automation plugin: missing dependencies — {}", missing
            )

    # -- Tools -------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return the ten PC-automation tool definitions.

        Returns:
            A list of ``ToolDefinition`` objects for each tool.
        """
        return [
            ToolDefinition(
                name="open_application",
                description=(
                    "Open a whitelisted application by name. Allowed: "
                    "notepad, calculator, explorer, paint, chrome, firefox, "
                    "edge, vscode, vivaldi, discord, lmstudio, notion, "
                    "hwinfo, steam, impostazioni, terminal, etc."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": (
                                "Application name (e.g. 'notepad', "
                                "'chrome', 'vscode')"
                            ),
                        },
                    },
                    "required": ["app_name"],
                },
                result_type="string",
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=15000,
            ),
            ToolDefinition(
                name="close_application",
                description=(
                    "Close a running application by name. "
                    "Only whitelisted application names are accepted."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "app_name": {
                            "type": "string",
                            "description": "Application name to close.",
                        },
                    },
                    "required": ["app_name"],
                },
                result_type="string",
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=15000,
            ),
            ToolDefinition(
                name="type_text",
                description=(
                    "Type text into the currently focused window "
                    "using clipboard paste. Max 1000 characters per call; "
                    "split longer text into multiple calls."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": (
                                "The text to type (max 1000 chars). "
                                "Unicode / accented characters are supported."
                            ),
                            "maxLength": 1000,
                        },
                    },
                    "required": ["text"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
                timeout_ms=5000,
            ),
            ToolDefinition(
                name="press_keys",
                description=(
                    "Press a key combination (e.g. ['ctrl', 'c']). "
                    "Accepts a list of key names."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of key names to press together "
                                "(e.g. ['ctrl', 's'])."
                            ),
                        },
                    },
                    "required": ["keys"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
                timeout_ms=5000,
            ),
            ToolDefinition(
                name="take_screenshot",
                description=(
                    "Capture a screenshot of the current screen "
                    "and return it as a base64-encoded PNG."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="binary_base64",
                risk_level="medium",
                requires_confirmation=True,
                timeout_ms=10000,
            ),
            ToolDefinition(
                name="get_active_window",
                description=(
                    "Return the title and process name of the currently "
                    "focused window."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="string",
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=5000,
            ),
            ToolDefinition(
                name="get_running_apps",
                description=(
                    "List all visible running applications with their "
                    "window titles and process names."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="json",
                risk_level="safe",
                requires_confirmation=False,
                timeout_ms=15000,
            ),
            ToolDefinition(
                name="execute_command",
                description=(
                    "Execute a whitelisted shell command. "
                    "Informational: dir, echo, type, ipconfig, "
                    "systeminfo, tasklist, hostname, whoami, ping, "
                    "nslookup, netstat, ver, vol, where, tree, findstr. "
                    "File management: mkdir, copy, move, rename, ren, "
                    "rmdir, robocopy. "
                    "System directories (C:\\Windows, C:\\Program Files, "
                    "etc.) are protected. Destructive flags like "
                    "rmdir /s /q are blocked."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The command string to execute.",
                        },
                    },
                    "required": ["command"],
                },
                result_type="string",
                risk_level="dangerous",
                requires_confirmation=True,
                timeout_ms=30000,
            ),
            ToolDefinition(
                name="move_mouse",
                description="Move the mouse cursor to absolute screen coordinates.",
                parameters={
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "integer",
                            "description": "X coordinate (pixels from left).",
                        },
                        "y": {
                            "type": "integer",
                            "description": "Y coordinate (pixels from top).",
                        },
                    },
                    "required": ["x", "y"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
                timeout_ms=5000,
            ),
            ToolDefinition(
                name="click",
                description=(
                    "Click at absolute screen coordinates with the "
                    "specified mouse button."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "integer",
                            "description": "X coordinate (pixels from left).",
                        },
                        "y": {
                            "type": "integer",
                            "description": "Y coordinate (pixels from top).",
                        },
                        "button": {
                            "type": "string",
                            "description": (
                                "Mouse button: 'left', 'right', or 'middle'."
                            ),
                            "enum": ["left", "right", "middle"],
                            "default": "left",
                        },
                    },
                    "required": ["x", "y"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=True,
                timeout_ms=5000,
            ),
        ]

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the matching executor function.

        Args:
            tool_name: One of the ten registered tool names.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the output or an error message.
        """
        start = time.perf_counter()

        try:
            if tool_name == "open_application":
                result = await exec_open_app(args["app_name"])
            elif tool_name == "close_application":
                result = await exec_close_app(args["app_name"])
            elif tool_name == "type_text":
                result = await exec_type_text(args["text"])
            elif tool_name == "press_keys":
                result = await exec_press_keys(args["keys"])
            elif tool_name == "take_screenshot":
                png_bytes = await exec_take_screenshot()
                b64 = base64.b64encode(png_bytes).decode("ascii")
                elapsed = (time.perf_counter() - start) * 1000
                return ToolResult.ok(
                    b64,
                    content_type="image/png",
                    execution_time_ms=elapsed,
                )
            elif tool_name == "get_active_window":
                result = await exec_get_active_window()
            elif tool_name == "get_running_apps":
                data = await exec_get_running_apps()
                elapsed = (time.perf_counter() - start) * 1000
                return ToolResult.ok(
                    data,
                    content_type="application/json",
                    execution_time_ms=elapsed,
                )
            elif tool_name == "execute_command":
                result = await exec_command(args["command"])
            elif tool_name == "move_mouse":
                result = await exec_move_mouse(args["x"], args["y"])
            elif tool_name == "click":
                button = args.get("button", "left")
                result = await exec_click(args["x"], args["y"], button)
            else:
                return ToolResult.error(f"Unknown tool: {tool_name}")

            elapsed = (time.perf_counter() - start) * 1000
            return ToolResult.ok(result, execution_time_ms=elapsed)

        except ValueError as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("Tool '{}' validation error: {}", tool_name, e)
            return ToolResult.error(str(e), execution_time_ms=elapsed)
        except RuntimeError as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("Tool '{}' runtime error: {}", tool_name, e)
            return ToolResult.error(str(e), execution_time_ms=elapsed)
        except (OSError, TimeoutError) as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error("Tool '{}' OS/timeout error: {}", tool_name, e)
            return ToolResult.error(
                f"System error executing '{tool_name}': {type(e).__name__}",
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error("Tool '{}' unexpected failure: {}", tool_name, e)
            return ToolResult.error(
                f"Unexpected error executing '{tool_name}'",
                execution_time_ms=elapsed,
            )

    # -- Dependency / health -----------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Report missing optional dependencies.

        Returns:
            A list of missing package names, or an empty list.
        """
        return check_executor_deps()

    async def get_connection_status(self) -> ConnectionStatus:
        """Return CONNECTED if all deps are available, DEGRADED on lockout.

        Returns:
            ``ConnectionStatus.CONNECTED``, ``DEGRADED``, or ``DISCONNECTED``.
        """
        missing = check_executor_deps()
        if missing:
            return ConnectionStatus.DISCONNECTED
        if get_lockout().is_locked("execute_command"):
            return ConnectionStatus.DEGRADED
        return ConnectionStatus.CONNECTED
