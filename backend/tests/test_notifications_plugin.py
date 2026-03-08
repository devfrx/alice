"""Tests for backend.plugins.notifications — NotificationsPlugin & TimerManager."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus, OmniaEvent
from backend.core.plugin_models import ConnectionStatus, ExecutionContext, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="test",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


def _make_app_context(
    *,
    db: MagicMock | None = None,
    event_bus: EventBus | None = None,
) -> AppContext:
    """Build a minimal AppContext with default config."""
    return AppContext(
        config=load_config(),
        event_bus=event_bus or EventBus(),
        db=db,
    )


def _make_db_factory() -> MagicMock:
    """Return an async_sessionmaker mock that supports ``async with``."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.exec = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


def _make_db_factory_with_timers(timer_rows: list) -> MagicMock:
    """Return a db factory mock whose session.exec returns *timer_rows*."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()

    result_mock = MagicMock()
    result_mock.all = MagicMock(return_value=timer_rows)
    result_mock.one_or_none = MagicMock(
        return_value=timer_rows[0] if timer_rows else None,
    )
    session.exec = AsyncMock(return_value=result_mock)

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


# ===========================================================================
# 1. Plugin lifecycle
# ===========================================================================


class TestNotificationsPluginLifecycle:
    """Verify plugin attributes and lifecycle behaviour."""

    def test_plugin_attributes(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        assert plugin.plugin_name == "notifications"
        assert plugin.plugin_priority == 25
        assert plugin.plugin_version == "1.0.0"
        assert plugin.plugin_dependencies == []

    @pytest.mark.asyncio
    async def test_initialize_sets_timer_manager(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)

        await plugin.initialize(ctx)

        assert plugin.is_initialized
        assert plugin._timer_manager is not None

    @pytest.mark.asyncio
    async def test_initialize_without_db_logs_error(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        ctx = _make_app_context(db=None)

        await plugin.initialize(ctx)

        assert plugin._timer_manager is None

    def test_tool_count_and_names(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        tools = plugin.get_tools()
        assert len(tools) == 4

        names = {t.name for t in tools}
        assert names == {
            "send_notification",
            "set_timer",
            "cancel_timer",
            "list_active_timers",
        }

    def test_all_tools_are_safe(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        for tool in plugin.get_tools():
            assert tool.risk_level == "safe"

    @pytest.mark.asyncio
    async def test_check_dependencies_winotify_available(self):
        from backend.plugins.notifications import plugin as plugin_mod
        from backend.plugins.notifications.plugin import NotificationsPlugin

        original = plugin_mod._WINOTIFY_AVAILABLE
        try:
            plugin_mod._WINOTIFY_AVAILABLE = True
            p = NotificationsPlugin()
            assert p.check_dependencies() == []
        finally:
            plugin_mod._WINOTIFY_AVAILABLE = original

    @pytest.mark.asyncio
    async def test_check_dependencies_winotify_missing(self):
        from backend.plugins.notifications import plugin as plugin_mod
        from backend.plugins.notifications.plugin import NotificationsPlugin

        original = plugin_mod._WINOTIFY_AVAILABLE
        try:
            plugin_mod._WINOTIFY_AVAILABLE = False
            p = NotificationsPlugin()
            assert p.check_dependencies() == ["winotify"]
        finally:
            plugin_mod._WINOTIFY_AVAILABLE = original

    @pytest.mark.asyncio
    async def test_connection_status_always_connected(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        status = await plugin.get_connection_status()
        assert status == ConnectionStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_get_db_models_includes_active_timer(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin
        from backend.plugins.notifications.timer_manager import ActiveTimer

        models = NotificationsPlugin.get_db_models()
        assert ActiveTimer in models

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        result = await plugin.execute_tool("nonexistent", {}, _make_exec_ctx())
        assert not result.success
        assert "Unknown tool" in result.error_message


# ===========================================================================
# 2. send_notification tool
# ===========================================================================


class TestSendNotificationTool:
    """Test the send_notification tool."""

    @pytest.mark.asyncio
    async def test_send_notification_winotify_available(self):
        from backend.plugins.notifications import plugin as plugin_mod
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        original = plugin_mod._WINOTIFY_AVAILABLE
        try:
            plugin_mod._WINOTIFY_AVAILABLE = True

            with patch(
                "backend.plugins.notifications.plugin._send_win_notification",
            ) as mock_send:
                result = await plugin.execute_tool(
                    "send_notification",
                    {"title": "Hello", "message": "World"},
                    _make_exec_ctx(),
                )

            assert result.success
            assert "Notification sent" in result.content
            mock_send.assert_called_once_with(
                "Hello",
                "World",
                ctx.config.notifications.app_id,
                ctx.config.notifications.default_timeout_s,
            )
        finally:
            plugin_mod._WINOTIFY_AVAILABLE = original

    @pytest.mark.asyncio
    async def test_send_notification_custom_timeout(self):
        from backend.plugins.notifications import plugin as plugin_mod
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        original = plugin_mod._WINOTIFY_AVAILABLE
        try:
            plugin_mod._WINOTIFY_AVAILABLE = True

            with patch(
                "backend.plugins.notifications.plugin._send_win_notification",
            ) as mock_send:
                result = await plugin.execute_tool(
                    "send_notification",
                    {"title": "Test", "message": "Body", "timeout_s": 10},
                    _make_exec_ctx(),
                )

            assert result.success
            # Custom timeout passed through
            mock_send.assert_called_once_with(
                "Test", "Body", ctx.config.notifications.app_id, 10,
            )
        finally:
            plugin_mod._WINOTIFY_AVAILABLE = original

    @pytest.mark.asyncio
    async def test_send_notification_winotify_not_available_fallback(self):
        from backend.plugins.notifications import plugin as plugin_mod
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        original = plugin_mod._WINOTIFY_AVAILABLE
        try:
            plugin_mod._WINOTIFY_AVAILABLE = False

            result = await plugin.execute_tool(
                "send_notification",
                {"title": "Hello", "message": "World"},
                _make_exec_ctx(),
            )

            assert result.success
            assert "logged" in result.content.lower()
        finally:
            plugin_mod._WINOTIFY_AVAILABLE = original

    @pytest.mark.asyncio
    async def test_send_notification_exception_returns_error(self):
        from backend.plugins.notifications import plugin as plugin_mod
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        original = plugin_mod._WINOTIFY_AVAILABLE
        try:
            plugin_mod._WINOTIFY_AVAILABLE = True

            with patch(
                "backend.plugins.notifications.plugin._send_win_notification",
                side_effect=RuntimeError("toast failed"),
            ):
                result = await plugin.execute_tool(
                    "send_notification",
                    {"title": "Bad", "message": "Fail"},
                    _make_exec_ctx(),
                )

            assert not result.success
            assert "Notification failed" in result.error_message
        finally:
            plugin_mod._WINOTIFY_AVAILABLE = original


# ===========================================================================
# 3. set_timer tool
# ===========================================================================


class TestSetTimerTool:
    """Test the set_timer tool."""

    @pytest.mark.asyncio
    async def test_set_timer_creates_timer(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        # Mock timer manager to avoid real DB usage
        plugin._timer_manager.list_active = AsyncMock(return_value=[])
        fires_at = datetime.now(timezone.utc) + timedelta(seconds=60)
        plugin._timer_manager.create_timer = AsyncMock(return_value=fires_at)

        result = await plugin.execute_tool(
            "set_timer",
            {"label": "Tea timer", "duration_seconds": 60},
            _make_exec_ctx(),
        )

        assert result.success
        assert "timer_id" in result.content
        assert result.content["label"] == "Tea timer"
        plugin._timer_manager.create_timer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_timer_duration_too_low(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "set_timer",
            {"label": "Bad", "duration_seconds": 0},
            _make_exec_ctx(),
        )

        assert not result.success
        assert "must be between 1 and 86400" in result.error_message

    @pytest.mark.asyncio
    async def test_set_timer_duration_too_high(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "set_timer",
            {"label": "Bad", "duration_seconds": 86401},
            _make_exec_ctx(),
        )

        assert not result.success
        assert "must be between 1 and 86400" in result.error_message

    @pytest.mark.asyncio
    async def test_set_timer_max_active_timers_exceeded(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        max_t = ctx.config.notifications.max_active_timers
        # Return exactly max timers already active
        plugin._timer_manager.list_active = AsyncMock(
            return_value=[{"id": f"t{i}"} for i in range(max_t)],
        )

        result = await plugin.execute_tool(
            "set_timer",
            {"label": "Overflow", "duration_seconds": 30},
            _make_exec_ctx(),
        )

        assert not result.success
        assert "Maximum active timers reached" in result.error_message

    @pytest.mark.asyncio
    async def test_set_timer_returns_timer_id_and_fires_at(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        plugin._timer_manager.list_active = AsyncMock(return_value=[])
        fires_at = datetime.now(timezone.utc) + timedelta(seconds=120)
        plugin._timer_manager.create_timer = AsyncMock(return_value=fires_at)

        result = await plugin.execute_tool(
            "set_timer",
            {"label": "Eggs", "duration_seconds": 120},
            _make_exec_ctx(),
        )

        assert result.success
        content = result.content
        assert "timer_id" in content
        assert content["fires_at"] == fires_at.isoformat()

    @pytest.mark.asyncio
    async def test_set_timer_without_timer_manager(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        # Initialize without DB so timer_manager stays None
        ctx = _make_app_context(db=None)
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "set_timer",
            {"label": "No manager", "duration_seconds": 10},
            _make_exec_ctx(),
        )

        assert not result.success
        assert "not initialised" in result.error_message


# ===========================================================================
# 4. cancel_timer tool
# ===========================================================================


class TestCancelTimerTool:
    """Test the cancel_timer tool."""

    @pytest.mark.asyncio
    async def test_cancel_existing_timer(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        plugin._timer_manager.cancel_timer = AsyncMock(return_value=True)

        result = await plugin.execute_tool(
            "cancel_timer",
            {"timer_id": "abc-123"},
            _make_exec_ctx(),
        )

        assert result.success
        assert "cancelled" in result.content
        plugin._timer_manager.cancel_timer.assert_awaited_once_with("abc-123")

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_timer(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        plugin._timer_manager.cancel_timer = AsyncMock(return_value=False)

        result = await plugin.execute_tool(
            "cancel_timer",
            {"timer_id": "doesnt-exist"},
            _make_exec_ctx(),
        )

        assert not result.success
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_cancel_timer_without_timer_manager(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        ctx = _make_app_context(db=None)
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "cancel_timer",
            {"timer_id": "any"},
            _make_exec_ctx(),
        )

        assert not result.success
        assert "not initialised" in result.error_message


# ===========================================================================
# 5. list_active_timers tool
# ===========================================================================


class TestListActiveTimers:
    """Test the list_active_timers tool."""

    @pytest.mark.asyncio
    async def test_list_timers_from_db(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        sample_timers = [
            {"id": "t1", "label": "Pasta", "fires_at": "2026-01-01T00:05:00+00:00"},
            {"id": "t2", "label": "Tea", "fires_at": "2026-01-01T00:10:00+00:00"},
        ]
        plugin._timer_manager.list_active = AsyncMock(return_value=sample_timers)

        result = await plugin.execute_tool(
            "list_active_timers",
            {},
            _make_exec_ctx(),
        )

        assert result.success
        assert result.content["count"] == 2
        assert len(result.content["timers"]) == 2

    @pytest.mark.asyncio
    async def test_list_timers_empty(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        ctx = _make_app_context(db=db)
        await plugin.initialize(ctx)

        plugin._timer_manager.list_active = AsyncMock(return_value=[])

        result = await plugin.execute_tool(
            "list_active_timers",
            {},
            _make_exec_ctx(),
        )

        assert result.success
        assert result.content["count"] == 0
        assert result.content["timers"] == []

    @pytest.mark.asyncio
    async def test_list_timers_without_timer_manager(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        ctx = _make_app_context(db=None)
        await plugin.initialize(ctx)

        result = await plugin.execute_tool(
            "list_active_timers",
            {},
            _make_exec_ctx(),
        )

        assert not result.success
        assert "not initialised" in result.error_message


# ===========================================================================
# 6. TimerManager
# ===========================================================================


class TestTimerManager:
    """Test TimerManager independently from the plugin."""

    @pytest.mark.asyncio
    async def test_create_timer_starts_task(self):
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        fires_at = await manager.create_timer(
            timer_id="t-1",
            label="Test timer",
            duration_s=3600,
            callback=callback,
        )

        assert "t-1" in manager._timers
        task = manager._timers["t-1"]
        assert not task.done()

        # Cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_create_timer_persists_to_db(self):
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        await manager.create_timer(
            timer_id="t-2",
            label="Persist test",
            duration_s=60,
            callback=callback,
        )

        # session.add was called with an ActiveTimer
        session = db.return_value.__aenter__.return_value
        session.add.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert added_obj.id == "t-2"
        assert added_obj.label == "Persist test"
        assert added_obj.status == "pending"
        session.commit.assert_awaited_once()

        # Cleanup
        manager._timers["t-2"].cancel()
        try:
            await manager._timers["t-2"]
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_cancel_timer_cancels_task(self):
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        await manager.create_timer(
            timer_id="t-cancel",
            label="Cancel me",
            duration_s=3600,
            callback=callback,
        )

        # Need fresh db factory for cancel's _update_status call
        result = await manager.cancel_timer("t-cancel")
        assert result is True
        assert "t-cancel" not in manager._timers

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self):
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        result = await manager.cancel_timer("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_shutdown_cancels_all_tasks(self):
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        await manager.create_timer("s1", "Timer 1", 3600, callback)
        await manager.create_timer("s2", "Timer 2", 3600, callback)

        assert len(manager._timers) == 2

        await manager.shutdown()

        assert len(manager._timers) == 0

    @pytest.mark.asyncio
    async def test_list_active_returns_pending(self):
        from backend.plugins.notifications.timer_manager import (
            ActiveTimer,
            TimerManager,
        )

        now = datetime.now(timezone.utc)
        row = ActiveTimer(
            id="list-1",
            label="Pending",
            fires_at=now + timedelta(seconds=300),
            created_at=now,
            status="pending",
        )
        db = _make_db_factory_with_timers([row])
        bus = EventBus()
        manager = TimerManager(db, bus)

        result = await manager.list_active()
        assert len(result) == 1
        assert result[0]["id"] == "list-1"
        assert result[0]["label"] == "Pending"

    @pytest.mark.asyncio
    async def test_restore_timers_fires_past_immediately(self):
        from backend.plugins.notifications.timer_manager import (
            ActiveTimer,
            TimerManager,
        )

        now = datetime.now(timezone.utc)
        past_row = ActiveTimer(
            id="past-1",
            label="Already past",
            fires_at=now - timedelta(seconds=60),
            created_at=now - timedelta(seconds=120),
            status="pending",
        )
        db = _make_db_factory_with_timers([past_row])
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        restored = await manager.restore_timers(callback)

        assert restored == 1
        # Give the immediate-fire task a moment to run
        await asyncio.sleep(0.05)
        callback.assert_awaited_once_with("past-1", "Already past")

    @pytest.mark.asyncio
    async def test_restore_timers_schedules_future(self):
        from backend.plugins.notifications.timer_manager import (
            ActiveTimer,
            TimerManager,
        )

        now = datetime.now(timezone.utc)
        future_row = ActiveTimer(
            id="future-1",
            label="Future timer",
            fires_at=now + timedelta(seconds=3600),
            created_at=now,
            status="pending",
        )
        db = _make_db_factory_with_timers([future_row])
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        restored = await manager.restore_timers(callback)

        assert restored == 1
        assert "future-1" in manager._timers

        # Cleanup
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_fire_timer_invokes_callback_and_updates_status(self):
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        await manager._fire_timer("fire-1", "Fire test", callback)

        callback.assert_awaited_once_with("fire-1", "Fire test")


# ===========================================================================
# 7. EventBus integration
# ===========================================================================


class TestEventBusIntegration:
    """Verify TIMER_FIRED event is emitted when a timer fires."""

    @pytest.mark.asyncio
    async def test_timer_fired_event_emitted(self):
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        received_events: list[dict] = []

        async def handler(**kwargs):
            received_events.append(kwargs)

        bus.subscribe(OmniaEvent.TIMER_FIRED, handler)

        callback = AsyncMock()
        await manager._fire_timer("evt-1", "Event test", callback)

        assert len(received_events) == 1
        assert received_events[0]["timer_id"] == "evt-1"
        assert received_events[0]["label"] == "Event test"

    @pytest.mark.asyncio
    async def test_timer_fired_event_from_create_short_timer(self):
        """Create a very short timer and verify event emission end-to-end."""
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        received_events: list[dict] = []

        async def handler(**kwargs):
            received_events.append(kwargs)

        bus.subscribe(OmniaEvent.TIMER_FIRED, handler)

        callback = AsyncMock()
        await manager.create_timer(
            timer_id="short-1",
            label="Quick fire",
            duration_s=0,  # fires immediately (sleep(0))
            callback=callback,
        )

        # Let the event loop process the task
        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert received_events[0]["timer_id"] == "short-1"
        callback.assert_awaited_once_with("short-1", "Quick fire")

    @pytest.mark.asyncio
    async def test_on_app_startup_subscribes_calendar_reminder(self):
        from backend.plugins.notifications.plugin import NotificationsPlugin

        plugin = NotificationsPlugin()
        db = _make_db_factory()
        bus = EventBus()
        ctx = _make_app_context(db=db, event_bus=bus)
        await plugin.initialize(ctx)

        # Mock restore_timers to avoid DB overhead
        plugin._timer_manager.restore_timers = AsyncMock(return_value=0)

        await plugin.on_app_startup()

        # Verify CALENDAR_REMINDER handler was subscribed
        assert OmniaEvent.CALENDAR_REMINDER in bus._handlers
        assert len(bus._handlers[OmniaEvent.CALENDAR_REMINDER]) == 1


# ===========================================================================
# 8. Restore fire-immediately tracking & shutdown behaviour
# ===========================================================================


class TestRestoreAndShutdown:
    """Verify fire-immediately tasks are tracked and shutdown is thorough."""

    @pytest.mark.asyncio
    async def test_restore_past_timer_is_tracked(self):
        """Fire-immediately tasks from restore must be in _timers."""
        from backend.plugins.notifications.timer_manager import (
            ActiveTimer,
            TimerManager,
        )

        now = datetime.now(timezone.utc)
        past_row = ActiveTimer(
            id="past-tracked",
            label="Track me",
            fires_at=now - timedelta(seconds=30),
            created_at=now - timedelta(seconds=90),
            status="pending",
        )
        db = _make_db_factory_with_timers([past_row])
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        restored = await manager.restore_timers(callback)

        assert restored == 1
        # The fire-immediately task must be tracked
        assert "past-tracked" in manager._timers

        # Let it finish
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_cancelled_error_updates_db_status(self):
        """When a timer task is cancelled, _update_status('cancelled') is called."""
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        await manager.create_timer(
            timer_id="cancel-status",
            label="Will cancel",
            duration_s=3600,
            callback=callback,
        )

        # Patch _update_status so we can verify it's called from the
        # CancelledError handler inside _run_timer
        task = manager._timers["cancel-status"]
        with patch.object(
            manager, "_update_status", new_callable=AsyncMock,
        ) as mock_update:
            # Let the task enter asyncio.sleep() before cancelling
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            mock_update.assert_awaited_once_with(
                "cancel-status", "cancelled",
            )

    @pytest.mark.asyncio
    async def test_shutdown_awaits_task_cancellation(self):
        """shutdown() must await all tasks after cancelling."""
        from backend.plugins.notifications.timer_manager import TimerManager

        db = _make_db_factory()
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        await manager.create_timer("sw-1", "Timer 1", 3600, callback)
        await manager.create_timer("sw-2", "Timer 2", 3600, callback)

        tasks = list(manager._timers.values())
        assert len(tasks) == 2
        assert all(not t.done() for t in tasks)

        await manager.shutdown()

        # After shutdown, all tasks should be done (cancelled)
        assert all(t.done() for t in tasks)
        assert len(manager._timers) == 0

    @pytest.mark.asyncio
    async def test_shutdown_clears_fire_immediately_tasks(self):
        """shutdown() must also cancel fire-immediately tasks from restore."""
        from backend.plugins.notifications.timer_manager import (
            ActiveTimer,
            TimerManager,
        )

        now = datetime.now(timezone.utc)
        future_row = ActiveTimer(
            id="fut-shutdown",
            label="Future",
            fires_at=now + timedelta(seconds=3600),
            created_at=now,
            status="pending",
        )
        db = _make_db_factory_with_timers([future_row])
        bus = EventBus()
        manager = TimerManager(db, bus)

        callback = AsyncMock()
        await manager.restore_timers(callback)
        assert "fut-shutdown" in manager._timers

        await manager.shutdown()
        assert len(manager._timers) == 0
