"""AL\\CE — Notifications plugin.

Windows toast notifications and timer management.  Uses *winotify* for
native Windows notifications and :class:`TimerManager` for persistent
async timers backed by SQLite.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any

from backend.core.event_bus import AliceEvent
from backend.core.plugin_base import BasePlugin
from backend.core.plugin_models import (
    ConnectionStatus,
    ExecutionContext,
    ToolDefinition,
    ToolResult,
)
from backend.plugins.notifications.timer_manager import (
    ActiveTimer,
    TimerManager,
)

if TYPE_CHECKING:
    from backend.core.context import AppContext

# -- Lazy import of winotify ------------------------------------------------

try:
    from winotify import Notification as WinNotification

    _WINOTIFY_AVAILABLE = True
except ImportError:
    WinNotification = None  # type: ignore[assignment,misc]
    _WINOTIFY_AVAILABLE = False


class NotificationsPlugin(BasePlugin):
    """Windows toast notifications and timer management."""

    plugin_name: str = "notifications"
    plugin_version: str = "1.0.0"
    plugin_description: str = (
        "Windows toast notifications and timer management."
    )
    plugin_dependencies: list[str] = []
    plugin_priority: int = 25

    def __init__(self) -> None:
        super().__init__()
        self._timer_manager: TimerManager | None = None

    # -- Lifecycle ---------------------------------------------------------

    async def initialize(self, ctx: AppContext) -> None:
        """Create the :class:`TimerManager` instance.

        Args:
            ctx: The shared application context.
        """
        await super().initialize(ctx)

        if ctx.db is None:
            self.logger.error("Database session factory not available")
            return

        self._timer_manager = TimerManager(ctx.db, ctx.event_bus)

        if not _WINOTIFY_AVAILABLE:
            self.logger.warning(
                "winotify not installed — toast notifications "
                "will be logged only"
            )

    async def cleanup(self) -> None:
        """Shut down the timer manager and release resources."""
        # Unsubscribe the calendar-reminder handler registered in
        # on_app_startup so the event_bus does not retain a reference
        # to this (now-defunct) plugin instance.  Without this the
        # plugin would leak across hot-reloads in development.
        try:
            self.ctx.event_bus.unsubscribe(
                AliceEvent.CALENDAR_REMINDER,
                self._on_calendar_reminder,
            )
        except Exception as exc:
            self.logger.debug(
                "Calendar-reminder unsubscribe skipped: {}", exc,
            )

        if self._timer_manager is not None:
            await self._timer_manager.shutdown()
            self._timer_manager = None
        await super().cleanup()

    async def on_app_startup(self) -> None:
        """Restore pending timers and subscribe to calendar reminders."""
        if self._timer_manager is not None:
            restored = await self._timer_manager.restore_timers(
                self._on_timer_fired,
            )
            if restored:
                self.logger.info(
                    "Restored {} pending timer(s)", restored,
                )

        # Subscribe to calendar reminders for toast integration
        self.ctx.event_bus.subscribe(
            AliceEvent.CALENDAR_REMINDER,
            self._on_calendar_reminder,
        )

    async def on_app_shutdown(self) -> None:
        """Signal shutdown — actual cleanup happens in cleanup()."""

    # -- Tool definitions --------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        """Return the four notification/timer tools.

        Returns:
            A list of ``ToolDefinition`` objects.
        """
        return [
            ToolDefinition(
                name="send_notification",
                description=(
                    "Send a Windows toast notification with a title "
                    "and message."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Notification title.",
                        },
                        "message": {
                            "type": "string",
                            "description": "Notification body text.",
                        },
                        "timeout_s": {
                            "type": "integer",
                            "description": (
                                "Seconds the notification stays visible. "
                                "Defaults to config value."
                            ),
                        },
                    },
                    "required": ["title", "message"],
                },
                result_type="string",
                risk_level="safe",
                timeout_ms=5000,
            ),
            ToolDefinition(
                name="set_timer",
                description=(
                    "Set a named timer that fires a notification after "
                    "the given number of seconds."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": (
                                "Human-readable timer description."
                            ),
                        },
                        "duration_seconds": {
                            "type": "integer",
                            "description": (
                                "Seconds until the timer fires "
                                "(1–86400)."
                            ),
                            "minimum": 1,
                            "maximum": 86400,
                        },
                    },
                    "required": ["label", "duration_seconds"],
                },
                result_type="json",
                risk_level="safe",
                timeout_ms=10_000,
            ),
            ToolDefinition(
                name="cancel_timer",
                description="Cancel an active timer by its ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "timer_id": {
                            "type": "string",
                            "description": "The UUID of the timer to cancel.",
                        },
                    },
                    "required": ["timer_id"],
                },
                result_type="string",
                risk_level="safe",
                timeout_ms=3000,
            ),
            ToolDefinition(
                name="list_active_timers",
                description="List all currently pending timers.",
                parameters={"type": "object", "properties": {}},
                result_type="json",
                risk_level="safe",
                timeout_ms=3000,
            ),
        ]

    # -- Tool execution ----------------------------------------------------

    async def execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Dispatch to the requested tool.

        Args:
            tool_name: One of the four tool names.
            args: Caller-supplied keyword arguments.
            context: Execution metadata.

        Returns:
            A ``ToolResult`` with the outcome.
        """
        start = time.perf_counter()

        try:
            if tool_name == "send_notification":
                result = await self._tool_send_notification(args)
            elif tool_name == "set_timer":
                result = await self._tool_set_timer(args)
            elif tool_name == "cancel_timer":
                result = await self._tool_cancel_timer(args)
            elif tool_name == "list_active_timers":
                result = await self._tool_list_active_timers()
            else:
                return ToolResult.error(f"Unknown tool: {tool_name}")
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            self.logger.error("Tool '{}' failed: {}", tool_name, exc)
            return ToolResult.error(str(exc), execution_time_ms=elapsed)

        result.execution_time_ms = (time.perf_counter() - start) * 1000
        return result

    # -- Individual tool implementations -----------------------------------

    async def _tool_send_notification(
        self, args: dict[str, Any],
    ) -> ToolResult:
        """Send a Windows toast notification."""
        title: str = args.get("title", "")
        message: str = args.get("message", "")
        if not title or not message:
            return ToolResult.error("Both 'title' and 'message' are required")
        timeout_s: int = args.get(
            "timeout_s",
            self.ctx.config.notifications.default_timeout_s,
        )

        if not _WINOTIFY_AVAILABLE:
            self.logger.warning(
                "Notification (no display): {} — {}", title, message,
            )
            return ToolResult.ok(
                "Notification logged (no display available)",
            )

        try:
            await asyncio.to_thread(
                _send_win_notification,
                title,
                message,
                self.ctx.config.notifications.app_id,
                timeout_s,
            )
        except Exception as exc:
            self.logger.error("Failed to send notification: {}", exc)
            return ToolResult.error(f"Notification failed: {exc}")

        return ToolResult.ok(f"Notification sent: {title}")

    async def _tool_set_timer(self, args: dict[str, Any]) -> ToolResult:
        """Set a new timer."""
        if self._timer_manager is None:
            return ToolResult.error("Timer manager not initialised")

        label = args.get("label", "")
        if not label:
            return ToolResult.error("'label' is required")
        try:
            duration_seconds = int(args.get("duration_seconds", 0))
        except (TypeError, ValueError):
            return ToolResult.error("'duration_seconds' must be an integer")

        # Validate duration
        if not 1 <= duration_seconds <= 86400:
            return ToolResult.error(
                "duration_seconds must be between 1 and 86400"
            )

        # Lock protects the check-and-create sequence against races
        async with self._timer_manager.lock:
            active = await self._timer_manager.list_active()
            max_timers = self.ctx.config.notifications.max_active_timers
            if len(active) >= max_timers:
                return ToolResult.error(
                    f"Maximum active timers reached ({max_timers})"
                )

            timer_id = str(uuid.uuid4())
            fires_at = await self._timer_manager.create_timer(
                timer_id=timer_id,
                label=label,
                duration_s=duration_seconds,
                callback=self._on_timer_fired,
            )

        return ToolResult.ok(
            content={
                "timer_id": timer_id,
                "label": label,
                "fires_at": fires_at.isoformat(),
            },
            content_type="application/json",
        )

    async def _tool_cancel_timer(self, args: dict[str, Any]) -> ToolResult:
        """Cancel an active timer."""
        if self._timer_manager is None:
            return ToolResult.error("Timer manager not initialised")

        timer_id: str = args.get("timer_id", "")
        if not timer_id:
            return ToolResult.error("Missing required parameter: timer_id")
        cancelled = await self._timer_manager.cancel_timer(timer_id)
        if cancelled:
            return ToolResult.ok(f"Timer '{timer_id}' cancelled")
        return ToolResult.error(f"Timer '{timer_id}' not found or not active")

    async def _tool_list_active_timers(self) -> ToolResult:
        """List all pending timers."""
        if self._timer_manager is None:
            return ToolResult.error("Timer manager not initialised")

        timers = await self._timer_manager.list_active()
        return ToolResult.ok(
            content={"timers": timers, "count": len(timers)},
            content_type="application/json",
        )

    # -- Callbacks ---------------------------------------------------------

    async def _on_timer_fired(
        self, timer_id: str, label: str,
    ) -> None:
        """Called when a timer fires — sends a toast notification."""
        self.logger.info("Timer fired: {} ({})", label, timer_id)
        await self._tool_send_notification({
            "title": "Timer",
            "message": label,
        })

    async def _on_calendar_reminder(self, **kwargs: Any) -> None:
        """Handle calendar reminder events with a toast notification."""
        title = kwargs.get("title", "Promemoria")
        start_time = kwargs.get("start_time", "")
        reminder_minutes = kwargs.get("reminder_minutes", 0)
        if start_time:
            message = (
                f"Tra {reminder_minutes} minuti — alle {start_time}"
                if reminder_minutes
                else f"Inizia alle {start_time}"
            )
        else:
            message = (
                f"Tra {reminder_minutes} minuti"
                if reminder_minutes
                else "Evento imminente"
            )
        await self._tool_send_notification({
            "title": f"\U0001f4c5 {title}",
            "message": message,
        })

    # -- Dependency / health -----------------------------------------------

    def check_dependencies(self) -> list[str]:
        """Report missing optional dependencies.

        Returns:
            A list with ``"winotify"`` if the package is not installed,
            otherwise an empty list.
        """
        if not _WINOTIFY_AVAILABLE:
            return ["winotify"]
        return []

    async def get_connection_status(self) -> ConnectionStatus:
        """Notifications are always local — report CONNECTED.

        Returns:
            ``ConnectionStatus.CONNECTED``.
        """
        return ConnectionStatus.CONNECTED

    @classmethod
    def get_db_models(cls) -> list[type]:
        """Return the ``ActiveTimer`` model for table creation.

        Returns:
            A list containing the ``ActiveTimer`` SQLModel class.
        """
        return [ActiveTimer]


# ---------------------------------------------------------------------------
# Helpers (run in thread)
# ---------------------------------------------------------------------------


def _send_win_notification(
    title: str,
    message: str,
    app_id: str,
    timeout_s: int,
) -> None:
    """Send a Windows toast notification via winotify (blocking).

    Args:
        title: Notification title.
        message: Notification body text.
        app_id: Application identifier for the toast.
        timeout_s: Duration the notification stays visible.
    """
    toast = WinNotification(
        app_id=app_id,
        title=title,
        msg=message,
        duration="long" if timeout_s > 7 else "short",
    )
    toast.show()
