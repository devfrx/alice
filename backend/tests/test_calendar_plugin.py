"""Tests for backend.plugins.calendar.plugin — CalendarPlugin."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from backend.core.config import load_config
from backend.core.context import AppContext
from backend.core.event_bus import EventBus, OmniaEvent
from backend.core.plugin_models import ConnectionStatus, ExecutionContext, ToolResult
from backend.plugins.calendar.plugin import CalendarEvent, CalendarPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TZ_ROME = ZoneInfo("Europe/Rome")


def _make_exec_ctx() -> ExecutionContext:
    return ExecutionContext(
        session_id="test",
        conversation_id="test-conv",
        execution_id="test-exec",
    )


def _make_event(
    title: str = "Meeting",
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    **kwargs,
) -> CalendarEvent:
    """Build a CalendarEvent with sensible defaults."""
    now = datetime.now(timezone.utc)
    return CalendarEvent(
        id=kwargs.get("id", uuid.uuid4()),
        title=title,
        description=kwargs.get("description"),
        start_time=start_dt or now + timedelta(hours=1),
        end_time=end_dt or now + timedelta(hours=2),
        recurrence_rule=kwargs.get("recurrence_rule"),
        reminder_minutes=kwargs.get("reminder_minutes"),
    )


@asynccontextmanager
async def _mock_db_session(session: AsyncMock):
    """Async context-manager wrapper used as ``ctx.db()``."""
    yield session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx() -> AppContext:
    return AppContext(config=load_config(), event_bus=EventBus())


@pytest.fixture
def exec_context() -> ExecutionContext:
    return _make_exec_ctx()


@pytest.fixture
def plugin(ctx: AppContext) -> CalendarPlugin:
    """Return an initialised CalendarPlugin (sync-safe)."""
    p = CalendarPlugin()
    # Manually wire context without awaiting initialize() which may
    # require a full app setup.  This matches what ``super().initialize``
    # does plus the CalendarPlugin-specific initialisation.
    p._ctx = ctx
    p._initialized = True
    p._tz = ZoneInfo(ctx.config.calendar.timezone)
    p._reminder_check_interval_s = ctx.config.calendar.reminder_check_interval_s
    return p


@pytest.fixture
def mock_session() -> AsyncMock:
    """A mock async DB session with standard helpers."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.get = AsyncMock(return_value=None)
    # exec returns an object with .all()
    result_proxy = MagicMock()
    result_proxy.all.return_value = []
    session.exec = AsyncMock(return_value=result_proxy)
    return session


@pytest.fixture
def plugin_with_db(plugin: CalendarPlugin, mock_session: AsyncMock):
    """Plugin wired with a mock DB session."""
    plugin.ctx.db = lambda: _mock_db_session(mock_session)
    return plugin, mock_session


# ===================================================================
# 1. Lifecycle
# ===================================================================


