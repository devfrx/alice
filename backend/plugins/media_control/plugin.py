"""O.M.N.I.A. — Media Control plugin.

Exposes tools for system volume, media playback keys, and display
brightness on Windows.  Volume control uses pycaw (COM), media keys
use pywin32 virtual key events, and brightness uses WMI via PowerShell.
"""

from __future__ import annotations

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
from backend.plugins.media_control.executor import (
    _IS_WINDOWS,
    _PYCAW_AVAILABLE,
    _WIN32_AVAILABLE,
    check_dependencies as check_executor_deps,
    exec_get_volume,
    exec_media_next,
    exec_media_play_pause,
    exec_media_prev,
    exec_mute,
    exec_set_brightness,
    exec_set_volume,
    exec_unmute,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext


class MediaControlPlugin(BasePlugin):
    """System volume, media playback and display brightness control (Windows)."""

    plugin_name: str = "media_control"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "System volume, media playback and display brightness control (Windows)."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 30

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Initialize the plugin and warn about missing dependencies.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)
        missing = check_executor_deps()
        if not _IS_WINDOWS:
            logger.warning(
                "media_control plugin: not running on Windows "
                "— all tools will be unavailable"
            )
        elif missing:
            logger.warning(
                "media_control plugin: missing dependencies — {}", missing
            )

    # -- Tools -------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return all media-control tool definitions.

        Returns:
            A list of ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="get_volume",
                description="Get the current system master volume level (0–100).",
                parameters={"type": "object", "properties": {}},
                result_type="string",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="set_volume",
                description=(
                    "Set the system master volume to a specific level (0–100). "
                    "This is easily reversible."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "integer",
                            "description": "Volume level (0–100).",
                            "minimum": 0,
                            "maximum": 100,
                        },
                    },
                    "required": ["level"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=False,
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="volume_up",
                description=(
                    "Increase the system volume by the configured step "
                    "(default 10%)."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="string",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="volume_down",
                description=(
                    "Decrease the system volume by the configured step "
                    "(default 10%)."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="string",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="mute",
                description="Mute the system audio output.",
                parameters={"type": "object", "properties": {}},
                result_type="string",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="unmute",
                description="Unmute the system audio output.",
                parameters={"type": "object", "properties": {}},
                result_type="string",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="media_play_pause",
                description="Toggle play/pause on the active media player.",
                parameters={"type": "object", "properties": {}},
                result_type="string",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="media_next",
                description="Skip to the next track in the active media player.",
                parameters={"type": "object", "properties": {}},
                result_type="string",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="media_previous",
                description=(
                    "Go to the previous track in the active media player."
                ),
                parameters={"type": "object", "properties": {}},
                result_type="string",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="set_brightness",
                description=(
                    "Set the display brightness (0–100). "
                    "Works on laptop displays via WMI."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "integer",
                            "description": "Brightness level (0–100).",
                            "minimum": 0,
                            "maximum": 100,
                        },
                    },
                    "required": ["level"],
                },
                result_type="string",
                risk_level="medium",
                requires_confirmation=False,
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
            tool_name: One of the registered tool names.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the output or an error message.
        """
        start = time.perf_counter()

        try:
            if tool_name == "get_volume":
                level = await exec_get_volume()
                result = f"Current volume: {level}%"

            elif tool_name == "set_volume":
                level = args.get("level")
                if level is None:
                    return ToolResult.error("Missing required parameter: level")
                result = await exec_set_volume(int(level))

            elif tool_name == "volume_up":
                step = self._volume_step()
                current = await exec_get_volume()
                new_level = min(current + step, 100)
                result = await exec_set_volume(new_level)

            elif tool_name == "volume_down":
                step = self._volume_step()
                current = await exec_get_volume()
                new_level = max(current - step, 0)
                result = await exec_set_volume(new_level)

            elif tool_name == "mute":
                result = await exec_mute()

            elif tool_name == "unmute":
                result = await exec_unmute()

            elif tool_name == "media_play_pause":
                result = await exec_media_play_pause()

            elif tool_name == "media_next":
                result = await exec_media_next()

            elif tool_name == "media_previous":
                result = await exec_media_prev()

            elif tool_name == "set_brightness":
                level = args.get("level")
                if level is None:
                    return ToolResult.error("Missing required parameter: level")
                result = await exec_set_brightness(int(level))

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
        """Return connection status based on platform and dependencies.

        Returns:
            ``CONNECTED`` if all deps present, ``ERROR`` if not Windows,
            ``DEGRADED`` if some deps are missing.
        """
        if not _IS_WINDOWS:
            return ConnectionStatus.ERROR
        missing = check_executor_deps()
        if missing:
            return ConnectionStatus.DEGRADED
        return ConnectionStatus.CONNECTED

    # -- Private helpers ----------------------------------------------------

    def _volume_step(self) -> int:
        """Read volume_step from plugin config (default 10).

        Returns:
            The configured volume step percentage.
        """
        try:
            return self.ctx.config.media_control.volume_step
        except AttributeError:
            logger.debug("media_control.volume_step not configured, using default 10")
            return 10