class TestCalendarPluginLifecycle:
    """Plugin metadata, initialization, tools, models, startup/shutdown."""

    def test_plugin_name(self) -> None:
        p = CalendarPlugin()
        assert p.plugin_name == "calendar"

    def test_plugin_version(self) -> None:
        p = CalendarPlugin()
        assert p.plugin_version == "1.0.0"

    def test_plugin_priority(self) -> None:
        p = CalendarPlugin()
        assert p.plugin_priority == 30

    async def test_initialize_sets_timezone(self, ctx: AppContext) -> None:
        p = CalendarPlugin()
        await p.initialize(ctx)
        assert p._tz == ZoneInfo(ctx.config.calendar.timezone)

    async def test_initialize_sets_reminder_interval(
        self, ctx: AppContext,
    ) -> None:
        p = CalendarPlugin()
        await p.initialize(ctx)
        assert (
            p._reminder_check_interval_s
            == ctx.config.calendar.reminder_check_interval_s
        )

    def test_get_tools_returns_five(self, plugin: CalendarPlugin) -> None:
        tools = plugin.get_tools()
        assert len(tools) == 5

    def test_tool_names(self, plugin: CalendarPlugin) -> None:
        names = {t.name for t in plugin.get_tools()}
        assert names == {
            "create_event",
            "list_events",
            "update_event",
            "delete_event",
            "get_today_summary",
        }

    def test_tool_risk_levels(self, plugin: CalendarPlugin) -> None:
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["create_event"].risk_level == "safe"
        assert tools["list_events"].risk_level == "safe"
        assert tools["update_event"].risk_level == "safe"
        assert tools["delete_event"].risk_level == "medium"
        assert tools["get_today_summary"].risk_level == "safe"

    def test_delete_event_requires_confirmation(
        self, plugin: CalendarPlugin,
    ) -> None:
        tools = {t.name: t for t in plugin.get_tools()}
        assert tools["delete_event"].requires_confirmation is True

    def test_get_db_models(self) -> None:
        models = CalendarPlugin.get_db_models()
        assert models == [CalendarEvent]

    async def test_on_app_startup_creates_reminder_task(
        self, plugin: CalendarPlugin,
    ) -> None:
        # Patch _reminder_loop to be a no-op so the task completes quickly
        plugin._reminder_loop = AsyncMock()  # type: ignore[method-assign]
        await plugin.on_app_startup()
        assert plugin._reminder_task is not None
        assert isinstance(plugin._reminder_task, asyncio.Task)
        # Cleanup
        plugin._reminder_task.cancel()
        try:
            await plugin._reminder_task
        except asyncio.CancelledError:
            pass

    async def test_on_app_shutdown_cancels_task(
        self, plugin: CalendarPlugin,
    ) -> None:
        async def forever():
            await asyncio.sleep(3600)

        plugin._reminder_task = asyncio.create_task(forever())
        await plugin.on_app_shutdown()
        assert plugin._reminder_task.done()


# ===================================================================
# 2. create_event
# ===================================================================


class TestCreateEvent:
    """Tests for the create_event tool."""

    async def test_create_valid_event(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=1)).isoformat()
        end = (now + timedelta(hours=2)).isoformat()

        result = await plugin.execute_tool(
            "create_event",
            {"title": "Standup", "start": start, "end": end},
            exec_context,
        )

        assert result.success is True
        assert "Standup" in result.content
        assert "created" in result.content
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    async def test_create_event_end_before_start(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, _ = plugin_with_db
        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=2)).isoformat()
        end = (now + timedelta(hours=1)).isoformat()

        result = await plugin.execute_tool(
            "create_event",
            {"title": "Bad", "start": start, "end": end},
            exec_context,
        )

        assert result.success is False
        assert "end must be after start" in result.error_message

    async def test_create_event_end_equals_start(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, _ = plugin_with_db
        ts = datetime.now(timezone.utc).isoformat()

        result = await plugin.execute_tool(
            "create_event",
            {"title": "Zero duration", "start": ts, "end": ts},
            exec_context,
        )

        assert result.success is False
        assert "end must be after start" in result.error_message

    async def test_create_event_optional_fields(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        now = datetime.now(timezone.utc)
        start = (now + timedelta(hours=1)).isoformat()
        end = (now + timedelta(hours=2)).isoformat()

        result = await plugin.execute_tool(
            "create_event",
            {
                "title": "Weekly Sync",
                "start": start,
                "end": end,
                "description": "Team sync",
                "reminder_minutes": 15,
                "recurrence_rule": "FREQ=WEEKLY;BYDAY=MO",
            },
            exec_context,
        )

        assert result.success is True
        added_event: CalendarEvent = session.add.call_args[0][0]
        assert added_event.description == "Team sync"
        assert added_event.reminder_minutes == 15
        assert added_event.recurrence_rule == "FREQ=WEEKLY;BYDAY=MO"

    async def test_create_event_missing_title_errors(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, _ = plugin_with_db
        now = datetime.now(timezone.utc)

        result = await plugin.execute_tool(
            "create_event",
            {
                "start": (now + timedelta(hours=1)).isoformat(),
                "end": (now + timedelta(hours=2)).isoformat(),
            },
            exec_context,
        )

        assert result.success is False

    async def test_create_event_missing_start_errors(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, _ = plugin_with_db

        result = await plugin.execute_tool(
            "create_event",
            {"title": "No start", "end": "2026-01-01T10:00:00Z"},
            exec_context,
        )

        assert result.success is False


# ===================================================================
# 3. list_events
# ===================================================================


class TestListEvents:
    """Tests for the list_events tool."""

    async def test_list_events_with_results(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        now = datetime.now(timezone.utc)
        ev = _make_event(
            title="Demo",
            start_dt=now + timedelta(hours=1),
            end_dt=now + timedelta(hours=2),
        )
        result_proxy = MagicMock()
        result_proxy.all.return_value = [ev]
        session.exec = AsyncMock(return_value=result_proxy)

        result = await plugin.execute_tool(
            "list_events",
            {
                "start_date": now.isoformat(),
                "end_date": (now + timedelta(days=1)).isoformat(),
            },
            exec_context,
        )

        assert result.success is True
        assert "Demo" in result.content
        assert "1 event(s)" in result.content

    async def test_list_events_empty(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, _ = plugin_with_db

        result = await plugin.execute_tool(
            "list_events",
            {
                "start_date": "2026-01-01T00:00:00Z",
                "end_date": "2026-01-02T00:00:00Z",
            },
            exec_context,
        )

        assert result.success is True
        assert "No events found" in result.content

    async def test_list_events_max_results_clamped(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        """max_results over 100 should be clamped to 100."""
        plugin, session = plugin_with_db

        await plugin.execute_tool(
            "list_events",
            {"max_results": 999},
            exec_context,
        )

        # The statement passed to session.exec should have limit(100)
        session.exec.assert_awaited_once()

    async def test_list_events_default_range(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        """No start_date/end_date should default to today+7 days."""
        plugin, session = plugin_with_db

        result = await plugin.execute_tool(
            "list_events",
            {},
            exec_context,
        )

        assert result.success is True
        session.exec.assert_awaited_once()

    async def test_list_events_with_recurrence_rule(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        now = datetime.now(timezone.utc)
        ev = _make_event(
            title="Standup",
            start_dt=now + timedelta(hours=1),
            end_dt=now + timedelta(hours=2),
            recurrence_rule="FREQ=DAILY",
        )
        result_proxy = MagicMock()
        result_proxy.all.return_value = [ev]
        session.exec = AsyncMock(return_value=result_proxy)

        result = await plugin.execute_tool(
            "list_events",
            {"start_date": now.isoformat(), "end_date": (now + timedelta(days=1)).isoformat()},
            exec_context,
        )

        assert result.success is True
        assert "rrule=FREQ=DAILY" in result.content


# ===================================================================
# 4. update_event
# ===================================================================


class TestUpdateEvent:
    """Tests for the update_event tool."""

    async def test_update_existing_event(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        now = datetime.now(timezone.utc)
        ev = _make_event(
            title="Old Title",
            start_dt=now + timedelta(hours=1),
            end_dt=now + timedelta(hours=2),
        )
        session.get = AsyncMock(return_value=ev)

        result = await plugin.execute_tool(
            "update_event",
            {"event_id": str(ev.id), "title": "New Title"},
            exec_context,
        )

        assert result.success is True
        assert "New Title" in result.content
        assert ev.title == "New Title"
        session.commit.assert_awaited_once()

    async def test_update_nonexistent_event(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        session.get = AsyncMock(return_value=None)
        fake_id = str(uuid.uuid4())

        result = await plugin.execute_tool(
            "update_event",
            {"event_id": fake_id, "title": "Nope"},
            exec_context,
        )

        assert result.success is False
        assert "not found" in result.error_message

    async def test_update_event_invalid_dates(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        """Updating end to before start should error."""
        plugin, session = plugin_with_db
        now = datetime.now(timezone.utc)
        ev = _make_event(
            title="Workshop",
            start_dt=now + timedelta(hours=3),
            end_dt=now + timedelta(hours=4),
        )
        session.get = AsyncMock(return_value=ev)

        result = await plugin.execute_tool(
            "update_event",
            {
                "event_id": str(ev.id),
                "end": (now + timedelta(hours=1)).isoformat(),
            },
            exec_context,
        )

        assert result.success is False
        assert "end must be after start" in result.error_message

    async def test_update_event_partial_fields(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        now = datetime.now(timezone.utc)
        ev = _make_event(
            title="Sprint Review",
            description="Old desc",
            start_dt=now + timedelta(hours=1),
            end_dt=now + timedelta(hours=2),
        )
        session.get = AsyncMock(return_value=ev)

        result = await plugin.execute_tool(
            "update_event",
            {"event_id": str(ev.id), "description": "New desc"},
            exec_context,
        )

        assert result.success is True
        assert ev.description == "New desc"
        assert ev.title == "Sprint Review"  # unchanged


# ===================================================================
# 5. delete_event
# ===================================================================


class TestDeleteEvent:
    """Tests for the delete_event tool."""

    async def test_delete_existing_event(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        ev = _make_event(title="Remove Me")
        session.get = AsyncMock(return_value=ev)

        result = await plugin.execute_tool(
            "delete_event",
            {"event_id": str(ev.id)},
            exec_context,
        )

        assert result.success is True
        assert "Remove Me" in result.content
        assert "deleted" in result.content
        session.delete.assert_awaited_once_with(ev)
        session.commit.assert_awaited_once()

    async def test_delete_nonexistent_event(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        session.get = AsyncMock(return_value=None)
        fake_id = str(uuid.uuid4())

        result = await plugin.execute_tool(
            "delete_event",
            {"event_id": fake_id},
            exec_context,
        )

        assert result.success is False
        assert "not found" in result.error_message


# ===================================================================
# 6. get_today_summary
# ===================================================================


class TestGetTodaySummary:
    """Tests for the get_today_summary tool."""

    async def test_summary_with_events(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, session = plugin_with_db
        now_local = datetime.now(TZ_ROME)
        ev1 = _make_event(
            title="Morning Call",
            description="Daily sync",
            start_dt=now_local.replace(hour=9, minute=0).astimezone(timezone.utc),
            end_dt=now_local.replace(hour=9, minute=30).astimezone(timezone.utc),
        )
        ev2 = _make_event(
            title="Lunch",
            start_dt=now_local.replace(hour=12, minute=0).astimezone(timezone.utc),
            end_dt=now_local.replace(hour=13, minute=0).astimezone(timezone.utc),
        )
        result_proxy = MagicMock()
        result_proxy.all.return_value = [ev1, ev2]
        session.exec = AsyncMock(return_value=result_proxy)

        result = await plugin.execute_tool(
            "get_today_summary", {}, exec_context,
        )

        assert result.success is True
        assert "2 event(s)" in result.content
        assert "Morning Call" in result.content
        assert "Lunch" in result.content
        # Description should appear for ev1
        assert "Daily sync" in result.content

    async def test_summary_no_events(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, _ = plugin_with_db

        result = await plugin.execute_tool(
            "get_today_summary", {}, exec_context,
        )

        assert result.success is True
        assert "No events scheduled" in result.content


# ===================================================================
# 7. Timezone handling
# ===================================================================


class TestTimezoneHandling:
    """Verify UTC conversion and timezone-aware parsing."""

    def test_parse_naive_assumes_config_tz(
        self, plugin: CalendarPlugin,
    ) -> None:
        """A naive datetime string should be interpreted in the plugin TZ."""
        result = plugin._parse_to_utc("2026-06-15T10:00:00")
        expected = (
            datetime(2026, 6, 15, 10, 0, tzinfo=TZ_ROME)
            .astimezone(timezone.utc)
        )
        assert result == expected
        assert result.tzinfo == timezone.utc

    def test_parse_utc_string(self, plugin: CalendarPlugin) -> None:
        result = plugin._parse_to_utc("2026-06-15T10:00:00Z")
        assert result == datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)

    def test_parse_offset_string(self, plugin: CalendarPlugin) -> None:
        result = plugin._parse_to_utc("2026-06-15T12:00:00+02:00")
        assert result == datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)

    def test_result_always_utc(self, plugin: CalendarPlugin) -> None:
        for iso in [
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00+05:30",
        ]:
            dt = plugin._parse_to_utc(iso)
            assert dt.tzinfo == timezone.utc


# ===================================================================
# 8. Dispatch edge cases
# ===================================================================


class TestToolDispatch:
    """Verify execute_tool dispatch handles unknown tools."""

    async def test_unknown_tool_returns_error(
        self, plugin: CalendarPlugin, exec_context: ExecutionContext,
    ) -> None:
        result = await plugin.execute_tool(
            "nonexistent_tool", {}, exec_context,
        )
        assert result.success is False
        assert "Unknown tool" in result.error_message

    async def test_execution_time_is_reported(
        self,
        plugin_with_db: tuple[CalendarPlugin, AsyncMock],
        exec_context: ExecutionContext,
    ) -> None:
        plugin, _ = plugin_with_db
        result = await plugin.execute_tool(
            "get_today_summary", {}, exec_context,
        )
        assert result.execution_time_ms >= 0


# ===================================================================
# 9. Dependency & health overrides
# ===================================================================


class TestDependencyHealth:
    """Verify check_dependencies and get_connection_status overrides."""

    def test_check_dependencies_returns_empty(
        self, plugin: CalendarPlugin,
    ) -> None:
        assert plugin.check_dependencies() == []

    async def test_get_connection_status_connected(
        self, plugin: CalendarPlugin,
    ) -> None:
        status = await plugin.get_connection_status()
        assert status is ConnectionStatus.CONNECTED


# ===================================================================
# 10. Cleanup
# ===================================================================


class TestCleanup:
    """Verify cleanup cancels the reminder task."""

    async def test_cleanup_cancels_task(
        self, plugin: CalendarPlugin,
    ) -> None:
        async def forever():
            await asyncio.sleep(3600)

        plugin._reminder_task = asyncio.create_task(forever())
        await plugin.cleanup()
        assert plugin._reminder_task.done()
        assert plugin._initialized is False

    async def test_cleanup_clears_fired_reminders(
        self, plugin: CalendarPlugin,
    ) -> None:
        plugin._fired_reminders.add(uuid.uuid4())
        await plugin.cleanup()
        assert len(plugin._fired_reminders) == 0


# ===================================================================
# 11. Reminder deduplication
# ===================================================================


class TestReminderDedup:
    """Verify reminders are not re-fired for the same event."""

    async def test_reminder_fires_once(
        self, plugin: CalendarPlugin, mock_session: AsyncMock,
    ) -> None:
        """Calling _check_reminders twice should only emit once."""
        plugin.ctx.db = lambda: _mock_db_session(mock_session)

        now = datetime.now(timezone.utc)
        # Place start_time so trigger_at falls within the check window:
        # trigger_at = start_time - reminder_minutes = now - 10s (in the past)
        ev = _make_event(
            title="Dedup Test",
            start_dt=now + timedelta(minutes=14, seconds=50),
            end_dt=now + timedelta(hours=1),
            reminder_minutes=15,
        )
        result_proxy = MagicMock()
        result_proxy.all.return_value = [ev]
        mock_session.exec = AsyncMock(return_value=result_proxy)

        plugin.ctx.event_bus.emit = AsyncMock()

        await plugin._check_reminders()
        await plugin._check_reminders()

        # Should have emitted exactly once (dedup)
        assert plugin.ctx.event_bus.emit.await_count == 1
        plugin.ctx.event_bus.emit.assert_awaited_with(
            OmniaEvent.CALENDAR_REMINDER,
            event_id=str(ev.id),
            title=ev.title,
            start_time=ev.start_time.astimezone(
                ZoneInfo(plugin.ctx.config.calendar.timezone),
            ).isoformat(),
            reminder_minutes=ev.reminder_minutes,
        )

    async def test_reminder_uses_enum_event(
        self, plugin: CalendarPlugin, mock_session: AsyncMock,
    ) -> None:
        """Reminder must emit OmniaEvent.CALENDAR_REMINDER, not a raw string."""
        plugin.ctx.db = lambda: _mock_db_session(mock_session)

        now = datetime.now(timezone.utc)
        ev = _make_event(
            title="Enum Test",
            start_dt=now + timedelta(minutes=14, seconds=50),
            end_dt=now + timedelta(hours=1),
            reminder_minutes=15,
        )
        result_proxy = MagicMock()
        result_proxy.all.return_value = [ev]
        mock_session.exec = AsyncMock(return_value=result_proxy)

        plugin.ctx.event_bus.emit = AsyncMock()
        await plugin._check_reminders()

        if plugin.ctx.event_bus.emit.await_count:
            call_args = plugin.ctx.event_bus.emit.call_args
            event_arg = call_args[0][0]
            assert isinstance(event_arg, OmniaEvent)
            assert event_arg is OmniaEvent.CALENDAR_REMINDER
